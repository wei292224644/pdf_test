"""
基于 Neo4j 知识图谱的对话查询系统
"""

import os
import json
import sys
from typing import Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv
from neo4j import GraphDatabase
import requests

from embedding_ollama import get_embedding

load_dotenv()

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Qwen API 配置
QWEN_API_URL = os.getenv(
    "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")

# Neo4j Schema 说明
NEO4J_SCHEMA = """
Neo4j 知识图谱 Schema（食品添加剂 GB 2760）：

节点类型：
1. Chemical（食品添加剂）
   - 属性：id（唯一，如 "01.104"）, name_zh（中文名）, name_en（英文名）
2. AdditiveCode（添加剂编码）
   - 属性：code_type（"CNS" 或 "INS"）, code（编码值）
   - 关系：REFERS_TO → Chemical
3. Function（功能）
   - 属性：name（如 "着色剂"、"增稠剂"）
   - 关系：Chemical -[:HAS_FUNCTION]-> Function
4. FoodCategory（食品分类）
   - 属性：code（如 "01.01.03"）, name（食品名称）, level（层级深度）
   - 关系：Chemical -[:PERMITTED_IN]-> FoodCategory（属性：max_usage, unit, note, scope, category_name）
   - 关系：Flavoring -[:PERMITTED_IN]-> FoodCategory（属性：max_usage, unit, note, exception_note）
   - 关系：FoodCategory -[:HAS_SUBCATEGORY]-> FoodCategory（层级关系）
5. FoodCategoryGroup（食品分类集合）
   - 属性：code（如 "FOOD_ADDITIVE_EXCEPTIONS", "NO_FLAVORING_ALLOWED"）, name
   - 关系：Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup（属性：max_usage, exclude_group）
   - 关系：FoodCategoryGroup -[:CONTAINS]-> FoodCategory
6. Flavoring（食品用香料）
   - 属性：code（唯一，如 "N001", "S0001"）, name_zh（中文名）, name_en（英文名）
   - 属性：flavoring_type（"natural" 天然 或 "synthetic" 合成）, fema_number（FEMA 编号）
   - 关系：Flavoring -[:PERMITTED_IN]-> FoodCategory（允许使用的食品分类）
7. ProcessingAid（食品工业用加工助剂）
   - 属性：code（唯一，如 "PA001"）, name_zh（中文名）, name_en（英文名）
   - 属性：type（"unlimited" C.1类型 或 "limited" C.2类型）
   - 属性：function（功能，仅 C.2 有）, usage_scope（使用范围，仅 C.2 有，文本描述）
   - 属性：note（备注，可选）, footnote_ref（脚注引用，可选）
8. Enzyme（食品用酶制剂）
   - 属性：code（唯一，如 "ENZ001"）, name_zh（中文名）, name_en（英文名）
   - 关系：Enzyme -[:HAS_SOURCE]-> EnzymeSource（来源-供体配对）
9. EnzymeSource（酶制剂来源-供体配对）
   - 属性：enzyme_code（关联的酶编码）, source_organism（来源生物体标识）, donor_organism（供体生物体标识，可选）
   - 关系：EnzymeSource -[:FROM_ORGANISM]-> Organism（来源）
   - 关系：EnzymeSource -[:USES_DONOR]-> Organism（供体，可选）
   - 注意：一个酶可以有多个 EnzymeSource，每个表示一个来源-供体配对
10. Organism（生物体，用于酶制剂的来源和供体）
   - 属性：name_zh（中文名，如 "黑曲霉"）, name_en（英文名，如 "Aspergillus niger"）
   - 注意：同一个生物体可能作为多个酶的来源或供体
"""


