#!/usr/bin/env python3
"""
从 cache 导入食品分类与例外类别到 Neo4j：
- page_245～254：表 E.1 食品分类系统 → FoodCategory（code, name）
- page_149、150：表 A.2 例外食品类别 → FoodCategoryGroup FOOD_ADDITIVE_EXCEPTIONS -[:CONTAINS]-> FoodCategory
需先执行 neo4j_schema.cypher，再执行本脚本，最后执行 load_cache_to_neo4j.py。
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# 表 E.1 文件：所有食品类别
E1_PAGES = [244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254]
# 表 A.2 文件：例外食品类别（1～68）
A2_PAGES = [149, 150]


def parse_table_row(line: str, num_columns: int = 2) -> list[str] | None:
    """解析表行 | a | b | 或 | a | b | c |，返回 [a, b] 或 [a, b, c]，否则 None"""
    line = line.strip()
    if not line.startswith("|") or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < num_columns:
        return None
    return parts[:num_columns]


def parse_e1_file(content: str) -> list[tuple[str, str]]:
    """解析表 E.1：食品分类号 | 食品类别/名称，返回 [(code, name), ...]"""
    rows: list[tuple[str, str]] = []
    lines = content.split("\n")
    in_table = False
    for line in lines:
        if "食品分类号" in line and "食品类别" in line and "|" in line:
            in_table = True
            continue
        if not in_table:
            continue
        parsed = parse_table_row(line, 2)
        if not parsed:
            continue
        code, name = parsed[0].strip(), parsed[1].strip()
        if not code or code in ("—", "-") or name in ("—", "-"):
            continue
        rows.append((code, name))
    return rows


def parse_a2_file(content: str) -> list[tuple[int, str, str]]:
    """解析表 A.2：例外食品类别编号 | 食品分类号 | 食品名称，返回 [(exception_no, code, name), ...]"""
    rows: list[tuple[int, str, str]] = []
    lines = content.split("\n")
    in_table = False
    for line in lines:
        if "例外食品类别编号" in line and "食品分类号" in line and "|" in line:
            in_table = True
            continue
        if not in_table:
            continue
        parsed = parse_table_row(line, 3)
        if not parsed:
            continue
        # parsed = [编号, code, name]，编号如 "1."、"35."
        raw_no, code, name = parsed[0].strip(), parsed[1].strip(), parsed[2].strip()
        if not code or not name:
            continue
        try:
            exception_no = int(raw_no.rstrip(".").strip())
        except ValueError:
            continue
        rows.append((exception_no, code, name))
    return rows


def calculate_level(code: str) -> int:
    """计算食品分类号的层级深度，如 '01' -> 1, '01.02' -> 2, '01.02.03' -> 3"""
    if not code:
        return 0
    return code.count(".") + 1


def get_parent_code(code: str) -> str | None:
    """获取父分类的code，如 '01.02.03' -> '01.02', '01.02' -> '01', '01' -> None"""
    if not code:
        return None
    parts = code.split(".")
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1])


def build_hierarchy_relationships(driver, codes: list[str]) -> None:
    """为所有食品分类建立层级关系 HAS_SUBCATEGORY"""
    with driver.session() as session:
        for code in codes:
            parent_code = get_parent_code(code)
            if parent_code:
                # 确保父分类存在（可能不在当前列表中，但应该已经创建）
                session.run(
                    """
                    MATCH (parent:FoodCategory { code: $parent_code })
                    MATCH (child:FoodCategory { code: $code })
                    MERGE (parent)-[:HAS_SUBCATEGORY]->(child)
                    """,
                    {"parent_code": parent_code, "code": code},
                )


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"
    if not cache_dir.is_dir():
        print("cache 目录不存在。")
        return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return

    # 1) 表 E.1：导入所有 FoodCategory
    e1_rows: list[tuple[str, str]] = []
    for p in E1_PAGES:
        fp = cache_dir / f"page_{p}.md"
        if not fp.is_file():
            continue
        text = fp.read_text(encoding="utf-8")
        e1_rows.extend(parse_e1_file(text))
    # 按 code 去重，保留首次
    seen_code: set[str] = set()
    unique_e1: list[tuple[str, str]] = []
    for code, name in e1_rows:
        if code in seen_code:
            continue
        seen_code.add(code)
        unique_e1.append((code, name))

    print(
        f"表 E.1：从 page_{E1_PAGES[0]}～{E1_PAGES[-1]} 解析到 {len(unique_e1)} 条食品分类。"
    )
    
    # 按层级排序，确保父分类先于子分类创建
    sorted_e1 = sorted(unique_e1, key=lambda x: (calculate_level(x[0]), x[0]))
    
    with driver.session() as session:
        for code, name in sorted_e1:
            level = calculate_level(code)
            session.run(
                """
                MERGE (fc:FoodCategory { code: $code })
                SET fc.name = $name, fc.level = $level
                """,
                {"code": code, "name": name, "level": level},
            )
    print("  FoodCategory 写入完成（含 level 属性）。")
    
    # 建立层级关系 HAS_SUBCATEGORY
    print("  正在建立层级关系...")
    build_hierarchy_relationships(driver, [code for code, _ in sorted_e1])
    print("  层级关系 HAS_SUBCATEGORY 建立完成。")

    # 2) 表 A.2：FoodCategoryGroup FOOD_ADDITIVE_EXCEPTIONS 及 CONTAINS（带例外食品类别编号 exception_no）
    a2_rows: list[tuple[int, str, str]] = []
    for p in A2_PAGES:
        fp = cache_dir / f"page_{p}.md"
        if not fp.is_file():
            continue
        text = fp.read_text(encoding="utf-8")
        a2_rows.extend(parse_a2_file(text))

    print(
        f"表 A.2：从 page_{A2_PAGES[0]}、{A2_PAGES[-1]} 解析到 {len(a2_rows)} 条例外食品类别。"
    )
    with driver.session() as session:
        session.run(
            "MERGE (g:FoodCategoryGroup { code: 'FOOD_ADDITIVE_EXCEPTIONS' }) SET g.name = '各类食品（表A.2中编号为1~68的食品类别除外）'"
        )
        for exception_no, code, name in a2_rows:
            level = calculate_level(code)
            session.run(
                """
                MERGE (fc:FoodCategory { code: $code })
                SET fc.name = $name, fc.level = $level
                WITH fc
                MATCH (g:FoodCategoryGroup { code: 'FOOD_ADDITIVE_EXCEPTIONS' })
                MERGE (g)-[r:CONTAINS]->(fc)
                SET r.exception_no = $exception_no
                """,
                {"exception_no": exception_no, "code": code, "name": name, "level": level},
            )
            # 为A.2中的分类也建立层级关系
            parent_code = get_parent_code(code)
            if parent_code:
                session.run(
                    """
                    MATCH (parent:FoodCategory { code: $parent_code })
                    MATCH (child:FoodCategory { code: $code })
                    MERGE (parent)-[:HAS_SUBCATEGORY]->(child)
                    """,
                    {"parent_code": parent_code, "code": code},
                )
    print(
        "  FoodCategoryGroup FOOD_ADDITIVE_EXCEPTIONS 及 CONTAINS（含 exception_no）写入完成。"
    )

    driver.close()
    print("食品分类与例外类别导入完成。")


if __name__ == "__main__":
    main()
