import json
from typing import Any, Dict, List

from ._common import get_driver


def get_food_categories_for_flavoring(flavoring_code_or_name: str) -> str:
    """
    查询某个食品用香料（按 code 或名称模糊匹配）可以在哪些食品分类中使用。

    返回 JSON 字符串，内容为数组：
    [{
      "flavoring_code": ...,
      "flavoring_name_zh": ...,
      "flavoring_name_en": ...,
      "flavoring_type": ...,
      "category_code": ...,
      "category_name": ...,
      "max_usage": ...,
      "unit": ...,
      "note": ...,
      "exception_note": ...
    }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (f:Flavoring)
                WHERE f.code = $q
                   OR f.name_zh CONTAINS $q
                   OR f.name_en CONTAINS $q
                MATCH (f)-[r:PERMITTED_IN]->(fc:FoodCategory)
                RETURN f.code AS flavoring_code,
                       f.name_zh AS flavoring_name_zh,
                       f.name_en AS flavoring_name_en,
                       f.flavoring_type AS flavoring_type,
                       fc.code AS category_code,
                       fc.name AS category_name,
                       r.max_usage AS max_usage,
                       r.unit AS unit,
                       r.note AS note,
                       r.exception_note AS exception_note
                ORDER BY fc.code
                LIMIT 200
                """,
                {"q": flavoring_code_or_name},
            )
            for rec in r:
                rows.append(dict(rec))
    finally:
        driver.close()

    return json.dumps(rows, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="查询某个食品用香料可以在哪些食品分类中使用。"
    )
    parser.add_argument(
        "flavoring_code_or_name",
        help="香料编码或名称（支持模糊），例如 'S0172' 或 '香兰素'",
    )
    args = parser.parse_args()

    output = get_food_categories_for_flavoring(args.flavoring_code_or_name)
    sys.stdout.write(output)

