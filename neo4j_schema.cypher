// =============================================================================
// Neo4j Schema: 食品添加剂 (GB 2760) 图谱
// 仅包含约束与索引，不含业务数据
// 适用 Neo4j 4.4+ / 5.x
// =============================================================================

// -----------------------------------------------------------------------------
// 1. 唯一约束 (UNIQUE CONSTRAINTS)
// 为每个节点标签定义唯一标识，并自动创建对应唯一索引
// -----------------------------------------------------------------------------

// Chemical 食品添加剂：以 id 为唯一标识（业务中可用 CNS 或自建 ID）
CREATE CONSTRAINT chemical_id IF NOT EXISTS
FOR (n:Chemical) REQUIRE n.id IS UNIQUE;

// AdditiveCode 添加剂编码：同一编码体系下 code 唯一，(code_type, code) 联合唯一
CREATE CONSTRAINT additive_code_type_code IF NOT EXISTS
FOR (n:AdditiveCode) REQUIRE (n.code_type, n.code) IS UNIQUE;

// Function 功能：功能名称唯一
CREATE CONSTRAINT function_name IF NOT EXISTS
FOR (n:Function) REQUIRE n.name IS UNIQUE;

// FoodCategory 食品分类：GB 2760 食品分类号唯一
CREATE CONSTRAINT food_category_code IF NOT EXISTS
FOR (n:FoodCategory) REQUIRE n.code IS UNIQUE;

// FoodCategoryGroup 食品分类集合：集合编码唯一
CREATE CONSTRAINT food_category_group_code IF NOT EXISTS
FOR (n:FoodCategoryGroup) REQUIRE n.code IS UNIQUE;


// -----------------------------------------------------------------------------
// 2. 普通索引 (INDEXES)
// 用于常用查询字段，加速 WHERE / 关系匹配
// -----------------------------------------------------------------------------

// Chemical: 按中文名、英文名查询
CREATE INDEX chemical_name_zh IF NOT EXISTS
FOR (n:Chemical) ON (n.name_zh);

CREATE INDEX chemical_name_en IF NOT EXISTS
FOR (n:Chemical) ON (n.name_en);

// AdditiveCode: 按 code 查询（跨类型查编码时用）
CREATE INDEX additive_code_code IF NOT EXISTS
FOR (n:AdditiveCode) ON (n.code);

// FoodCategory: 按名称查询、按 code 前缀查层级
CREATE INDEX food_category_name IF NOT EXISTS
FOR (n:FoodCategory) ON (n.name);

// FoodCategoryGroup: 按名称查询（若有 name 字段）
CREATE INDEX food_category_group_name IF NOT EXISTS
FOR (n:FoodCategoryGroup) ON (n.name);


// -----------------------------------------------------------------------------
// 3. 关系属性索引 (可选，用于按关系属性过滤/聚合)
// 若常按 max_usage、exclude_group 等查询可保留
// -----------------------------------------------------------------------------

// PERMITTED_IN 关系的 max_usage 范围查询
CREATE INDEX permitted_in_max_usage IF NOT EXISTS
FOR ()-[r:PERMITTED_IN]-() ON (r.max_usage);

// PERMITTED_IN_GROUP 的 exclude_group 过滤
CREATE INDEX permitted_in_group_exclude_group IF NOT EXISTS
FOR ()-[r:PERMITTED_IN_GROUP]-() ON (r.exclude_group);


// =============================================================================
// Schema 说明
// =============================================================================
//
// 节点标签与建议属性（仅结构，不规定全部必填）：
//
//   Chemical
//     id          (string)  必填，唯一
//     name_zh     (string)  中文名
//     name_en     (string)  英文名
//
//   AdditiveCode
//     code        (string)  必填，如 "08.002", "124"
//     code_type   (string)  必填，如 "CNS", "INS"
//
//   Function
//     name        (string)  必填，如 "增稠剂", "着色剂"
//
//   FoodCategory
//     code        (string)  必填，食品分类号，如 "01.01.03"
//     name        (string)  食品名称
//
//   FoodCategoryGroup
//     code        (string)  必填，如 "ALL_FOOD", "TABLE_A2_EXCEPTIONS"
//     name        (string)  可选
//
// 关系类型与属性：
//
//   AdditiveCode -[:REFERS_TO]-> Chemical
//
//   Chemical -[:HAS_FUNCTION]-> Function
//
//   Chemical -[:PERMITTED_IN]-> FoodCategory
//     max_usage   (string)  如 "0.05", "按生产需要适量使用"
//     unit        (string)  如 "g/kg", "g/L"
//     note        (string)  备注
//
//   Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup
//     max_usage     (string)
//     exclude_group (string)  排除的组，如 "1~68"
//
//   FoodCategoryGroup -[:CONTAINS]-> FoodCategory
//
// =============================================================================
