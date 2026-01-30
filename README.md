# 1. 清空（可选，若需从头来）
uv run python clear_neo4j.py

# 2. Schema + 示例（约束与索引 + L-苹果酸、β-阿朴 示例）
uv run python run_neo4j_cypher.py

# 3. 食品分类与例外（E.1 → FoodCategory，A.2 → TABLE_A2_EXCEPTIONS + CONTAINS）
uv run python load_categories_to_neo4j.py

# 4. 添加剂（仅 page_128～148 等，排除 149/150/245～254）
uv run python load_cache_to_neo4j.py