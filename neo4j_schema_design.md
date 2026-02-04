# Neo4j Schema 设计：食品添加剂 (GB 2760)

## 1. 节点标签与属性

| 标签 | 说明 | 唯一键 | 建议属性 |
|------|------|--------|----------|
| **Chemical** | 食品添加剂 | `id` | `id`, `name_zh`, `name_en` |
| **AdditiveCode** | 添加剂编码（CNS/INS） | `(code_type, code)` | `code_type`, `code` |
| **Function** | 功能 | `name` | `name` |
| **FoodCategory** | 食品分类（GB 2760） | `code` | `code`, `name` |
| **FoodCategoryGroup** | 食品分类集合 | `code` | `code`, `name` |

## 2. 关系类型

| 关系 | 方向 | 属性 |
|------|------|------|
| **REFERS_TO** | AdditiveCode → Chemical | — |
| **HAS_FUNCTION** | Chemical → Function | — |
| **PERMITTED_IN** | Chemical → FoodCategory | `max_usage`, `unit`, `note`, `scope`（范围限定，如「仅限植脂末」）, `category_name`（当前行完整食品名称，便于按条处理） |
| **PERMITTED_IN_GROUP** | Chemical → FoodCategoryGroup | `max_usage`, `exclude_group`（**整数数组**，如 [1,2,3,4,6,7,…,68]，由 1~4、6~9、11~30 等展开）, `group_rule_description`（原始完整描述） |
| **CONTAINS** | FoodCategoryGroup → FoodCategory | `exception_no`（表 A.2 例外编号 1～68，仅 FOOD_ADDITIVE_EXCEPTIONS 时使用） |

## 3. 约束与索引汇总

### 唯一约束（自动带唯一索引）

- `Chemical(id)`
- `AdditiveCode(code_type, code)`
- `Function(name)`
- `FoodCategory(code)`
- `FoodCategoryGroup(code)`

### 普通索引（常用查询）

- `Chemical`: `name_zh`, `name_en`
- `AdditiveCode`: `code`
- `FoodCategory`: `name`
- `FoodCategoryGroup`: `name`

### 关系属性索引（可选）

- `PERMITTED_IN.max_usage`
- `PERMITTED_IN_GROUP.exclude_group`

## 4. 执行方式

```bash
# 方式一：Neo4j Browser 或 Cypher Shell 中粘贴执行
# 将 neo4j_schema.cypher 内容逐段或整体执行

# 方式二：cypher-shell
cypher-shell -u neo4j -p <password> -f neo4j_schema.cypher
```

要求 Neo4j 4.4+ 或 5.x（使用 `IF NOT EXISTS`）。更早版本需去掉 `IF NOT EXISTS` 或先判断再创建。

## 5. 与 cache 数据的对应

- **Chemical**：对应“食品添加剂中文名称/英文名称”聚合后的实体，可用 CNS 或内部 ID 作为 `id`。
- **AdditiveCode**：CNS号、INS号 各一条，`code_type` 为 `"CNS"` / `"INS"`。
- **Function**：对应“功能”字段，如 增稠剂、着色剂、抗结剂。
- **FoodCategory**：先由表 E.1（cache/page_245～254）导入全部食品分类；添加剂“使用范围”中的具体许可再通过 PERMITTED_IN 关联到这些节点。
- **FoodCategoryGroup**：表 A.2 例外食品类别（cache/page_149、150）→ `FOOD_ADDITIVE_EXCEPTIONS`，并通过 CONTAINS 关联 68 条例外 FoodCategory。

## 6. 数据导入顺序（推荐）

1. 执行 **neo4j_schema.cypher**（约束与索引）
2. 执行 **load_categories_to_neo4j.py**（表 E.1 → FoodCategory；表 A.2 → FoodCategoryGroup + CONTAINS）
3. 执行 **load_cache_to_neo4j.py**（表 A.1 添加剂，排除 149/150/245～254）
