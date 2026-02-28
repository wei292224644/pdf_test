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

// Flavoring 食品用香料：以 code 为唯一标识（如 N001, S0001）
CREATE CONSTRAINT flavoring_code IF NOT EXISTS
FOR (n:Flavoring) REQUIRE n.code IS UNIQUE;

// ProcessingAid 食品工业用加工助剂：以 code 为唯一标识（如 PA001）
CREATE CONSTRAINT processing_aid_code IF NOT EXISTS
FOR (n:ProcessingAid) REQUIRE n.code IS UNIQUE;

// Enzyme 食品用酶制剂：以 code 为唯一标识（如 ENZ001）
CREATE CONSTRAINT enzyme_code IF NOT EXISTS
FOR (n:Enzyme) REQUIRE n.code IS UNIQUE;

// EnzymeSource 酶制剂来源-供体配对：以 (enzyme_code, source_organism, donor_organism) 为唯一标识
// 供体为空时存为空字符串 ''，约束中不能使用 COALESCE 等表达式，仅支持属性名
CREATE CONSTRAINT enzyme_source_unique IF NOT EXISTS
FOR (n:EnzymeSource) REQUIRE (n.enzyme_code, n.source_organism, n.donor_organism) IS UNIQUE;

// Organism 生物体（微生物、植物、动物等）：以 name_zh 和 name_en 组合为唯一标识
CREATE CONSTRAINT organism_name_unique IF NOT EXISTS
FOR (n:Organism) REQUIRE (n.name_zh, n.name_en) IS UNIQUE;


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

// Flavoring: 按中文名、英文名、类型查询
CREATE INDEX flavoring_name_zh IF NOT EXISTS
FOR (n:Flavoring) ON (n.name_zh);

CREATE INDEX flavoring_name_en IF NOT EXISTS
FOR (n:Flavoring) ON (n.name_en);

CREATE INDEX flavoring_type IF NOT EXISTS
FOR (n:Flavoring) ON (n.flavoring_type);

// ProcessingAid: 按中文名、英文名、类型查询
CREATE INDEX processing_aid_name_zh IF NOT EXISTS
FOR (n:ProcessingAid) ON (n.name_zh);

CREATE INDEX processing_aid_name_en IF NOT EXISTS
FOR (n:ProcessingAid) ON (n.name_en);

CREATE INDEX processing_aid_type IF NOT EXISTS
FOR (n:ProcessingAid) ON (n.type);

// Enzyme: 按中文名、英文名查询
CREATE INDEX enzyme_name_zh IF NOT EXISTS
FOR (n:Enzyme) ON (n.name_zh);

CREATE INDEX enzyme_name_en IF NOT EXISTS
FOR (n:Enzyme) ON (n.name_en);

// EnzymeSource: 按酶编码、来源生物体查询
CREATE INDEX enzyme_source_enzyme_code IF NOT EXISTS
FOR (n:EnzymeSource) ON (n.enzyme_code);

CREATE INDEX enzyme_source_source_organism IF NOT EXISTS
FOR (n:EnzymeSource) ON (n.source_organism);

// Organism: 按中文名、英文名查询
CREATE INDEX organism_name_zh IF NOT EXISTS
FOR (n:Organism) ON (n.name_zh);

