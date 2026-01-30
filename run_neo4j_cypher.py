#!/usr/bin/env python3
"""执行 neo4j_schema.cypher 与 neo4j_load_examples.cypher，需本地 Neo4j 运行且 .env 配置正确。"""
import re
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def split_cypher_statements(content: str) -> list[str]:
    """按分号+换行拆成单条 Cypher，去掉纯注释块，并去掉语句内注释行。"""
    # 按 ";\n" 或 ";\r\n" 拆分
    raw = re.split(r";\s*\n", content)
    statements = []
    for block in raw:
        block = block.strip()
        if not block:
            continue
        # 去掉以 // 开头的行（整行注释）
        lines = [
            line
            for line in block.split("\n")
            if not line.strip().startswith("//") and line.strip() != ""
        ]
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        # 补回结尾分号（Neo4j 可选，但保持习惯）
        if not stmt.endswith(";"):
            stmt += ";"
        statements.append(stmt)
    return statements


def run_cypher_file(driver, path: Path) -> tuple[int, list[str]]:
    """执行一个 .cypher 文件，返回 (成功数, 错误信息列表)。"""
    text = path.read_text(encoding="utf-8")
    statements = split_cypher_statements(text)
    ok = 0
    errors = []
    for i, stmt in enumerate(statements):
        try:
            with driver.session() as session:
                session.run(stmt)
            ok += 1
        except Exception as e:
            errors.append(f"Statement {i + 1}: {e!s}")
    return ok, errors


def main():
    root = Path(__file__).resolve().parent
    schema_file = root / "neo4j_schema.cypher"
    load_file = root / "neo4j_load_examples.cypher"

    print(f"连接 Neo4j: {NEO4J_URI}")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"连接失败: {e}")
        print("请确认 Neo4j 已启动且 .env 中 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 正确。")
        return

    print("执行 Schema: neo4j_schema.cypher")
    ok1, err1 = run_cypher_file(driver, schema_file)
    print(f"  Schema: {ok1} 条成功")
    if err1:
        for e in err1:
            print(f"  错误: {e}")

    print("执行入库示例: neo4j_load_examples.cypher")
    ok2, err2 = run_cypher_file(driver, load_file)
    print(f"  入库: {ok2} 条成功")
    if err2:
        for e in err2:
            print(f"  错误: {e}")

    driver.close()
    if err1 or err2:
        raise SystemExit(1)
    print("全部执行完成。")


if __name__ == "__main__":
    main()