def call_qwen_api(
    messages: List[Dict[str, str]], model: str = "qwen-turbo"
) -> Optional[str]:
    """调用 Qwen API"""
    if not QWEN_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }

    try:
        response = requests.post(
            f"{QWEN_API_URL}/chat/completions", headers=headers, json=data, timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return (
            result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )
    except Exception as e:
        print(f"❌ Qwen API 调用失败: {e}", file=sys.stderr)
        return None


def generate_retrieval_cypher(user_query: str) -> List[str]:
    """
    使用 LLM 根据 Schema 和用户问题动态生成 Neo4j Cypher 检索语句。
    返回多条只读 Cypher（MATCH...RETURN），便于根据问题语义灵活检索。
    """
    prompt = f"""你是一个 Neo4j Cypher 专家。根据下面的知识图谱 Schema 和用户问题，生成 1～3 条用于检索的 Cypher 查询。

要求：
1. 只生成只读查询（MATCH ... RETURN），不要 DELETE/CREATE/SET/MERGE。
2. 查询条件中的具体值（如添加剂名、编码、食品分类名）请根据用户问题直接写死在查询里，不要使用 $ 参数。
3. 每条查询要能检索到与问题相关的节点和关系；可以查 Chemical、Flavoring、FoodCategory、Function、ProcessingAid、Enzyme、Organism 等节点及它们的关系。
4. 每条查询单独一行，多条之间用分号加换行分隔。不要输出 Markdown 代码块或多余解释，只输出 Cypher。

Schema：
{NEO4J_SCHEMA}

用户问题：{user_query}

请直接输出 Cypher 语句（可多行，用分号分隔多条）："""

    messages = [{"role": "user", "content": prompt}]
    result = call_qwen_api(messages)
    if not result:
        return []

    text = result.strip()
    # 去掉可能的 ```cypher ... ``` 包裹
    if "```" in text:
        import re
        parts = re.split(r"```(?:cypher)?\s*", text, flags=re.IGNORECASE)
        text = "".join(p for i, p in enumerate(parts) if i % 2 == 1) or text
    statements = []
    for raw in text.replace(";", "\n;").split(";"):
        stmt = raw.strip().strip(";").strip()
        if stmt and (stmt.upper().startswith("MATCH") or stmt.upper().startswith("CALL")):
            statements.append(stmt)
    return statements[:5]  # 最多 5 条


def _serialize_value(v: Any) -> Any:
    """将 Neo4j 返回的 Node/Relationship 等转为可 JSON 序列化的类型。"""
    if v is None:
        return None
    if hasattr(v, "keys") and hasattr(v, "get"):
        # Node / Relationship：按属性名递归序列化
        try:
            return {k: _serialize_value(v.get(k)) for k in v.keys()}
        except Exception:
            return str(v)
    if isinstance(v, (list, tuple)):
        return [_serialize_value(x) for x in v]
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def execute_cypher_context(
    driver, cypher_list: List[str], params: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """
    执行 LLM 生成的 Cypher 列表，将每条的结果转为可读的结构（list of dict），
    合并为 {"llm_cypher_results": [{"cypher": "...", "records": [...]}]}。
    若提供 params，则每条 Cypher 用该参数执行（用于向量命中后的展开查询）。
    """
    if not cypher_list:
        return {}
    results = []
    try:
        with driver.session() as session:
            for cypher in cypher_list:
                try:
                    r = session.run(cypher, params or {})
                    records = []
                    for rec in r:
                        row = {k: _serialize_value(rec.get(k)) for k in rec.keys()}
                        records.append(row)
                    results.append({"cypher": cypher[:200] + ("..." if len(cypher) > 200 else ""), "records": records[:50]})
                except Exception as e:
                    results.append({"cypher": cypher[:200], "error": str(e), "records": []})
    except Exception as e:
        print(f"⚠️ 执行 LLM 生成的 Cypher 失败: {e}", file=sys.stderr)
        return {}
    return {"llm_cypher_results": results}


def extract_entities(user_query: str) -> Dict[str, List[str]]:
    """使用 LLM 从用户查询中提取实体"""
    prompt = f"""从以下问题中提取关键实体，返回 JSON 格式：
- chemicals: 提到的食品添加剂名称列表
- food_categories: 提到的食品分类代码或名称列表
- functions: 提到的功能名称列表
- codes: 提到的 CNS/INS 编码列表
- flavorings: 提到的食品用香料名称列表（如香兰素、乙基香兰素、香荚兰豆浸膏等）
- processing_aids: 提到的加工助剂名称列表（如磷酸、甘油、活性炭等）
- enzymes: 提到的酶制剂名称列表（如α-淀粉酶、蛋白酶等）

问题：{user_query}

只返回 JSON，格式：{{"chemicals": [], "food_categories": [], "functions": [], "codes": [], "flavorings": [], "processing_aids": [], "enzymes": []}}
"""

    messages = [{"role": "user", "content": prompt}]
    result = call_qwen_api(messages)

    if not result:
        return {
            "chemicals": [],
            "food_categories": [],
            "functions": [],
            "codes": [],
            "flavorings": [],
            "processing_aids": [],
            "enzymes": [],
        }

    try:
        # 清理可能的 Markdown 代码块
        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1]) if len(lines) > 2 else result
        if result.startswith("json"):
            result = result[4:].strip()

        entities = json.loads(result)
        # 确保所有键都存在
        for key in ["chemicals", "food_categories", "functions", "codes", "flavorings", "processing_aids", "enzymes"]:
            if key not in entities:
                entities[key] = []
        return entities
    except:
        raise Exception(f"解析实体失败: {result}")


