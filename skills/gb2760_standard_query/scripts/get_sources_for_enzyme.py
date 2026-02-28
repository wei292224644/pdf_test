import json
from typing import Any, Dict, List

from ._common import get_driver


def get_sources_for_enzyme(enzyme_code_or_name: str) -> str:
    """
    查询某个酶制剂的所有来源/供体配对（EnzymeSource）。

    返回 JSON 字符串，内容为数组：
    [{
      "enzyme_code": ...,
      "enzyme_name_zh": ...,
      "enzyme_name_en": ...,
      "source_name_zh": ...,
      "source_name_en": ...,
      "donor_name_zh": ...,
      "donor_name_en": ...
    }, ...]
    """
    driver = get_driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            r = session.run(
                """
                MATCH (e:Enzyme)
                WHERE e.code = $q
                   OR e.name_zh CONTAINS $q
                   OR e.name_en CONTAINS $q
                MATCH (e)-[:HAS_SOURCE]->(es:EnzymeSource)
                MATCH (es)-[:FROM_ORGANISM]->(source:Organism)
                OPTIONAL MATCH (es)-[:USES_DONOR]->(donor:Organism)
                RETURN e.code AS enzyme_code,
                       e.name_zh AS enzyme_name_zh,
                       e.name_en AS enzyme_name_en,
                       source.name_zh AS source_name_zh,
                       source.name_en AS source_name_en,
                       donor.name_zh AS donor_name_zh,
                       donor.name_en AS donor_name_en
                ORDER BY enzyme_code, source_name_zh
                LIMIT 100
                """,
                {"q": enzyme_code_or_name},
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
        description="查询某个酶制剂的所有来源/供体配对（EnzymeSource）。"
    )
    parser.add_argument(
        "enzyme_code_or_name",
        help="酶制剂编码或名称（支持模糊），例如 'ENZ001' 或 'α-淀粉酶'",
    )
    args = parser.parse_args()

    output = get_sources_for_enzyme(args.enzyme_code_or_name)
    sys.stdout.write(output)

