import json
from typing import Any, Dict, List

from ._common import get_driver



def get_flavorings_for_food_category(code_or_name: str) -> str:
    """
    查询某食品分类允许使用的香料列表（Flavoring-[:PERMITTED_IN]->FoodCategory）。
    支持按分类 code 精确匹配，或按名称模糊匹配。

    返回 JSON 字符串，内容为数组：
    [{
      "flavoring_code": ...,
      "flavoring_name_zh": ...,
      "flavoring_name_en": ...,
      "flavoring_type": ...,
      "max_usage": ...,
      "unit": ...,
      "note": ...,
      "exception_note": ...,
      "category_code": ...,
      "category_name": ...
    }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (f:Flavoring)-[r:PERMITTED_IN]->(fc:FoodCategory)
                WHERE fc.code = $q OR fc.name CONTAINS $q
                RETURN f.code AS flavoring_code,
                       f.name_zh AS flavoring_name_zh,
                       f.name_en AS flavoring_name_en,
                       f.flavoring_type AS flavoring_type,
                       r.max_usage AS max_usage,
                       r.unit AS unit,
                       r.note AS note,
                       r.exception_note AS exception_note,
                       fc.code AS category_code,
                       fc.name AS category_name
                ORDER BY f.code
                LIMIT 200
                """,
                {"q": code_or_name},
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
        description="查询某食品分类允许使用的香料列表（Flavoring-[:PERMITTED_IN]->FoodCategory）。"
    )
    parser.add_argument(
        "code_or_name",
        help="食品分类编码或名称关键字，例如 '04.02.02.04' 或 '蔬菜罐头'",
    )
    args = parser.parse_args()

    output = get_flavorings_for_food_category(args.code_or_name)
    sys.stdout.write(output)