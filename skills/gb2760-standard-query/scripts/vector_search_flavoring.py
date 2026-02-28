import json
from typing import Any, Dict, List

from _common import get_driver, get_embedding


def vector_search_flavoring(keyword: str, top_k: int = 5) -> str:
    """
    根据自然语言或名称关键词，使用 Neo4j 向量索引检索最相近的食品用香料 Flavoring。

    返回 JSON 字符串，内容为数组：
    [{ "code": ..., "name_zh": ..., "name_en": ..., "flavoring_type": ..., "score": ... }, ...]
    """
    emb = get_embedding(keyword)
    if not emb:
        return json.dumps([], ensure_ascii=False)

    results: List[Dict[str, Any]] = []
    driver = get_driver()
    try:
        with driver.session() as session:
            r = session.run(
                """
                CALL db.index.vector.queryNodes('flavoring_embedding', $k, $vector)
                YIELD node, score
                RETURN node.code AS code,
                       node.name_zh AS name_zh,
                       node.name_en AS name_en,
                       node.flavoring_type AS flavoring_type,
                       score
                ORDER BY score DESC
                LIMIT $k
                """,
                {"k": top_k, "vector": emb},
            )
            for rec in r:
                results.append(
                    {
                        "code": rec.get("code"),
                        "name_zh": rec.get("name_zh"),
                        "name_en": rec.get("name_en"),
                        "flavoring_type": rec.get("flavoring_type"),
                        "score": rec.get("score"),
                    }
                )
    finally:
        driver.close()

    return json.dumps(results, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="使用向量索引检索最相近的食品用香料（Flavoring）。"
    )
    parser.add_argument(
        "keyword",
        help="检索关键词或描述，例如 '香兰素'",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回前多少条结果，默认 5",
    )
    args = parser.parse_args()

    output = vector_search_flavoring(args.keyword, top_k=args.top_k)
    sys.stdout.write(output)

