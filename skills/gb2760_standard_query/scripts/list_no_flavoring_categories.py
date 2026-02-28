import json
from typing import Any, Dict, List

from ._common import get_driver


def list_no_flavoring_categories() -> str:
    """
    列出“不得添加食品用香料、香精的食品名单”中的所有食品分类。
    对应 FoodCategoryGroup {code:'NO_FLAVORING_ALLOWED'} 下的 CONTAINS 关系。

    返回 JSON 字符串，内容为数组：
    [{ "category_code": ..., "category_name": ... }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (g:FoodCategoryGroup {code: 'NO_FLAVORING_ALLOWED'})-[:CONTAINS]->(fc:FoodCategory)
                RETURN fc.code AS category_code, fc.name AS category_name
                ORDER BY fc.code
                """,
            )
            for rec in r:
                rows.append(dict(rec))
    finally:
        driver.close()

    return json.dumps(rows, ensure_ascii=False)


if __name__ == "__main__":
    import sys

    output = list_no_flavoring_categories()
    sys.stdout.write(output)

