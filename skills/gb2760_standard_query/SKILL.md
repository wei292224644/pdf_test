---
name: gb2760_standard_query
description: "当用户提出与 GB 2760《食品安全国家标准 食品添加剂使用标准》相关的问题时使用本 Skill，例如：某类食品可以使用哪些添加剂/香料/加工助剂/酶制剂、某个添加剂/香料/加工助剂/酶制剂可以用于哪些食品分类、查询“不得添加食品用香料、香精的食品名单”及其例外情况。"
license: 专有，详见项目 LICENSE
---

## 概述

本 Skill 基于 Neo4j 中构建的 GB 2760 食品添加剂知识图谱以及向量索引，封装了 13 个与图谱交互的基础工具。这些工具覆盖：

- 食品分类（FoodCategory）的向量检索
- 食品添加剂（Chemical）、食品用香料（Flavoring）、加工助剂（ProcessingAid）、酶制剂（Enzyme）的向量检索
- 某个食品分类允许使用的添加剂/香料/加工助剂的结构化查询
- 某个添加剂/香料在不同食品分类中的使用范围查询
- 加工助剂的类型、功能和使用范围查询
- 酶制剂的来源/供体信息查询
- “不得添加食品用香料、香精的食品名单”的结构化获取

本文件仅描述每个工具本身的输入、输出和语义，不规定具体业务场景或调用顺序。

## 环境变量（Env 参数）

所有工具在运行时依赖以下环境变量（通常通过项目根目录的 `.env` 文件配置），如果未显式配置，将使用括号中的默认值：

- **NEO4J_URI**：Neo4j 数据库连接地址（默认：`bolt://localhost:7687`）
- **NEO4J_USER**：Neo4j 数据库用户名（默认：`neo4j`）
- **NEO4J_PASSWORD**：Neo4j 数据库密码（默认：`password`）
- **OLLAMA_EMBED_URL**：Ollama Embedding 接口地址，用于生成向量（默认：`http://localhost:11434/api/embed`）
- **OLLAMA_EMBED_MODEL**：Ollama Embedding 模型名称（默认：`qwen3-embedding:4b`）

在生产环境中，建议显式设置上述环境变量，以确保连接正确的 Neo4j 实例和向量模型服务。

## 工具说明（Tools）

### `vector_search_food_category`

**用途**  
根据自然语言的食品描述（如“菜罐头”“婴幼儿配方食品”“果味饮料”），利用 `foodcategory_embedding` 向量索引检索最相近的 `FoodCategory` 节点，实现“文本 → 食品分类编码”的语义映射。

**输出（JSON 数组）**  

```json
[
  {
    "code": "04.02.02.04",
    "name": "蔬菜罐头",
    "score": 0.8247
  }
]
```

**CLI 调用示例**

```bash
python scripts/vector_search_food_category.py "菜罐头" --top-k 5
```

---

### `query_additives_for_category`

**用途**  
给定食品分类编码（如 `"04.02.02.04"`），基于 `Chemical-[:PERMITTED_IN]->FoodCategory` 关系，返回该分类允许使用的所有食品添加剂及其使用条件（最大使用量、单位、备注等）。

**输出（JSON 数组）**  

```json
[
  {
    "additive_id": "01.104",
    "additive_name_zh": "山梨酸",
    "additive_name_en": "Sorbic acid",
    "max_usage": "0.05",
    "unit": "g/kg",
    "note": "按生产需要适量使用",
    "category_code": "04.02.02.04",
    "category_name": "蔬菜罐头"
  }
]
```

**CLI 调用示例**

```bash
python scripts/query_additives_for_category.py 04.02.02.04
```

---

### `vector_search_chemical`

**用途**  
根据关键词或简短描述（中文名、英文名、或诸如“防腐剂 山梨酸”这样的短语），利用 `chemical_embedding` 向量索引，语义检索最相近的食品添加剂 `Chemical`。

**输出（JSON 数组）**  

```json
[
  {
    "id": "01.104",
    "name_zh": "山梨酸",
    "name_en": "Sorbic acid",
    "score": 0.91
  }
]
```

**CLI 调用示例**

```bash
python scripts/vector_search_chemical.py "山梨酸" --top-k 5
```

---

### `vector_search_flavoring`

**用途**  
根据关键词（如“香兰素”“乙基香兰素”等），利用 `flavoring_embedding` 向量索引语义检索最相近的 `Flavoring`（食品用香料）。

**输出（JSON 数组）**  

```json
[
  {
    "code": "S0172",
    "name_zh": "香兰素",
    "name_en": "Vanillin",
    "flavoring_type": "synthetic",
    "score": 0.93
  }
]
```

**CLI 调用示例**

```bash
python scripts/vector_search_flavoring.py "香兰素" --top-k 5
```

---

### `vector_search_processing_aid`

**用途**  
利用 `processingaid_embedding` 向量索引，根据名称或自然语言描述语义检索最相近的 `ProcessingAid`（食品工业用加工助剂）。

**输出（JSON 数组）**  

```json
[
  {
    "code": "PA001",
    "name_zh": "磷酸",
    "name_en": "Phosphoric acid",
    "type": "limited",
    "score": 0.88
  }
]
```

**CLI 调用示例**

```bash
python scripts/vector_search_processing_aid.py "萃取溶剂" --top-k 5
```

---

### `vector_search_enzyme`

**用途**  
利用 `enzyme_embedding` 向量索引，根据名称或描述语义检索最相近的 `Enzyme`（酶制剂）。

