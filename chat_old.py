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

# 用于 LLM 生成 Cypher 的简明 Schema（节点与关系）
CYPHER_SCHEMA_FOR_LLM = """
节点标签及主要属性：
- Chemical: id, name_zh, name_en
- AdditiveCode: code_type, code
- Function: name
- FoodCategory: code, name, level
- FoodCategoryGroup: code, name
- Flavoring: code, name_zh, name_en, flavoring_type
- ProcessingAid: code, name_zh, name_en, type, function, usage_scope, note
- Enzyme: code, name_zh, name_en, sequence_no
- EnzymeSource: enzyme_code, source_organism, donor_organism
- Organism: name_zh, name_en

关系类型（均为有向）及关系上的属性（RETURN 时尽量带上）：
- AdditiveCode -[:REFERS_TO]-> Chemical
- Chemical -[:HAS_FUNCTION]-> Function
- Chemical -[:PERMITTED_IN]-> FoodCategory  关系属性：r.max_usage, r.unit, r.note, r.scope, r.category_name
- Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup  关系属性：r.max_usage, r.exclude_group
- FoodCategoryGroup -[:CONTAINS]-> FoodCategory
- FoodCategory -[:HAS_SUBCATEGORY]-> FoodCategory
- Flavoring -[:PERMITTED_IN]-> FoodCategory  关系属性：r.max_usage, r.unit, r.note, r.exception_note
- Enzyme -[:HAS_SOURCE]-> EnzymeSource
- EnzymeSource -[:FROM_ORGANISM]-> Organism
- EnzymeSource -[:USES_DONOR]-> Organism
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
- organisms: 提到的生物体名称列表（如黑曲霉、枯草芽孢杆菌等，用于查询其作为酶制剂来源或供体时对应的酶）

问题：{user_query}

只返回 JSON，格式：{{"chemicals": [], "food_categories": [], "functions": [], "codes": [], "flavorings": [], "processing_aids": [], "enzymes": [], "organisms": []}}
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
            "organisms": [],
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
        for key in [
            "chemicals",
            "food_categories",
            "functions",
            "codes",
            "flavorings",
            "processing_aids",
            "enzymes",
            "organisms",
        ]:
            if key not in entities:
                entities[key] = []
        return entities
    except:
        raise Exception(f"解析实体失败: {result}")


def generate_cypher_for_question(user_query: str) -> Optional[str]:
    """使用 LLM 根据用户问题和 Schema 动态生成一条 Cypher 查询（只读）。"""
    prompt = f"""你是一个 Neo4j Cypher 专家。根据下面的图 Schema 和用户问题，生成一条且仅一条 Cypher 查询，用于从图中检索回答该问题所需的数据。

{CYPHER_SCHEMA_FOR_LLM}

要求：
1. 只生成 READ 查询（仅 MATCH、WHERE、RETURN、WITH、OPTIONAL MATCH、ORDER BY、LIMIT）。
2. 禁止使用 CREATE、MERGE、DELETE、SET、REMOVE、DROP 等写操作。
3. 对中文/名称的匹配使用 CONTAINS，例如：WHERE n.name_zh CONTAINS $name
4. 必须包含 LIMIT，且 LIMIT 不超过 100。
5. RETURN 时尽量把图中与问题相关的数据都查出来：节点属性（如 name_zh, name_en, code, id）以及关系上的属性（如 PERMITTED_IN 的 max_usage, unit, note）。不要只 RETURN id 和 name，否则无法回答使用量等问题。
6. 若问题涉及具体名称（如黑曲霉、磷酸、婴幼儿配方食品），用参数 $name 表示，在返回的 Cypher 中保留 $name；执行时会传入用户问题中出现的名称，不要写死。
7. 问「某生物体是哪些酶的来源或供体」时，正确写法示例：先 MATCH (o:Organism) WHERE o.name_zh CONTAINS $name OR o.name_en CONTAINS $name，再 MATCH (es:EnzymeSource) WHERE (es)-[:FROM_ORGANISM]->(o) OR (es)-[:USES_DONOR]->(o)，再 MATCH (e:Enzyme)-[:HAS_SOURCE]->(es)，最后 RETURN DISTINCT e.code AS enzyme_code, e.name_zh AS enzyme_name_zh, e.name_en AS enzyme_name_en。
8. 问「某食品分类允许的添加剂/香料」时，严禁写死食品分类代码。必须用参数：MATCH (fc:FoodCategory) WHERE fc.name CONTAINS $name OR fc.code = $name，再 MATCH (c:Chemical)-[r:PERMITTED_IN]->(fc)，RETURN 时必须包含 c.id, c.name_zh, c.name_en 以及 r.max_usage, r.unit, r.note（和 fc.code, fc.name 等），以便回答使用量和范围。
9. 问「哪些食品不得添加食品用香料」「不得添加香料的食品名单」时，必须查 FoodCategoryGroup 的 NO_FLAVORING_ALLOWED 名单，不要用「食品用香料」去匹配 FoodCategory（没有该名称的分类）。正确写法：MATCH (g:FoodCategoryGroup {{ code: 'NO_FLAVORING_ALLOWED' }})-[:CONTAINS]->(fc:FoodCategory) RETURN fc.code AS category_code, fc.name AS category_name ORDER BY fc.code LIMIT 100。若需同时查例外（如香兰素在婴幼儿谷类中的例外），可再 OPTIONAL MATCH (f:Flavoring)-[r:PERMITTED_IN]->(fc) WHERE r.exception_note IS NOT NULL RETURN fc.code, fc.name, f.code, f.name_zh, r.max_usage, r.unit, r.exception_note。
10. 只输出一条 Cypher，不要解释；若用代码块包裹，请使用 ```cypher 或 ``` 包裹。

