import json
from typing import Dict, List, Any

from _common import get_driver


def query_additives_for_category(category_code: str) -> str:
    """
    查询指定食品分类 code（如“04.02.02”）允许使用的食品添加剂列表。

    返回 JSON 字符串，内容为数组：
    [{
      "additive_id": ...,
      "additive_name_zh": ...,
      "additive_name_en": ...,
      "max_usage": ...,
      "unit": ...,
      "note": ...,
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
                MATCH (c:Chemical)-[r:PERMITTED_IN]->(fc:FoodCategory {code: $code})
                RETURN c.id        AS additive_id,
                       c.name_zh   AS additive_name_zh,
                       c.name_en   AS additive_name_en,
                       r.max_usage AS max_usage,
                       r.unit      AS unit,
                       r.note      AS note,
                       fc.code     AS category_code,
                       fc.name     AS category_name
                ORDER BY c.id
                LIMIT 100
                """,
                {"code": category_code},
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
        description="查询指定食品分类允许使用的食品添加剂列表。"
    )
    parser.add_argument(
        "category_code",
        help="食品分类编码，例如 '04.02.02.04'",
    )
    args = parser.parse_args()

    output = query_additives_for_category(args.category_code)
    sys.stdout.write(output)