CREATE INDEX organism_name_en IF NOT EXISTS
FOR (n:Organism) ON (n.name_en);


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
//     embedding   (list)    可选，Ollama qwen3-embedding:4b 向量（入库时写入）
//
//   AdditiveCode
//     code        (string)  必填，如 "08.002", "124"
//     code_type   (string)  必填，如 "CNS", "INS"
//
//   Function
//     name        (string)  必填，如 "增稠剂", "着色剂"
//     embedding   (list)    可选，Ollama 向量
//
//   FoodCategory
//     code        (string)  必填，食品分类号，如 "01.01.03"
//     name        (string)  食品名称
//     level       (int)     可选，层级深度（1=第一层如"01"，2=第二层如"01.02"，3=第三层如"01.02.03"）
//     embedding   (list)    可选，Ollama 向量（code + name）
//     层级关系：通过 HAS_SUBCATEGORY 关系表示，父分类指向子分类
//     例如：01 → 01.02 → 01.02.03
//
//   FoodCategoryGroup
//     code        (string)  必填，如 "FOOD_ADDITIVE_EXCEPTIONS"-食品添加剂的允许使用范围例外, "NO_FLAVORING_ALLOWED"-不得添加食品用香料、香精的食品名单, "ALL_FOODS"-可在各类食品加工过程中使用
//     name        (string)  可选
//     description (string)  可选
//
//   Flavoring 食品用香料
//     code          (string)  必填，唯一，如 "N001", "S0001"
//     name_zh       (string)  中文名
//     name_en       (string)  英文名
//     flavoring_type (string)  类型："natural"（天然）或 "synthetic"（合成）
//     fema_number   (string)  FEMA 编号（可选）
//     embedding     (list)    可选，Ollama 向量
//
//   ProcessingAid 食品工业用加工助剂（附录 C）
//     code          (string)  必填，唯一，如 "PA001"
//     name_zh       (string)  中文名（不含上标标记，如 "磷酸<sup>10)</sup>"应该存储为 "磷酸"）
//     name_en       (string)  英文名
//     type          (string)  类型："unlimited"（C.1：可在各类食品加工过程中使用，残留量不需限定）
//                             或 "limited"（C.2：需要规定功能和使用范围）
//     function      (string)  功能（仅 type="limited" 时有），如 "萃取溶剂"、"防黏剂"
//     usage_scope   (string)  使用范围（仅 type="limited" 时有），文本描述，如 "发酵工艺"、"糖果的加工工艺"
//                             可能包含最大使用量信息，如 "制盐工艺（最大使用量0.065 g/kg）"
//     note          (string)  备注（可选），存储脚注说明，如 "包括磷酸（湿法），磷酸湿法仅用于制糖工艺、油脂加工工艺、发酵工艺。"
//     footnote_ref  (string)  脚注引用（可选），如 "10)"，对应 name_zh 中的 <sup>10)</sup>
//     sequence_no   (int)     序号（可选）
//     embedding     (list)    可选，Ollama 向量
//
//   Enzyme 食品用酶制剂（附录 C.3）
//     code          (string)  必填，唯一，如 "ENZ001"
//     name_zh       (string)  中文名，如 "α-淀粉酶"
//     name_en       (string)  英文名，如 "Alpha-amylase"
//     sequence_no   (int)     序号（可选）
//     embedding     (list)    可选，Ollama 向量
//
//   EnzymeSource 酶制剂来源-供体配对（附录 C.3）
//     enzyme_code   (string)  必填，关联的酶编码
//     source_organism (string) 必填，来源生物体的标识（关联到 Organism）
//     donor_organism (string)  可选，供体生物体的标识（关联到 Organism）
//     注意：一个酶可以有多个 EnzymeSource，每个 EnzymeSource 表示一个来源-供体配对
//     例如：蛋白酶可以有多个来源，每个来源可能有不同的供体
//
//   Organism 生物体（微生物、植物、动物等）
//     name_zh       (string)  必填，中文名，如 "黑曲霉"
//     name_en       (string)  必填，英文名，如 "Aspergillus niger"
//     embedding     (list)    可选，Ollama 向量
//     注意：同一个生物体可能作为多个酶的来源或供体
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
//   FoodCategory -[:HAS_SUBCATEGORY]-> FoodCategory
//     表示食品分类的层级关系，父分类指向子分类
//     例如：01 -[:HAS_SUBCATEGORY]-> 01.02 -[:HAS_SUBCATEGORY]-> 01.02.03
//
//   Flavoring -[:PERMITTED_IN]-> FoodCategory
//     max_usage     (string)  最大使用量（可选）
//     unit          (string)  单位（可选）
//     note          (string)  备注（可选）
//     exception_note (string) 例外说明（可选，用于脚注a的情况）
//
//   Enzyme -[:HAS_SOURCE]-> EnzymeSource
//     表示酶制剂的一个来源-供体配对
//     一个酶可以有多个 HAS_SOURCE 关系，对应不同的来源-供体配对
//
//   EnzymeSource -[:FROM_ORGANISM]-> Organism
//     表示该来源-供体配对的来源生物体
//     每个 EnzymeSource 必须有一个 FROM_ORGANISM 关系
//
//   EnzymeSource -[:USES_DONOR]-> Organism
//     表示该来源-供体配对的供体生物体（用于基因工程）
//     每个 EnzymeSource 可以有零个或一个 USES_DONOR 关系
//     如果供体为空，则不建立此关系
//
// 查询示例：
//
//   // 查询某个酶的所有来源-供体配对
//   MATCH (e:Enzyme {code: 'ENZ001'})-[:HAS_SOURCE]->(es:EnzymeSource)
//   MATCH (es)-[:FROM_ORGANISM]->(source:Organism)
//   OPTIONAL MATCH (es)-[:USES_DONOR]->(donor:Organism)
//   RETURN e.name_zh, source.name_zh AS source_name, source.name_en AS source_name_en,
//          donor.name_zh AS donor_name, donor.name_en AS donor_name_en
//
//   // 查询某个生物体作为来源的所有酶
//   MATCH (e:Enzyme)-[:HAS_SOURCE]->(es:EnzymeSource)
//   MATCH (es)-[:FROM_ORGANISM]->(o:Organism {name_zh: '黑曲霉'})
//   RETURN DISTINCT e.name_zh, e.name_en
//
//   // 查询某个生物体作为供体的所有酶
//   MATCH (e:Enzyme)-[:HAS_SOURCE]->(es:EnzymeSource)
//   MATCH (es)-[:USES_DONOR]->(o:Organism {name_zh: '嗜热脂解地芽孢杆菌'})
//   RETURN DISTINCT e.name_zh, e.name_en
//
// =============================================================================