用户问题：{user_query}

请输出 Cypher 查询："""

    messages = [{"role": "user", "content": prompt}]
    result = call_qwen_api(messages)
    if not result:
        return None

    text = result.strip()
    # 提取代码块中的 Cypher
    if "```" in text:
        parts = text.split("```")
        for i, p in enumerate(parts):
            p = p.strip()
            if p.startswith("cypher"):
                p = p[6:].strip()
            if p and not p.startswith("json") and "MATCH" in p.upper():
                return p.strip()
    if "MATCH" in text.upper():
        return text.strip()
    return None


def _cypher_is_readonly(cypher: str) -> bool:
    """简单检查是否为只读查询（禁止写操作关键字）。"""
    upper = cypher.upper()
    for keyword in ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE", "DROP", "DETACH"):
        if keyword in upper:
            return False
    return True


def run_dynamic_cypher(
    driver, cypher: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """执行动态 Cypher，返回记录列表（每行为 dict）。仅允许只读查询。"""
    if not cypher or not _cypher_is_readonly(cypher):
        return []
    params = params or {}
    try:
        with driver.session() as session:
            result = session.run(cypher, params)
            records = []
            for rec in result:
                records.append(dict(rec))
            return records
    except Exception as e:
        print(f"⚠️ 动态 Cypher 执行失败: {e}", file=sys.stderr)
        return []


def query_graph_context_with_llm(
    driver, user_query: str, entities: Optional[Dict[str, List[str]]] = None
) -> Dict[str, Any]:
    """通过 LLM 动态生成 Cypher 并执行，将结果放入 context 的 dynamic_query_result。"""
    cypher = generate_cypher_for_question(user_query)

    # 若 Cypher 中含 $name，优先用已提取的实体（含 food_categories），否则从问题中抽中文词
    params = {}
    if "$name" in cypher or "CONTAINS $name" in cypher or "= $name" in cypher:
        name_val = None
        if entities:
            # 食品分类、生物体、酶等按顺序取第一个作为 $name，便于按名称/代码匹配
            for key in (
                "food_categories",
                "organisms",
                "enzymes",
                "processing_aids",
                "flavorings",
                "chemicals",
            ):
                if entities.get(key):
                    name_val = entities[key][0]
                    break
        if not name_val:
            import re

            tokens = re.findall(r"[\u4e00-\u9fff]+", user_query)
            if tokens:
                name_val = max(tokens, key=len)
        if name_val:
            params["name"] = name_val
    records = run_dynamic_cypher(driver, cypher, params)
    print(f"🔎 生成的 Cypher: {cypher}")
    print(f"🔎 生成的参数: {params}")
    print(f"🔎 生成的记录: {records}")
    return {"dynamic_query_result": records}


def query_graph_context(
    driver,
    entities: Dict[str, List[str]],
    max_nodes: int = 50,
    raw_query: str = "",
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
        "organisms": [],  # 按生物体查到的酶会合并进 enzymes
    }

    try:
        # ---------- 原实体查询逻辑已注释，默认改用 LLM 动态生成 Cypher ----------
        pass
        # with driver.session() as session:
        #     # 查询化学品及其关系（含 PERMITTED_IN 与 PERMITTED_IN_GROUP）
        #     if entities.get("chemicals"):
        #         for chem in entities["chemicals"]:
        #             query = """
        #             MATCH (c:Chemical)-[r1:PERMITTED_IN]->(fc:FoodCategory)
        #             WHERE c.name_zh CONTAINS $name OR c.name_en CONTAINS $name
        #             ...
        #             """
        #             result = session.run(query, {"name": chem})
        #             ...
        #             context_data["chemicals"].append(chemical_data)

        #     (PERMITTED_IN_GROUP / functions / codes / flavorings / food_categories / processing_aids / enzymes / organisms 等实体查询逻辑已省略)

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
        dyn = graph_context.get("dynamic_query_result")
        if isinstance(dyn, list) and len(dyn) > 0:
            context_text += f"【重要】以下 dynamic_query_result 共 {len(dyn)} 条记录，回答时必须逐条列出全部 {len(dyn)} 条（可用序号列表），不得只写部分或遗漏。\n\n"
        context_text += f"【图查询结果】\n{json.dumps(graph_context, ensure_ascii=False, indent=2)}\n\n"
    if vector_context:
        context_text += f"【相关历史信息】\n{vector_context}\n\n"

    system_prompt = f"""你是一个食品添加剂和食品用香料知识图谱助手。根据用户的问题和提供的图查询结果，给出准确、详细的回答。

{NEO4J_SCHEMA}

要求：
1. 基于提供的图查询结果回答问题
2. 若图查询结果中包含 dynamic_query_result（数组），回答中必须按条数逐条列出其中每一项，条目数须与数组长度一致；不得只写一条、不得遗漏、不得用“此外”“其他”等概括代替未列出的记录。仅当 dynamic_query_result 中的记录可补充说明时，再结合其他图结果或历史信息。
3. 如果图查询结果中没有相关信息，明确说明
4. 回答要准确、专业、易于理解
5. 如果涉及使用范围，要列出具体的食品分类和最大使用量
6. 对于香料相关的问题，要特别说明：
   - 该香料是天然香料还是合成香料
   - 允许使用的食品分类及使用量限制
   - 是否有例外情况
   - 是否在不得添加香料的食品名单中
7. 对于加工助剂相关的问题，要特别说明：
   - 该加工助剂的类型（C.1：可在各类食品加工过程中使用，残留量不需限定；C.2：需要规定功能和使用范围）
   - 如果是 C.2 类型，要说明其功能和使用范围
   - 如果有备注信息，要一并说明
8. 对于酶制剂相关的问题，要特别说明：
   - 该酶制剂的名称（中英文）
   - 允许使用的来源和供体信息
   - 如果有多个来源，要列出所有来源和对应的供体
9. 使用中文回答
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
            graph_context = query_graph_context(driver, entities, raw_query=user_input)
            llm_ctx = query_graph_context_with_llm(
                driver, user_input, entities=entities
            )
            if llm_ctx:
                graph_context["dynamic_query_result"] = llm_ctx["dynamic_query_result"]
                print("🔎 已使用 LLM 动态生成并执行 Cypher，结果已合并")

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
    graph_context = query_graph_context(driver, entities, raw_query=query)
    llm_ctx = query_graph_context_with_llm(driver, query, entities=entities)
    if llm_ctx:
        graph_context["dynamic_query_result"] = llm_ctx["dynamic_query_result"]
        print("🔎 已使用 LLM 动态生成并执行 Cypher，结果已合并")

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

    # 酶制剂来源/供体
    # single_query("黑曲霉是什么酶的来源或者供体？")
    # single_query("来源于米曲霉的酶制剂有哪些？")

    # 香料与不得添加香料
    # single_query("较大婴儿和幼儿配方食品可以使用香料吗？可以使用什么香料？")
    single_query("哪些食品不得添加食品用香料？")
    # single_query("天然香料和合成香料在乳制品里的使用规定是什么？")

    # 食品添加剂与食品分类
    # single_query("婴幼儿配方食品的食品添加剂有哪些？")
    # single_query("山梨酸及其钾盐可以在哪些食品中使用？限量是多少？")
    # single_query("CNS 号 08.001 是什么添加剂？能在哪些食品里用？")
    # single_query("小麦粉（06.03.01）允许使用哪些着色剂？")

    # 加工助剂
    # single_query("C.1 加工助剂有哪些？使用范围有什么限制？")
    # single_query("硅藻土作为加工助剂的使用范围是什么？")

    # 综合
    # single_query("碳酸氢钠的功能和在烘焙食品中的用量？")
    # single_query("01.01 乳及乳制品下面有哪些子分类？")


if __name__ == "__main__":
    main()
