import json
from typing import Any, Dict, List

from _common import get_driver, get_embedding


def vector_search_food_category(food_desc: str, top_k: int = 5) -> str:
    """
    根据自然语言的食品描述（如“菜罐头”“婴幼儿配方食品”等），
    使用 Neo4j 向量索引 foodcategory_embedding 检索最相近的食品分类 FoodCategory。

    返回 JSON 字符串，内容为数组：
    [{ "code": ..., "name": ..., "score": ... }, ...]
    """
    emb = get_embedding(food_desc)
    if not emb:
        return json.dumps([], ensure_ascii=False)

    results: List[Dict[str, Any]] = []
    driver = get_driver()
    try:
        with driver.session() as session:
            r = session.run(
                """
                CALL db.index.vector.queryNodes('foodcategory_embedding', $k, $vector)
                YIELD node, score
                RETURN node.code AS code, node.name AS name, score
                ORDER BY score DESC
                LIMIT $k
                """,
                {"k": top_k, "vector": emb},
            )
            for rec in r:
                results.append(
                    {
                        "code": rec.get("code"),
                        "name": rec.get("name"),
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
        description="根据自然语言食品描述，使用向量索引检索最相近的食品分类（FoodCategory）。"
    )
    parser.add_argument(
        "food_desc",
        help="食品描述，例如 '菜罐头'、'婴幼儿配方食品'",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回前多少条结果，默认 5",
    )
    args = parser.parse_args()

    output = vector_search_food_category(args.food_desc, top_k=args.top_k)
    sys.stdout.write(output)