**输出（JSON 数组）**  

```json
[
  {
    "code": "ENZ001",
    "name_zh": "α-淀粉酶",
    "name_en": "Alpha-amylase",
    "score": 0.90
  }
]
```

**CLI 调用示例**

```bash
python scripts/vector_search_enzyme.py "α-淀粉酶" --top-k 5
```

---

### `get_flavorings_for_food_category`

**用途**  
对于给定的 `FoodCategory`（按 code 精确匹配或按 name 模糊匹配），返回所有允许使用的香料（`Flavoring-[:PERMITTED_IN]->FoodCategory`），包括最大使用量、单位和例外说明。

**输出（JSON 数组）**  

```json
[
  {
    "flavoring_code": "S0172",
    "flavoring_name_zh": "香兰素",
    "flavoring_name_en": "Vanillin",
    "flavoring_type": "synthetic",
    "max_usage": "7",
    "unit": "mg/100 g",
    "note": "按即食食品计",
    "exception_note": "仅用于婴幼儿谷类辅助食品，生产企业应折算...",
    "category_code": "13.02.01",
    "category_name": "婴幼儿谷类辅助食品"
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_flavorings_for_food_category.py 04.02.02.04
```

---

### `get_processing_aids_for_food_category`

**用途**  
通过匹配 `usage_scope` 或 `note` 文本与给定分类编码/名称，近似找出与某食品分类相关的 `ProcessingAid`（加工助剂）。用于弥补 `ProcessingAid` 与 `FoodCategory` 之间未建立直接结构化关系的情况。

**输出（JSON 数组）**  

```json
[
  {
    "code": "PA010",
    "name_zh": "某加工助剂",
    "name_en": "Some processing aid",
    "type": "limited",
    "function": "萃取溶剂",
    "usage_scope": "用于蔬菜罐头的制备工艺",
    "note": "...",
    "footnote_ref": "10)"
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_processing_aids_for_food_category.py 04.02.02.04
```

---

### `get_food_categories_for_additive`

**用途**  
给定添加剂的编号或名称（支持模糊匹配），列出该添加剂通过 `PERMITTED_IN` 关系允许使用的所有 `FoodCategory`，包括最大使用量和单位。

**输出（JSON 数组）**  

```json
[
  {
    "additive_id": "01.104",
    "additive_name_zh": "山梨酸",
    "additive_name_en": "Sorbic acid",
    "category_code": "04.02.02.04",
    "category_name": "蔬菜罐头",
    "max_usage": "0.05",
    "unit": "g/kg",
    "note": "按生产需要适量使用"
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_food_categories_for_additive.py 01.104
```

---

### `get_food_categories_for_flavoring`

**用途**  
给定香料编码或名称（支持模糊匹配），列出该香料允许使用的所有 `FoodCategory`，包括最大使用量、单位和例外说明。

**输出（JSON 数组）**  

```json
[
  {
    "flavoring_code": "S0172",
    "flavoring_name_zh": "香兰素",
    "flavoring_name_en": "Vanillin",
    "flavoring_type": "synthetic",
    "category_code": "13.02.01",
    "category_name": "婴幼儿谷类辅助食品",
    "max_usage": "7",
    "unit": "mg/100 g",
    "note": "...",
    "exception_note": "仅限于..."
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_food_categories_for_flavoring.py S0172
```

---

### `get_usage_for_processing_aid`

**用途**  
返回某个 `ProcessingAid` 的详细信息：类型（C.1/C.2）、功能、使用范围、备注及脚注引用。

**输出（JSON 数组）**  

```json
[
  {
    "code": "PA001",
    "name_zh": "磷酸",
    "name_en": "Phosphoric acid",
    "type": "limited",
    "function": "萃取溶剂",
    "usage_scope": "用于制糖工艺、油脂加工工艺...",
    "note": "包括磷酸（湿法），磷酸湿法仅用于...",
    "footnote_ref": "10)"
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_usage_for_processing_aid.py PA001
```

---

### `get_sources_for_enzyme`

**用途**  
基于 `Enzyme-[:HAS_SOURCE]->EnzymeSource-[:FROM_ORGANISM]/[:USES_DONOR]->Organism` 关系，列出某个酶制剂的所有来源/供体配对。

**输出（JSON 数组）**  

```json
[
  {
    "enzyme_code": "ENZ001",
    "enzyme_name_zh": "α-淀粉酶",
    "enzyme_name_en": "Alpha-amylase",
    "source_name_zh": "黑曲霉",
    "source_name_en": "Aspergillus niger",
    "donor_name_zh": "嗜热脂解地芽孢杆菌",
    "donor_name_en": "Bacillus licheniformis"
  }
]
```

**CLI 调用示例**

```bash
python scripts/get_sources_for_enzyme.py ENZ001
```

---

### `list_no_flavoring_categories`

**用途**  
返回 `FoodCategoryGroup {code:'NO_FLAVORING_ALLOWED'}` 所包含的所有 `FoodCategory` 节点，即标准中“不得添加食品用香料、香精的食品名单”。

**输出（JSON 数组）**  

```json
[
  {
    "category_code": "13.01",
    "category_name": "婴幼儿配方食品"
  }
]
```

**CLI 调用示例**

```bash
python scripts/list_no_flavoring_categories.py
```

---

> 本 `SKILL.md` 仅声明 13 个工具本身及其返回结构，聚焦能力封装，不描述具体业务场景或调用编排方式。具体如何组合这些工具（例如通过 Agent 编排）由上层系统自行决定。
