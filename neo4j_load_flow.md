# 法规数据入库流程（Neo4j 标准化）

基于既定 Schema，将 GB 2760 等法规中的「化学物质、编码、功能、食品分类许可、各类食品除外规则」以**固定顺序**写入图库，保证不重复、编码必关联物质、「各类食品（除外表A.2）」用 FoodCategoryGroup 表达。

---

## 1. 数据约定

### 1.1 Chemical 唯一标识（id）

- **优先**：CNS 号（如 `01.104`、`08.018`），同一物质只建一个 Chemical 节点。
- **无 CNS**：用 INS 号（如 `160e`）；INS 为「—」或空时，用规范化中文名（如去除空格/全角后的 `name_zh`）或业务自建 ID。
- 同一化学物质**禁止**用多个 id 创建多个 Chemical；后续所有编码、功能、许可都挂到该唯一 Chemical 上。

### 1.2 编码与物质

- 每条 CNS/INS 记录对应一个 **AdditiveCode** 节点，通过 **REFERS_TO** 指向唯一 Chemical。
- 不创建「孤儿」AdditiveCode；编码必须关联到已 MERGE 的 Chemical。

### 1.3 「各类食品（除外 表A.2）」类规则

- **必须**用 **FoodCategoryGroup** 表达，例如：
  - 规则：「各类食品，表A.2中编号为1~68的食品类别除外」
  - 建 FoodCategoryGroup：`code = 'FOOD_ADDITIVE_EXCEPTIONS'`，`name = '各类食品（表A.2中1~68除外）'`
  - Chemical 与该组的关系：**PERMITTED_IN_GROUP**，属性 `max_usage`、`exclude_group`（如 `'1~68'`）
- **禁止**把该规则展开成多条 Chemical -[:PERMITTED_IN]-> FoodCategory；否则与标准语义不符且数据膨胀。

### 1.4 具体食品分类许可

- 表中有明确「食品分类号 + 食品名称」且**不是**「各类食品…除外」时，使用：
  - **FoodCategory**（code + name）
  - Chemical -[:PERMITTED_IN]-> FoodCategory，属性 `max_usage`、`unit`、`note`

---

## 2. 入库顺序（标准流程）

按以下顺序执行，可避免违反约束、保证编码必关联物质、且「除外」规则只落组不展开。

| 步骤 | 说明 | 节点/关系 |
|------|------|-----------|
| 1 | 预置 FoodCategoryGroup（若尚未存在） | MERGE FoodCategoryGroup（如 FOOD_ADDITIVE_EXCEPTIONS |
| 2 | 预置 FoodCategory（按需，可批量或按条） | MERGE FoodCategory |
| 3 | 预置 Function（按需） | MERGE Function |
| 4 | 以 **Chemical.id**（CNS 优先）MERGE Chemical，写 name_zh、name_en | 1 个 Chemical/物质 |
| 5 | 对该物质的每个 CNS/INS 建 AdditiveCode，并 REFERS_TO Chemical | AdditiveCode -[:REFERS_TO]-> Chemical |
| 6 | 对该物质的每个功能建 HAS_FUNCTION | Chemical -[:HAS_FUNCTION]-> Function |
| 7a | 「各类食品（除外…）」→ PERMITTED_IN_GROUP | Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup |
| 7b | 具体食品分类许可 → PERMITTED_IN | Chemical -[:PERMITTED_IN]-> FoodCategory（max_usage, unit, note） |
| 8 | 若 FoodCategoryGroup 的成员需在图中显式列出 | FoodCategoryGroup -[:CONTAINS]-> FoodCategory（可选） |

同一化学物质在一次导入中只执行一次步骤 4，再重复执行 5～7 不会产生新 Chemical，满足「同一化学物质不重复创建」。

---

## 3. 规则小结

1. **同一化学物质不重复创建**：Chemical 仅用 id（CNS/INS/自建）MERGE 一次。
2. **编码必须通过 REFERS_TO 关联物质**：先 MERGE Chemical，再 MERGE AdditiveCode 并创建 REFERS_TO。
3. **「各类食品（除外 A.2）」用 FoodCategoryGroup**：建组节点 + PERMITTED_IN_GROUP（max_usage、exclude_group），不展开为多条 PERMITTED_IN。
4. **具体许可用 PERMITTED_IN**：仅对「食品分类号 + 食品名称」明确的行建 FoodCategory 与 PERMITTED_IN（max_usage、unit、note）。

---

## 4. 文件说明

- **neo4j_load_examples.cypher**：按上述流程的 Cypher 示例，含：
  - 预置组/分类/功能（可选）
  - **L-苹果酸**完整示例（仅「各类食品除外表A.2」一条规则，PERMITTED_IN_GROUP）
  - **β-阿朴-8'-胡萝卜素醛**完整示例（多条具体食品分类，PERMITTED_IN）

按顺序执行该文件中的语句即可复现两条完整示例数据。

---

## 5. 参数化入库（供程序调用）

在 Python/Java 等驱动中，建议用**参数**传入变量，避免拼接 Cypher 字符串。示例（仅展示模式）：

```cypher
// 1. MERGE Chemical（id 优先 CNS）
MERGE (c:Chemical { id: $chemical_id })
SET c.name_zh = $name_zh, c.name_en = $name_en;

// 2. 编码 REFERS_TO Chemical
MERGE (ac:AdditiveCode { code_type: $code_type, code: $code })
WITH ac
MATCH (c:Chemical { id: $chemical_id })
MERGE (ac)-[:REFERS_TO]->(c);

// 3. HAS_FUNCTION
MATCH (c:Chemical { id: $chemical_id })
MERGE (f:Function { name: $function_name })
MERGE (c)-[:HAS_FUNCTION]->(f);

// 4a. 「各类食品除外」→ PERMITTED_IN_GROUP（不展开）
MATCH (c:Chemical { id: $chemical_id })
MATCH (g:FoodCategoryGroup { code: $group_code })
MERGE (c)-[r:PERMITTED_IN_GROUP]->(g)
SET r.max_usage = $max_usage, r.exclude_group = $exclude_group;

// 4b. 具体许可 → PERMITTED_IN
MATCH (c:Chemical { id: $chemical_id })
MERGE (fc:FoodCategory { code: $category_code })
SET fc.name = $category_name
WITH c, fc
MERGE (c)-[r:PERMITTED_IN]->(fc)
SET r.max_usage = $max_usage, r.unit = $unit, r.note = $note;
```

程序侧：先解析法规文本得到「化学物质、编码、功能、许可行、各类食品除外规则」，再按**入库顺序**依次执行上述模式，同一物质的 `chemical_id` 保持不变即可保证不重复创建。
