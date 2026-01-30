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
   - 属性：code（如 "01.01.03"）, name（食品名称）
   - 关系：Chemical -[:PERMITTED_IN]-> FoodCategory（属性：max_usage, unit, note, scope, category_name）
5. FoodCategoryGroup（食品分类集合）
   - 属性：code（如 "TABLE_A2_EXCEPTIONS"）, name
   - 关系：Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup（属性：max_usage, exclude_group）
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

问题：{user_query}

只返回 JSON，格式：{{"chemicals": [], "food_categories": [], "functions": [], "codes": []}}
"""

    messages = [{"role": "user", "content": prompt}]
    result = call_qwen_api(messages)

    if not result:
        return {"chemicals": [], "food_categories": [], "functions": [], "codes": []}

    try:
        # 清理可能的 Markdown 代码块
        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1]) if len(lines) > 2 else result
        if result.startswith("json"):
            result = result[4:].strip()

        entities = json.loads(result)
        return entities
    except:
        raise Exception(f"解析实体失败: {result}")


def query_graph_context(
    driver, entities: Dict[str, List[str]], max_nodes: int = 50
) -> str:
    """从 Neo4j 中查询相关图结构上下文"""
    context_parts = []

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
                        category: fc.code + ': ' + fc.name,
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
                        name_zh = record.get("c.name_zh", "")
                        name_en = record.get("c.name_en", "")
                        cid = record.get("c.id", "")
                        perms = record.get("permissions", [])
                        funcs = record.get("functions", [])

                        context_parts.append(
                            f"添加剂：{name_zh} ({name_en}), ID: {cid}"
                        )
                        if funcs:
                            context_parts.append(f"  功能：{', '.join(funcs)}")
                        if perms:
                            context_parts.append(f"  使用范围（具体食品分类）：")
                            for p in perms[:10]:  # 限制数量
                                context_parts.append(
                                    f"    - {p.get('category', '')}: {p.get('max_usage', '')} {p.get('unit', '')} {p.get('note', '')}"
                                )

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
                        context_parts.append(f"  各类食品（表A.2除外）规则：")
                        for r in group_rows:
                            desc = r.get("r.group_rule_description") or ""
                            excl = r.get("r.exclude_group")
                            usage = r.get("r.max_usage") or ""
                            # exclude_group 存为整数数组，格式化为 1,2,3,4,...
                            excl_str = ""
                            if isinstance(excl, list):
                                excl_str = ",".join(str(x) for x in excl[:50])
                                if len(excl) > 50:
                                    excl_str += f",... 共{len(excl)}项"
                            elif excl:
                                excl_str = str(excl)
                            if desc:
                                context_parts.append(
                                    f"    - {desc}；最大使用量：{usage}"
                                )
                            else:
                                context_parts.append(
                                    f"    - 除外编号：{excl_str or '-'}；最大使用量：{usage}"
                                )
                        # 带出表A.2除外食品类别具体内容（FoodCategoryGroup CONTAINS FoodCategory）
                        query_excluded = """
                        MATCH (g:FoodCategoryGroup { code: 'TABLE_A2_EXCEPTIONS' })-[r:CONTAINS]->(fc:FoodCategory)
                        RETURN r.exception_no AS no, fc.code AS code, fc.name AS name
                        ORDER BY r.exception_no
                        """
                        result_excluded = session.run(query_excluded)
                        excluded_list = list(result_excluded)
                        if excluded_list:
                            context_parts.append(
                                f"  表A.2除外食品类别（共{len(excluded_list)}项）："
                            )
                            for x in excluded_list[:30]:  # 最多展示30条，避免过长
                                context_parts.append(
                                    f"    {x.get('no')}. {x.get('code')} {x.get('name')}"
                                )
                            if len(excluded_list) > 30:
                                context_parts.append(
                                    f"    ... 等共 {len(excluded_list)} 类"
                                )

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
                        f"{r.get('c.name_zh', '')} ({r.get('c.id', '')})"
                        for r in result
                    ]
                    if chemicals:
                        context_parts.append(
                            f"功能「{func}」相关的添加剂：{', '.join(chemicals)}"
                        )

            # 查询食品分类相关的添加剂
            if entities.get("food_categories"):
                for fc in entities["food_categories"]:
                    query = """
                    MATCH (c:Chemical)-[r:PERMITTED_IN]->(fc:FoodCategory)
                    WHERE fc.code = $code OR fc.name CONTAINS $code
                    RETURN c.name_zh, c.id, r.max_usage, r.unit, r.note
                    LIMIT 20
                    """
                    result = session.run(query, {"code": fc})
                    additives = []
                    for r in result:
                        name = r.get("c.name_zh", "")
                        cid = r.get("c.id", "")
                        usage = r.get("r.max_usage", "")
                        unit = r.get("r.unit", "")
                        additives.append(f"{name} ({cid}): {usage} {unit}")
                    if additives:
                        context_parts.append(
                            f"食品分类「{fc}」可用的添加剂：{', '.join(additives[:10])}"
                        )

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
                        name_zh = r.get("c.name_zh", "")
                        name_en = r.get("c.name_en", "")
                        cid = r.get("c.id", "")
                        code_type = r.get("ac.code_type", "")
                        context_parts.append(
                            f"{code_type}编码 {code} 对应：{name_zh} ({name_en}), ID: {cid}"
                        )

    except Exception as e:
        print(f"⚠️ 图查询错误: {e}", file=sys.stderr)

    return "\n".join(context_parts) if context_parts else ""


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
    graph_context: str,
    vector_context: str,
    conversation_history: List[Dict[str, str]] = None,
) -> str:
    """使用 GraphRAG 方法生成答案"""

    context_text = ""
    if graph_context:
        context_text += f"【图查询结果】\n{graph_context}\n\n"
    if vector_context:
        context_text += f"【相关历史信息】\n{vector_context}\n\n"

    system_prompt = f"""你是一个食品添加剂知识图谱助手。根据用户的问题和提供的图查询结果，给出准确、详细的回答。

{NEO4J_SCHEMA}

要求：
1. 基于提供的图查询结果回答问题
2. 如果图查询结果中没有相关信息，明确说明
3. 回答要准确、专业、易于理解
4. 如果涉及使用范围，要列出具体的食品分类和最大使用量
5. 使用中文回答
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
                store_graph_summary(chroma_collection, graph_context, user_input)

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
        store_graph_summary(chroma_collection, graph_context, query)

    driver.close()


def main():
    """主函数"""
    # if len(sys.argv) > 1:
    #     query = " ".join(sys.argv[1:])
    # else:
    #     chat_loop()
    single_query("卡拉胶可以用在灭菌乳和高温杀菌乳中吗?")


if __name__ == "__main__":
    main()
