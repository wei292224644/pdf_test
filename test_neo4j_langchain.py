from langchain_core.vectorstores import VectorStoreRetriever
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain, Neo4jVector
from langchain_openai import ChatOpenAI
from langchain_ollama import OllamaEmbeddings
from dotenv import load_dotenv
import os

load_dotenv()
QWEN_API_URL = os.getenv(
    "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("LLM_MODEL", "qwen-turbo")


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b")
# base_url 必须是 Ollama 服务器根地址（如 http://localhost:11434），不能包含 /api/embed
OLLAMA_BASE_URL = os.getenv(
    "EMBEDDING_BINDING_HOST", os.getenv("OLLAMA_HOST", "http://localhost:11434")
)


def main():
    # 初始化连接和模型
    graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)
    embedding_model = OllamaEmbeddings(
        model=OLLAMA_EMBED_MODEL, base_url="http://localhost:11434"
    )

    llm = ChatOpenAI(
        model=QWEN_MODEL,
        openai_api_key=QWEN_API_KEY,
        openai_api_base=QWEN_API_URL,
        temperature=0.4,
    )

    # # FoodCategory 节点使用 name、code 属性，非默认的 text
    # vector_store = Neo4jVector.from_existing_index(
    #     embedding=embedding_model,
    #     url=NEO4J_URI,
    #     username=NEO4J_USER,
    #     password=NEO4J_PASSWORD,
    #     index_name="foodcategory_embedding",
    #     text_node_properties=["name", "code"],
    # )

    # docs_with_scores = vector_store.similarity_search_with_score("蔬菜罐头")

    # for doc, score in docs_with_scores:
    #     print(f"节点元数据: {doc.metadata}")
    #     print(f"内容: {doc.page_content}")
    #     print(f"分数: {score}")

    # 创建链并执行查询（graph 需作为关键字参数；allow_dangerous_requests 为安全确认）
    chain = GraphCypherQAChain.from_llm(
        llm,
        graph=graph,
        verbose=True,
        allow_dangerous_requests=True,
    )
    response = chain.invoke({"query": "食品分类菜罐头允许使用的食品添加剂有哪些？"})

    print(response["result"])


if __name__ == "__main__":
    main()
