import json
from typing import Any, Dict, List

from ._common import get_driver



def get_food_categories_for_additive(additive_id_or_name: str) -> str:
    """
    查询某个食品添加剂（按 id 或中英文名模糊匹配）可以在哪些食品分类中使用。

    返回 JSON 字符串，内容为数组：
    [{
      "additive_id": ...,
      "additive_name_zh": ...,
      "additive_name_en": ...,
      "category_code": ...,
      "category_name": ...,
      "max_usage": ...,
      "unit": ...,
      "note": ...
    }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (c:Chemical)
                WHERE c.id = $q
                   OR c.name_zh CONTAINS $q
                   OR c.name_en CONTAINS $q
                MATCH (c)-[r:PERMITTED_IN]->(fc:FoodCategory)
                RETURN c.id AS additive_id,
                       c.name_zh AS additive_name_zh,
                       c.name_en AS additive_name_en,
                       fc.code AS category_code,
                       fc.name AS category_name,
                       r.max_usage AS max_usage,
                       r.unit AS unit,
                       r.note AS note
                ORDER BY fc.code
                LIMIT 200
                """,
                {"q": additive_id_or_name},
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
        description="查询某个食品添加剂可以在哪些食品分类中使用。"
    )
    parser.add_argument(
        "additive_id_or_name",
        help="添加剂编号或中/英文名（支持模糊），例如 '01.104' 或 '山梨酸'",
    )
    args = parser.parse_args()

    output = get_food_categories_for_additive(args.additive_id_or_name)
    sys.stdout.write(output)

