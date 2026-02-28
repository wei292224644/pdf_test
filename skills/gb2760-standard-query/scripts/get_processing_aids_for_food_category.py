import json
from pathlib import Path
import sys
from typing import Any, Dict, List

from _common import get_driver


def get_processing_aids_for_food_category(code_or_name: str) -> str:
    """
    近似查询：根据食品分类 code 或名称关键字，匹配使用范围/备注中提到该分类的加工助剂 ProcessingAid。
    由于 C.1/C.2 没有结构化 FoodCategory 关系，这里采用 usage_scope/note 文本匹配。

    返回 JSON 字符串，内容为数组：
    [{
      "code": ...,
      "name_zh": ...,
      "name_en": ...,
      "type": ...,
      "function": ...,
      "usage_scope": ...,
      "note": ...,
      "footnote_ref": ...
    }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (pa:ProcessingAid)
                WHERE pa.usage_scope CONTAINS $q OR pa.note CONTAINS $q
                RETURN pa.code AS code,
                       pa.name_zh AS name_zh,
                       pa.name_en AS name_en,
                       pa.type AS type,
                       pa.function AS function,
                       pa.usage_scope AS usage_scope,
                       pa.note AS note,
                       pa.footnote_ref AS footnote_ref
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
        description="按 usage_scope/note 文本近似检索与某食品分类相关的加工助剂。"
    )
    parser.add_argument(
        "code_or_name",
        help="食品分类编码或名称关键字，例如 '04.02.02.04' 或 '蔬菜罐头'",
    )
    args = parser.parse_args()

    output = get_processing_aids_for_food_category(args.code_or_name)
    sys.stdout.write(output)

