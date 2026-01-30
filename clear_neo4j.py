#!/usr/bin/env python3
"""清空 Neo4j 中所有节点与关系（不删约束/索引）。"""
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def main():
    print(f"连接 Neo4j: {NEO4J_URI}")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"连接失败: {e}")
        return

    with driver.session() as session:
        result = session.run("MATCH (n) DETACH DELETE n")
        result.consume()
    driver.close()
    print("已清空 Neo4j 中所有节点与关系。（约束与索引保留）")


if __name__ == "__main__":
    main()