def query_graph_context(
    driver, entities: Dict[str, List[str]], max_nodes: int = 50
) -> Dict[str, Any]:
    """从 Neo4j 中查询相关图结构上下文，返回结构化数据"""
    context_data: Dict[str, Any] = {
        "chemicals": [],
        "functions": [],
        "food_categories": [],
        "codes": [],
        "flavorings": [],
        "processing_aids": [],
        "enzymes": [],
    }

    try:
        with driver.session() as session:
            # 查询化学品及其关系（含 PERMITTED_IN 与 PERMITTED_IN_GROUP）
            if entities.get("chemicals"):
                for chem in entities["chemicals"]:
                    # 1) 具体食品分类许可 PERMITTED_IN
                    query = """
                    MATCH (c:Chemical)-[r1:PERMITTED_IN]->(fc:FoodCategory)
                    WHERE c.name_zh CONTAINS $name OR c.name_en CONTAINS $name
                    WITH c, collect({
                        category_code: fc.code,
                        category_name: fc.name,
                        max_usage: r1.max_usage,
                        unit: r1.unit,
                        note: r1.note
                    }) as permissions
                    MATCH (c)-[:HAS_FUNCTION]->(f:Function)
                    WITH c, permissions, collect(f.name) as functions
                    RETURN c.name_zh, c.name_en, c.id, permissions, functions
                    LIMIT 5
                    """
                    result = session.run(query, {"name": chem})
                    for record in result:
                        chemical_data = {
                            "name_zh": record.get("c.name_zh"),
                            "name_en": record.get("c.name_en"),
                            "id": record.get("c.id"),
                            "functions": record.get("functions", []),
                            "permissions": record.get("permissions", [])[:10],  # 限制数量
                        }
                        context_data["chemicals"].append(chemical_data)

                    # 2) 各类食品除外规则 PERMITTED_IN_GROUP（表A.2 除外），并带出除外食品类别列表
                    query_group = """
                    MATCH (c:Chemical)-[r:PERMITTED_IN_GROUP]->(g:FoodCategoryGroup)
                    WHERE c.name_zh CONTAINS $name OR c.name_en CONTAINS $name
                    RETURN c.name_zh, c.id, r.max_usage, r.exclude_group, r.group_rule_description
                    LIMIT 10
                    """
                    result_group = session.run(query_group, {"name": chem})
                    group_rows = list(result_group)
                    if group_rows:
                        group_rules = []
                        for r in group_rows:
                            group_rules.append({
                                "max_usage": r.get("r.max_usage"),
                                "exclude_group": r.get("r.exclude_group"),
                                "group_rule_description": r.get("r.group_rule_description"),
                            })
                        
                        # 带出表A.2除外食品类别具体内容（FoodCategoryGroup CONTAINS FoodCategory）
                        query_excluded = """
                        MATCH (g:FoodCategoryGroup { code: 'FOOD_ADDITIVE_EXCEPTIONS' })-[r:CONTAINS]->(fc:FoodCategory)
                        RETURN r.exception_no AS no, fc.code AS code, fc.name AS name
                        ORDER BY r.exception_no
                        """
                        result_excluded = session.run(query_excluded)
                        excluded_list = [
                            {
                                "exception_no": x.get("no"),
                                "code": x.get("code"),
                                "name": x.get("name"),
                            }
                            for x in list(result_excluded)[:30]  # 最多30条
                        ]
                        
                        # 将group规则添加到最后一个chemical数据中
                        if context_data["chemicals"]:
                            context_data["chemicals"][-1]["group_rules"] = group_rules
                            context_data["chemicals"][-1]["excluded_categories"] = excluded_list

            # 查询功能相关的化学品
            if entities.get("functions"):
                for func in entities["functions"]:
                    query = """
                    MATCH (c:Chemical)-[:HAS_FUNCTION]->(f:Function {name: $func})
                    RETURN c.name_zh, c.id
                    LIMIT 20
                    """
                    result = session.run(query, {"func": func})
                    chemicals = [
                        {
                            "name_zh": r.get("c.name_zh"),
                            "id": r.get("c.id"),
                        }
                        for r in result
                    ]
                    if chemicals:
                        context_data["functions"].append({
                            "function_name": func,
                            "chemicals": chemicals,
                        })

            # 查询食品分类相关的添加剂（这部分会在后面的香料查询中处理，这里先跳过避免重复）
            # 注意：food_categories 的完整查询在香料部分统一处理

            # 查询编码对应的化学品
            if entities.get("codes"):
                for code in entities["codes"]:
                    query = """
                    MATCH (ac:AdditiveCode)-[:REFERS_TO]->(c:Chemical)
                    WHERE ac.code = $code
                    RETURN c.name_zh, c.name_en, c.id, ac.code_type
                    LIMIT 5
                    """
                    result = session.run(query, {"code": code})
                    for r in result:
                        context_data["codes"].append({
                            "code": code,
                            "code_type": r.get("ac.code_type"),
                            "chemical": {
                                "name_zh": r.get("c.name_zh"),
                                "name_en": r.get("c.name_en"),
                                "id": r.get("c.id"),
                            },
                        })

            # 查询香料及其与食品分类的关系
            if entities.get("flavorings"):
                for flavoring_name in entities["flavorings"]:
                    # 1) 查询香料基本信息
                    query_flavoring = """
                    MATCH (f:Flavoring)
                    WHERE f.name_zh CONTAINS $name OR f.name_en CONTAINS $name
                    RETURN f.code, f.name_zh, f.name_en, f.flavoring_type, f.fema_number
                    LIMIT 5
                    """
                    result = session.run(query_flavoring, {"name": flavoring_name})
                    flavoring_records = list(result)

                    if flavoring_records:
                        for f_rec in flavoring_records:
                            f_code = f_rec.get("f.code", "")
                            
                            flavoring_data = {
                                "code": f_code,
                                "name_zh": f_rec.get("f.name_zh"),
                                "name_en": f_rec.get("f.name_en"),
                                "flavoring_type": f_rec.get("f.flavoring_type"),
                                "fema_number": f_rec.get("f.fema_number"),
                                "permitted_in": [],
                                "prohibited_in": [],
                            }

                            # 2) 查询该香料允许使用的食品分类
                            query_permitted = """
                            MATCH (f:Flavoring {code: $code})-[r:PERMITTED_IN]->(fc:FoodCategory)
                            RETURN fc.code, fc.name, r.max_usage, r.unit, r.note, r.exception_note
                            ORDER BY fc.code
                            LIMIT 20
                            """
                            result_permitted = session.run(
                                query_permitted, {"code": f_code}
                            )
                            for p in result_permitted:
                                flavoring_data["permitted_in"].append({
                                    "category_code": p.get("fc.code"),
                                    "category_name": p.get("fc.name"),
                                    "max_usage": p.get("r.max_usage"),
                                    "unit": p.get("r.unit"),
                                    "note": p.get("r.note"),
                                    "exception_note": p.get("r.exception_note"),
                                })

                            # 3) 查询该香料是否在不得添加香料的食品名单中（通过反向查询）
                            query_no_flavoring = """
                            MATCH (g:FoodCategoryGroup {code: 'NO_FLAVORING_ALLOWED'})-[:CONTAINS]->(fc:FoodCategory)
                            MATCH (f:Flavoring)
                            WHERE (f.name_zh CONTAINS $name OR f.name_en CONTAINS $name)
                              AND NOT EXISTS((f)-[:PERMITTED_IN]->(fc))
                            RETURN DISTINCT fc.code, fc.name
                            LIMIT 10
                            """
                            result_no = session.run(
                                query_no_flavoring, {"name": flavoring_name}
                            )
                            for n in result_no:
                                flavoring_data["prohibited_in"].append({
                                    "category_code": n.get("fc.code"),
                                    "category_name": n.get("fc.name"),
                                })
                            
                            context_data["flavorings"].append(flavoring_data)

            # 查询食品分类是否允许添加香料
            if entities.get("food_categories"):
                for fc_query in entities["food_categories"]:
                    category_data = {
                        "query": fc_query,
                        "is_prohibited": False,
                        "category_code": None,
                        "category_name": None,
                        "exceptions": [],
                        "allowed_flavorings": [],
                        "allowed_additives": [],
                    }
                    
                    # 检查是否在不得添加香料的名单中
                    query_no_flavoring_group = """
                    MATCH (g:FoodCategoryGroup {code: 'NO_FLAVORING_ALLOWED'})-[:CONTAINS]->(fc:FoodCategory)
                    WHERE fc.code = $code OR fc.name CONTAINS $code
                    RETURN fc.code, fc.name
                    LIMIT 5
                    """
                    result_no_group = session.run(
                        query_no_flavoring_group, {"code": fc_query}
                    )
                    no_group_list = list(result_no_group)

                    if no_group_list:
                        for fc_rec in no_group_list:
                            category_data["is_prohibited"] = True
                            category_data["category_code"] = fc_rec.get("fc.code")
                            category_data["category_name"] = fc_rec.get("fc.name")

                            # 查询是否有例外情况（脚注a）
                            query_exceptions = """
                            MATCH (f:Flavoring)-[r:PERMITTED_IN]->(fc:FoodCategory {code: $code})
                            WHERE r.exception_note IS NOT NULL
                            RETURN f.name_zh, f.code, r.max_usage, r.unit, r.note, r.exception_note
                            LIMIT 10
                            """
                            result_exceptions = session.run(
                                query_exceptions, {"code": category_data["category_code"]}
                            )
                            for exc in result_exceptions:
                                category_data["exceptions"].append({
                                    "flavoring_name": exc.get("f.name_zh"),
                                    "flavoring_code": exc.get("f.code"),
                                    "max_usage": exc.get("r.max_usage"),
                                    "unit": exc.get("r.unit"),
                                    "note": exc.get("r.note"),
                                    "exception_note": exc.get("r.exception_note"),
                                })
                    else:
                        # 查询该食品分类允许使用的香料（包括子分类）
                        query_allowed_flavorings = """
                        MATCH (f:Flavoring)-[r:PERMITTED_IN]->(fc:FoodCategory)
                        WHERE fc.code = $code OR fc.name CONTAINS $code
                        RETURN f.name_zh, f.code, f.flavoring_type, r.max_usage, r.unit, r.note, fc.code AS fc_code, fc.name AS fc_name
                        LIMIT 20
                        """
                        result_allowed = session.run(
                            query_allowed_flavorings, {"code": fc_query}
                        )
                        allowed_list = list(result_allowed)

                        # 如果没找到，尝试通过层级关系查询（查询父分类的所有子分类）
                        if not allowed_list:
                            query_find_category = """
                            MATCH (fc:FoodCategory)
                            WHERE fc.code = $code OR fc.name CONTAINS $code
                            RETURN fc.code AS fc_code, fc.name AS fc_name
                            LIMIT 5
                            """
                            result_find = session.run(
                                query_find_category, {"code": fc_query}
                            )
                            found_categories = list(result_find)

                            for found_fc in found_categories:
                                found_code = found_fc.get("fc_code", "")
                                query_with_children = """
                                MATCH path = (parent:FoodCategory {code: $code})-[:HAS_SUBCATEGORY*0..]->(child:FoodCategory)
                                MATCH (f:Flavoring)-[r:PERMITTED_IN]->(child)
                                RETURN DISTINCT f.name_zh, f.code, f.flavoring_type, r.max_usage, r.unit, r.note, child.code AS fc_code, child.name AS fc_name
                                LIMIT 20
                                """
                                result_children = session.run(
                                    query_with_children, {"code": found_code}
                                )
                                allowed_list.extend(list(result_children))

                        # 去重并构建数据
                        seen_flavorings = set()
                        for a in allowed_list:
                            f_code = a.get("f.code", "")
                            fc_code = a.get("fc_code", "")
                            key = (f_code, fc_code)
                            if key in seen_flavorings:
                                continue
                            seen_flavorings.add(key)

                            category_data["allowed_flavorings"].append({
                                "flavoring_name": a.get("f.name_zh"),
                                "flavoring_code": f_code,
                                "flavoring_type": a.get("f.flavoring_type"),
                                "max_usage": a.get("r.max_usage"),
                                "unit": a.get("r.unit"),
                                "note": a.get("r.note"),
                                "category_code": fc_code,
                                "category_name": a.get("fc_name"),
                            })
                        
                        # 查询该食品分类允许使用的添加剂
                        query_additives = """
                        MATCH (c:Chemical)-[r:PERMITTED_IN]->(fc:FoodCategory)
                        WHERE fc.code = $code OR fc.name CONTAINS $code
                        RETURN c.name_zh, c.id, r.max_usage, r.unit, r.note
                        LIMIT 20
                        """
                        result_additives = session.run(query_additives, {"code": fc_query})
                        for r in result_additives:
                            category_data["allowed_additives"].append({
                                "name_zh": r.get("c.name_zh"),
                                "id": r.get("c.id"),
                                "max_usage": r.get("r.max_usage"),
                                "unit": r.get("r.unit"),
                                "note": r.get("r.note"),
                            })
                    
                    context_data["food_categories"].append(category_data)

            # 查询加工助剂
            if entities.get("processing_aids"):
                for aid_name in entities["processing_aids"]:
                    query_aid = """
                    MATCH (pa:ProcessingAid)
                    WHERE pa.name_zh CONTAINS $name OR pa.name_en CONTAINS $name
                    RETURN pa.code, pa.name_zh, pa.name_en, pa.type, pa.function, pa.usage_scope, pa.note, pa.footnote_ref, pa.sequence_no
                    LIMIT 10
                    """
                    result_aid = session.run(query_aid, {"name": aid_name})
                    for r in result_aid:
                        aid_data = {
                            "code": r.get("pa.code"),
                            "name_zh": r.get("pa.name_zh"),
                            "name_en": r.get("pa.name_en"),
                            "type": r.get("pa.type"),
                            "function": r.get("pa.function"),
                            "usage_scope": r.get("pa.usage_scope"),
                            "note": r.get("pa.note"),
                            "footnote_ref": r.get("pa.footnote_ref"),
                            "sequence_no": r.get("pa.sequence_no"),
                        }
                        context_data["processing_aids"].append(aid_data)

            # 查询酶制剂
            if entities.get("enzymes"):
                for enzyme_name in entities["enzymes"]:
                    query_enzyme = """
                    MATCH (e:Enzyme)
                    WHERE e.name_zh CONTAINS $name OR e.name_en CONTAINS $name
                    RETURN e.code, e.name_zh, e.name_en, e.sequence_no
                    LIMIT 10
                    """
                    result_enzyme = session.run(query_enzyme, {"name": enzyme_name})
                    enzyme_records = list(result_enzyme)
                    
                    for e_rec in enzyme_records:
                        enzyme_code = e_rec.get("e.code")
                        enzyme_data = {
                            "code": enzyme_code,
                            "name_zh": e_rec.get("e.name_zh"),
                            "name_en": e_rec.get("e.name_en"),
                            "sequence_no": e_rec.get("e.sequence_no"),
                            "source_pairs": [],
                        }
                        
                        # 查询该酶的所有来源-供体配对
                        query_pairs = """
                        MATCH (e:Enzyme {code: $code})-[:HAS_SOURCE]->(es:EnzymeSource)
                        MATCH (es)-[:FROM_ORGANISM]->(source:Organism)
                        OPTIONAL MATCH (es)-[:USES_DONOR]->(donor:Organism)
                        RETURN source.name_zh AS source_name_zh, source.name_en AS source_name_en,
                               donor.name_zh AS donor_name_zh, donor.name_en AS donor_name_en
                        ORDER BY source.name_zh
                        """
                        result_pairs = session.run(query_pairs, {"code": enzyme_code})
                        for p in result_pairs:
                            enzyme_data["source_pairs"].append({
                                "source_name_zh": p.get("source_name_zh"),
                                "source_name_en": p.get("source_name_en"),
                                "donor_name_zh": p.get("donor_name_zh"),
                                "donor_name_en": p.get("donor_name_en"),
                            })
                        
                        context_data["enzymes"].append(enzyme_data)

    except Exception as e:
        print(f"⚠️ 图查询错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    return context_data


# 向量索引名称（需先运行 create_vector_indexes.py，Neo4j 5.13+）
VECTOR_INDEX_CHEMICAL = "chemical_embedding"
VECTOR_INDEX_FLAVORING = "flavoring_embedding"
VECTOR_INDEX_FOOD_CATEGORY = "foodcategory_embedding"
VECTOR_INDEX_PROCESSING_AID = "processingaid_embedding"
VECTOR_INDEX_ENZYME = "enzyme_embedding"
VECTOR_SEARCH_TOP_K = 5


def get_vector_hits(
    driver, user_query: str, top_k: int = VECTOR_SEARCH_TOP_K
) -> Dict[str, List[str]]:
    """
    仅做向量 k-NN 检索，返回各标签下命中节点的 id/code 列表。
    不写任何展开逻辑，展开由 LLM 生成 Cypher 完成。
    """
    out = {
        "chemical_ids": [],
        "flavoring_codes": [],
        "food_category_codes": [],
        "processing_aid_codes": [],
        "enzyme_codes": [],
    }
    query_emb = get_embedding(user_query)
    if not query_emb:
        return out
    params = {"k": top_k, "vector": query_emb}
    try:
        with driver.session() as session:
            for index_key, index_name in [
                ("chemical_ids", VECTOR_INDEX_CHEMICAL),
                ("flavoring_codes", VECTOR_INDEX_FLAVORING),
                ("food_category_codes", VECTOR_INDEX_FOOD_CATEGORY),
                ("processing_aid_codes", VECTOR_INDEX_PROCESSING_AID),
                ("enzyme_codes", VECTOR_INDEX_ENZYME),
            ]:
                try:
                    r = session.run(
                        """
                        CALL db.index.vector.queryNodes($index, $k, $vector)
                        YIELD node
                        WHERE node.id IS NOT NULL OR node.code IS NOT NULL
                        RETURN coalesce(node.id, node.code) AS id
                        LIMIT $k
                        """,
                        {**params, "index": index_name},
                    )
                    ids = [rec["id"] for rec in r if rec.get("id")]
                    out[index_key] = ids
                except Exception:
                    out[index_key] = []
    except Exception as e:
        print(f"⚠️ 向量检索失败: {e}", file=sys.stderr)
    return out


def generate_expansion_cypher(
    vector_hits: Dict[str, List[str]], user_query: str
) -> List[str]:
    """
    根据向量命中的节点 id/code，让 LLM 生成用于展开上下文的 Cypher（带参数），
    避免手写大量展开查询。
    """
    if not any(vector_hits.values()):
        return []
    hits_json = json.dumps(vector_hits, ensure_ascii=False)
    prompt = f"""你是一个 Neo4j Cypher 专家。下面是通过向量相似度检索得到的节点 id/code 列表（与用户问题语义相关），以及知识图谱 Schema。请生成 1～5 条 Cypher 查询，用于从图中取出这些节点及其相关关系，以便回答用户问题。要求：

1. 只写只读查询（MATCH ... RETURN），不要写 DELETE/CREATE/SET。
2. 必须使用以下参数名（列表类型），在 Cypher 中用 IN 或 UNWIND 使用：
   - $chemical_ids：Chemical 的 id 列表
   - $flavoring_codes：Flavoring 的 code 列表
   - $food_category_codes：FoodCategory 的 code 列表
   - $processing_aid_codes：ProcessingAid 的 code 列表
   - $enzyme_codes：Enzyme 的 code 列表
3. 示例：MATCH (c:Chemical) WHERE c.id IN $chemical_ids 或 UNWIND $food_category_codes AS code MATCH (fc:FoodCategory {{code: code}}) ...
4. 查询应带回与许可、功能、分类等相关的信息（PERMITTED_IN、HAS_FUNCTION、CONTAINS 等），便于回答问题。
5. 只输出 Cypher，多条用分号加换行分隔，不要 Markdown 包裹和多余解释。

Schema：
{NEO4J_SCHEMA}

向量命中结果：
{hits_json}

用户问题：{user_query}

请直接输出 Cypher 语句："""

    messages = [{"role": "user", "content": prompt}]
    result = call_qwen_api(messages)
    if not result:
        return []
    text = result.strip()
    if "```" in text:
        import re
        parts = re.split(r"```(?:cypher)?\s*", text, flags=re.IGNORECASE)
        text = "".join(p for i, p in enumerate(parts) if i % 2 == 1) or text
    statements = []
    for raw in text.replace(";", "\n;").split(";"):
        stmt = raw.strip().strip(";").strip()
        if stmt and (stmt.upper().startswith("MATCH") or stmt.upper().startswith("UNWIND") or stmt.upper().startswith("CALL")):
            statements.append(stmt)
    return statements[:5]


def query_graph_context_by_vector(
    driver, user_query: str, top_k: int = VECTOR_SEARCH_TOP_K
) -> Dict[str, Any]:
    """
    向量检索 + LLM 生成展开 Cypher，不再手写展开逻辑。
    流程：get_vector_hits → generate_expansion_cypher → execute_cypher_context(带参数)。
    """
    vector_hits = get_vector_hits(driver, user_query, top_k)
    if not any(vector_hits.values()):
        return {}
    expansion_cypher = generate_expansion_cypher(vector_hits, user_query)
    if not expansion_cypher:
        return {}
    params = {
        "chemical_ids": vector_hits.get("chemical_ids") or [],
        "flavoring_codes": vector_hits.get("flavoring_codes") or [],
        "food_category_codes": vector_hits.get("food_category_codes") or [],
        "processing_aid_codes": vector_hits.get("processing_aid_codes") or [],
        "enzyme_codes": vector_hits.get("enzyme_codes") or [],
    }
    return execute_cypher_context(driver, expansion_cypher, params)


def merge_graph_context(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """合并两段图上下文，按 id/code 去重（extra 不覆盖 base 已有）。"""
    out = {k: list(v) for k, v in base.items()}
    seen_chemical_ids = {c.get("id") for c in out["chemicals"] if c.get("id")}
    for c in extra.get("chemicals", []):
        if c.get("id") and c["id"] not in seen_chemical_ids:
            out["chemicals"].append(c)
            seen_chemical_ids.add(c["id"])
    seen_flavoring_codes = {f.get("code") for f in out["flavorings"] if f.get("code")}
    for f in extra.get("flavorings", []):
        if f.get("code") and f["code"] not in seen_flavoring_codes:
            out["flavorings"].append(f)
            seen_flavoring_codes.add(f["code"])
    seen_pa_codes = {p.get("code") for p in out["processing_aids"] if p.get("code")}
    for p in extra.get("processing_aids", []):
        if p.get("code") and p["code"] not in seen_pa_codes:
            out["processing_aids"].append(p)
            seen_pa_codes.add(p["code"])
    seen_enzyme_codes = {e.get("code") for e in out["enzymes"] if e.get("code")}
    for e in extra.get("enzymes", []):
        if e.get("code") and e["code"] not in seen_enzyme_codes:
            out["enzymes"].append(e)
            seen_enzyme_codes.add(e["code"])
    for key in ("functions", "food_categories", "codes"):
        out[key] = list(base.get(key, []))
        for item in extra.get(key, []):
            if item not in out[key]:
                out[key].append(item)
    return out


def generate_answer(
    user_query: str,
    graph_context: Dict[str, Any],
    conversation_history: List[Dict[str, str]] = None,
) -> str:
    """基于图查询结果生成答案"""

    context_text = ""
    if graph_context:
        context_text += f"【图查询结果】\n{json.dumps(graph_context, ensure_ascii=False, indent=2)}\n\n"

    system_prompt = f"""你是一个食品添加剂和食品用香料知识图谱助手。根据用户的问题和提供的图查询结果，给出准确、详细的回答。

{NEO4J_SCHEMA}

要求：
1. 基于提供的图查询结果回答问题
2. 如果图查询结果中没有相关信息，明确说明
3. 回答要准确、专业、易于理解
4. 如果涉及使用范围，要列出具体的食品分类和最大使用量
5. 对于香料相关的问题，要特别说明：
   - 该香料是天然香料还是合成香料
   - 允许使用的食品分类及使用量限制
   - 是否有例外情况
   - 是否在不得添加香料的食品名单中
6. 对于加工助剂相关的问题，要特别说明：
   - 该加工助剂的类型（C.1：可在各类食品加工过程中使用，残留量不需限定；C.2：需要规定功能和使用范围）
   - 如果是 C.2 类型，要说明其功能和使用范围
   - 如果有备注信息，要一并说明
7. 对于酶制剂相关的问题，要特别说明：
   - 该酶制剂的名称（中英文）
   - 允许使用的来源和供体信息
   - 如果有多个来源，要列出所有来源和对应的供体
8. 使用中文回答
"""

    user_prompt = f"{context_text}用户问题：{user_query}\n\n请基于以上信息回答问题："

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history[-6:])

    messages.append({"role": "user", "content": user_prompt})

    answer = call_qwen_api(messages)
    return answer or "抱歉，无法生成回答。请检查 API 配置或重试。"


def chat_loop():
    """交互式对话循环"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
        print("✅ 已连接到 Neo4j")
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}", file=sys.stderr)
        return

    conversation_history = []

    print("\n" + "=" * 60)
    print("🤖 知识图谱对话查询系统")
    print("=" * 60)
    print("💡 提示：输入 'quit' 或 'exit' 退出，输入 'clear' 清空对话历史\n")

    while True:
        try:
            user_input = input("❓ 您的问题: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("👋 再见！")
                break

            if user_input.lower() == "clear":
                conversation_history = []
                print("✅ 对话历史已清空\n")
                continue

            print("\n🔍 正在分析问题...")

            # 1. 用 LLM 动态生成检索语句（Cypher），并执行
            print("🧠 正在生成检索语句...")
            cypher_list = generate_retrieval_cypher(user_input)
            llm_cypher_context = execute_cypher_context(driver, cypher_list) if cypher_list else {}

            # 2. 向量语义检索
            print("🔍 正在向量语义检索...")
            vector_ctx = query_graph_context_by_vector(driver, user_input)
            retrieval_list = llm_cypher_context.get("llm_cypher_results", [])
            vector_list = vector_ctx.get("llm_cypher_results", [])
            graph_context = {"llm_cypher_results": retrieval_list + vector_list}

            # 3. 生成答案
            print("💬 正在生成回答...")
            answer = generate_answer(
                user_input, graph_context, conversation_history
            )

            print(f"\n📊 回答:\n{answer}\n")

            # 保存到对话历史
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": answer})

        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {e}\n", file=sys.stderr)
            import traceback

            traceback.print_exc()

    driver.close()


def single_query(query: str):
    """单次查询模式"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}", file=sys.stderr)
        return

    print(f"🔍 问题: {query}\n")
    print("🔍 正在分析问题...")

    # LLM 生成 Cypher 并执行
    print("🧠 正在生成检索语句...")
    cypher_list = generate_retrieval_cypher(query)
    llm_cypher_context = execute_cypher_context(driver, cypher_list) if cypher_list else {}

    print("🔍 正在向量语义检索...")
    vector_ctx = query_graph_context_by_vector(driver, query)
    retrieval_list = llm_cypher_context.get("llm_cypher_results", [])
    vector_list = vector_ctx.get("llm_cypher_results", [])
    graph_context = {"llm_cypher_results": retrieval_list + vector_list}

    print("💬 正在生成回答...")
    answer = generate_answer(query, graph_context)

    print(f"\n📊 回答:\n{answer}")

    driver.close()


def main():
    """主函数"""
    # if len(sys.argv) > 1:
    #     query = " ".join(sys.argv[1:])
    # else:
    #     chat_loop()
    # single_query("较大婴儿和幼儿配方食品可以使用香料吗？可以使用什么香料？")
    single_query("菜罐头可以使用什么添加剂？")


if __name__ == "__main__":
    main()
