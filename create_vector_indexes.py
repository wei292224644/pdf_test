#!/usr/bin/env python3
"""
为带 embedding 的节点创建 Neo4j 向量索引（Neo4j 5.13+）。
用于 chat.py 的向量检索（db.index.vector.queryNodes）。
需先完成数据导入且节点已有 embedding 属性；向量维度与 Ollama qwen3-embedding:4b 一致。
"""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

from embedding_ollama import get_embedding

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# 带 embedding 的节点标签（与入库脚本写入一致）
LABELS_WITH_EMBEDDING = [
    "Chemical",
    "Function",
    "FoodCategory",
    "Flavoring",
    "ProcessingAid",
    "Enzyme",
    "Organism",
]


def get_embedding_dimension() -> int:
    """通过 Ollama 获取当前模型的 embedding 维度（建索引必须一致）。"""
    emb = get_embedding("test")
    if emb:
        return len(emb)
    # 若 Ollama 不可用，尝试从 Neo4j 中已有节点读取
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            r = session.run(
                "MATCH (c:Chemical) WHERE c.embedding IS NOT NULL RETURN size(c.embedding) AS dim LIMIT 1"
            )
            rec = r.single()
            if rec and rec.get("dim"):
                return int(rec["dim"])
    finally:
        driver.close()
    return 1024  # 常见默认，若不对建索引会报错


def create_vector_indexes(dimension: int) -> None:
    """为各标签创建向量索引。"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}")
        return

    with driver.session() as session:
        for label in LABELS_WITH_EMBEDDING:
            index_name = f"{label.lower()}_embedding"
            # Neo4j 5.13+ 语法；OPTIONS 内 dimension 与 similarity_function 依版本可能不同
            stmt = f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (n:{label})
            ON (n.embedding)
            OPTIONS {{
                indexConfig: {{
                    `vector.dimensions`: {dimension},
                    `vector.similarity_function`: 'cosine'
                }}
            }}
            """
            try:
                session.run(stmt)
                print(f"  ✅ 向量索引 {index_name} ({label}.embedding, dim={dimension})")
            except Exception as e:
                # 部分版本 OPTIONS 格式不同，可尝试简化
                try:
                    stmt_simple = f"""
                    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                    FOR (n:{label})
                    ON (n.embedding)
                    OPTIONS {{ `vector.dimensions`: {dimension} }}
                    """
                    session.run(stmt_simple)
                    print(f"  ✅ 向量索引 {index_name} (dim={dimension})")
                except Exception as e2:
                    print(f"  ⚠️ {label} 创建失败: {e2}")
    driver.close()
    print("向量索引创建完成。Neo4j 需 5.13+ 才支持 VECTOR INDEX。")


def main():
    print("获取 embedding 维度（Ollama 或已有节点）...")
    dim = get_embedding_dimension()
    print(f"使用维度: {dim}\n创建向量索引...")
    create_vector_indexes(dim)


if __name__ == "__main__":
    main()
