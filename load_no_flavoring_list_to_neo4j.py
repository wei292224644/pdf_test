#!/usr/bin/env python3
"""
将 cache/page_152.md 中的"不得添加食品用香料、香精的食品名单"解析并写入 Neo4j。
同时处理脚注a的例外情况：某些香料在特定条件下可以使用。
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


def parse_table_row(line: str) -> tuple[str, str] | None:
    """解析表行：| 食品分类号 | 食品名称 |"""
    line = line.strip()
    if not line.startswith("|") or line == "|" or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < 2:
        return None
    code = parts[0]
    name = parts[1]
    # 移除脚注标记
    name = re.sub(r"<sup>a</sup>", "", name).strip()
    return code, name


def calculate_level(code: str) -> int:
    """计算食品分类号的层级深度，如 '01' -> 1, '01.02' -> 2, '01.02.03' -> 3"""
    if not code:
        return 0
    return code.count(".") + 1


def parse_footnote_a(content: str) -> dict:
    """解析脚注a的内容，提取例外情况（直接返回固定数据）"""
    # 根据 page_152.md 脚注a的内容，直接返回固定数据
    exceptions = [
        {
            "flavoring_name": "香兰素",
            "flavoring_code": "S0172",
            "max_usage": "5",
            "unit": "mg/100 mL",
            "note": "其中 100 mL 以即食食品计，生产企业应按照冲调比例折算成配方食品中的使用量",
            "exception_note": "凡使用范围涵盖 0～6 个月婴幼儿配方食品不得添加任何食用香料。",
            "food_category_code": "13.01.02",
        },
        {
            "flavoring_name": "乙基香兰素",
            "flavoring_code": "S1171",
            "max_usage": "5",
            "unit": "mg/100 mL",
            "note": "其中 100 mL 以即食食品计，生产企业应按照冲调比例折算成配方食品中的使用量",
            "exception_note": "凡使用范围涵盖 0～6 个月婴幼儿配方食品不得添加任何食用香料。",
            "food_category_code": "13.01.02",
        },
        {
            "flavoring_name": "香荚兰豆浸膏(提取物)",
            "flavoring_code": "N105",
            "max_usage": "按生产需要适量使用",
            "unit": "mg/100 mL",
            "note": "其中 100 mL 以即食食品计，生产企业应按照冲调比例折算成配方食品中的使用量",
            "exception_note": "凡使用范围涵盖 0～6 个月婴幼儿配方食品不得添加任何食用香料。",
            "food_category_code": "13.01.02",
        },
        {
            "flavoring_name": "香兰素",
            "flavoring_code": "S0172",
            "max_usage": "7",
            "unit": "mg/100 g",
            "note": "其中 100 g 以即食食品计，生产企业应按照冲调比例折算成谷类食品中的使用量",
            "exception_note": "凡使用范围涵盖 0～6 个月婴幼儿配方食品不得添加任何食用香料。",
            "food_category_code": "13.02.01",
        },
    ]

    return exceptions


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"
    filepath = cache_dir / "page_152.md"

    if not filepath.exists():
        print(f"文件不存在: {filepath}")
        return

    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")

    # 解析表格数据
    food_categories = []
    in_table = False

    for line in lines:
        if "食品分类号" in line and "食品名称" in line and "|" in line:
            in_table = True
            continue
        if not in_table:
            continue

        row = parse_table_row(line)
        if not row:
            continue

        code, name = row
        if not code or code.strip() in ("—", "-", "–"):
            continue

        food_categories.append((code.strip(), name.strip()))

    # 解析脚注a
    footnote_exceptions = parse_footnote_a(content)

    print(f"解析到 {len(food_categories)} 个不得添加香料的食品分类")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return

    with driver.session() as session:
        # 1. 创建或更新 NO_FLAVORING_ALLOWED FoodCategoryGroup
        session.run(
            """
            MERGE (g:FoodCategoryGroup { code: 'NO_FLAVORING_ALLOWED' })
            SET g.name = '不得添加食品用香料、香精的食品名单',
                g.description = '表 B.1 所列食品没有加香的必要，不得添加食品用香料、香精'
            """
        )

        # 2. 创建或更新 FoodCategory，并建立 CONTAINS 关系
        for code, name in food_categories:
            level = calculate_level(code)
            session.run(
                """
                MERGE (fc:FoodCategory { code: $code })
                ON CREATE SET fc.name = $name, fc.level = $level
                ON MATCH SET fc.level = $level
                WITH fc
                MATCH (g:FoodCategoryGroup { code: 'NO_FLAVORING_ALLOWED' })
                MERGE (g)-[:CONTAINS]->(fc)
                """,
                {"code": code, "name": name, "level": level},
            )

        # 3. 处理脚注a的例外情况：为特定香料创建 PERMITTED_IN 关系
        # 注意：这些关系会覆盖 NO_FLAVORING_ALLOWED 的限制，表示在特定条件下可以使用
        print("\n正在创建脚注a例外关系...")

        for exception in footnote_exceptions:
            flavoring_name = exception["flavoring_name"]
            flavoring_code = exception.get("flavoring_code", "")
            max_usage = exception["max_usage"]
            unit = exception["unit"]
            note = exception["note"]
            exception_note = exception["exception_note"]
            food_category_code = exception["food_category_code"]

            # 优先通过 code 匹配，如果没有 code 则通过中文名匹配
            result = session.run(
                """
                MATCH (f:Flavoring { code: $flavoring_code })
                MATCH (fc:FoodCategory { code: $food_category_code })
                MERGE (f)-[r:PERMITTED_IN]->(fc)
                SET r.max_usage = $max_usage,
                    r.unit = $unit,
                    r.note = $note,
                    r.exception_note = $exception_note
                RETURN f.name_zh, f.code
                """,
                {
                    "flavoring_code": flavoring_code,
                    "max_usage": max_usage,
                    "unit": unit,
                    "note": note,
                    "exception_note": exception_note,
                    "food_category_code": food_category_code,
                },
            )
            record = result.single()
            if record:
                print(
                    f"  ✓ 已创建关系: {record.get('f.name_zh')} ({record.get('f.code')}) -[:PERMITTED_IN]-> 13.01.02"
                )
            else:
                print(
                    f"  ⚠ 警告: 未找到香料 {flavoring_name} (code: {flavoring_code})，请确保已运行 load_flavorings_to_neo4j.py"
                )

    driver.close()
    print("\n不得添加香料名单写入完成。")
    print(
        "查询示例: MATCH (g:FoodCategoryGroup { code: 'NO_FLAVORING_ALLOWED' })-[:CONTAINS]->(fc:FoodCategory) RETURN fc"
    )


if __name__ == "__main__":
    main()
