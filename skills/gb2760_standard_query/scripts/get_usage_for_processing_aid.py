import json
from typing import Any, Dict, List

from ._common import get_driver


def get_usage_for_processing_aid(code_or_name: str) -> str:
    """
    查询某个加工助剂（按 code 或名称模糊匹配）的类型、功能、使用范围、脚注等信息。

    返回 JSON 字符串，内容为数组（可能匹配多条）：
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
                WHERE pa.code = $q
                   OR pa.name_zh CONTAINS $q
                   OR pa.name_en CONTAINS $q
                RETURN pa.code AS code,
                       pa.name_zh AS name_zh,
                       pa.name_en AS name_en,
                       pa.type AS type,
                       pa.function AS function,
                       pa.usage_scope AS usage_scope,
                       pa.note AS note,
                       pa.footnote_ref AS footnote_ref
                LIMIT 20
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
        description="查询某个加工助剂的类型、功能、使用范围及脚注信息。"
    )
    parser.add_argument(
        "code_or_name",
        help="加工助剂编码或名称（支持模糊），例如 'PA001' 或 '磷酸'",
    )
    args = parser.parse_args()

    output = get_usage_for_processing_aid(args.code_or_name)
    sys.stdout.write(output)

