"""
基于 GraphRAG 的 Neo4j 对话查询系统
结合图查询和向量检索，提供更准确的答案
"""

import os
import json
import sys
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
import requests
import chromadb
from chromadb.config import Settings

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

# ChromaDB 配置
CHROMA_DB_PATH = Path(__file__).parent / "chroma_graphrag"
CHROMA_COLLECTION_NAME = "neo4j_graph_summaries"

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


def get_vector_context(user_query: str, chroma_client, collection) -> str:
    """从向量数据库中检索相关上下文"""
    try:
        results = collection.query(query_texts=[user_query], n_results=3)

        if results and results.get("documents") and results["documents"][0]:
            contexts = results["documents"][0]
            return "\n\n".join(contexts)
    except Exception as e:
        print(f"⚠️ 向量检索错误: {e}", file=sys.stderr)

    return ""


def generate_answer_with_graphrag(
    user_query: str,
    graph_context: Dict[str, Any],
    vector_context: str,
    conversation_history: List[Dict[str, str]] = None,
) -> str:
    """使用 GraphRAG 方法生成答案"""

    # 将结构化数据转换为JSON字符串，不进行额外转义
    context_text = ""
    if graph_context:
        context_text += f"【图查询结果】\n{json.dumps(graph_context, ensure_ascii=False, indent=2)}\n\n"
    if vector_context:
        context_text += f"【相关历史信息】\n{vector_context}\n\n"

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


def store_graph_summary(collection, summary: str, query: str):
    """将图查询结果存储到向量数据库"""
    try:
        # 生成唯一 ID
        import hashlib

        doc_id = hashlib.md5(query.encode()).hexdigest()

        # 检查是否已存在
        try:
            existing = collection.get(ids=[doc_id])
            if existing and existing.get("ids"):
                return  # 已存在，跳过
        except:
            pass

        collection.add(documents=[summary], ids=[doc_id], metadatas=[{"query": query}])
    except Exception as e:
        print(f"⚠️ 向量存储错误: {e}", file=sys.stderr)


def init_chroma_db():
    """初始化 ChromaDB"""
    try:
        client = chromadb.PersistentClient(
            path=str(CHROMA_DB_PATH), settings=Settings(anonymized_telemetry=False)
        )

        # 获取或创建集合
        try:
            collection = client.get_collection(name=CHROMA_COLLECTION_NAME)
        except:
            collection = client.create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"description": "Neo4j graph summaries for GraphRAG"},
            )

        return client, collection
    except Exception as e:
        print(f"⚠️ ChromaDB 初始化失败: {e}", file=sys.stderr)
        return None, None


def chat_loop():
    """交互式对话循环"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
        print("✅ 已连接到 Neo4j")
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}", file=sys.stderr)
        return

    # 初始化 ChromaDB
    chroma_client, chroma_collection = init_chroma_db()
    if chroma_client:
        print("✅ 已连接到向量数据库")
    else:
        print("⚠️ 向量数据库未启用，将仅使用图查询")

    conversation_history = []

    print("\n" + "=" * 60)
    print("🤖 GraphRAG 知识图谱对话查询系统")
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

            # 1. 提取实体
            entities = extract_entities(user_input)
            if any(entities.values()):
                print(f"📌 识别到实体: {json.dumps(entities, ensure_ascii=False)}")

            # 2. 图查询
            print("🔎 正在查询知识图谱...")
            graph_context = query_graph_context(driver, entities)

            # 3. 向量检索
            vector_context = ""
            if chroma_collection:
                print("🔍 正在检索相关历史信息...")
                vector_context = get_vector_context(
                    user_input, chroma_client, chroma_collection
                )

            # 4. 生成答案
            print("💬 正在生成回答...")
            answer = generate_answer_with_graphrag(
                user_input, graph_context, vector_context, conversation_history
            )

            print(f"\n📊 回答:\n{answer}\n")

            # 5. 存储图查询结果到向量数据库
            if chroma_collection and graph_context:
                # 将结构化数据转换为JSON字符串存储
                graph_context_str = json.dumps(graph_context, ensure_ascii=False)
                store_graph_summary(chroma_collection, graph_context_str, user_input)

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

    chroma_client, chroma_collection = init_chroma_db()

    print(f"🔍 问题: {query}\n")
    print("🔍 正在分析问题...")

    entities = extract_entities(query)
    print(f"📌 识别到实体: {json.dumps(entities, ensure_ascii=False)}\n")

    print("🔎 正在查询知识图谱...")
    graph_context = query_graph_context(driver, entities)

    vector_context = ""
    if chroma_collection:
        print("🔍 正在检索相关历史信息...")
        vector_context = get_vector_context(query, chroma_client, chroma_collection)

    print("💬 正在生成回答...")
    answer = generate_answer_with_graphrag(query, graph_context, vector_context)

    print(f"\n📊 回答:\n{answer}")

    if chroma_collection and graph_context:
        # 将结构化数据转换为JSON字符串存储
        graph_context_str = json.dumps(graph_context, ensure_ascii=False)
        store_graph_summary(chroma_collection, graph_context_str, query)

    driver.close()


def main():
    """主函数"""
    # if len(sys.argv) > 1:
    #     query = " ".join(sys.argv[1:])
    # else:
    #     chat_loop()
    single_query("较大婴儿和幼儿配方食品可以使用香料吗？可以使用什么香料？")


if __name__ == "__main__":
    main()
