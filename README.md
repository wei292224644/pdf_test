# GB 2760 食品添加剂知识图谱数据导入指南

本仓库包含将 GB 2760-2024 食品添加剂标准数据导入 Neo4j 图数据库的完整流程。

## 📋 前置要求

- Python 3.10+
- Neo4j 4.4+ 或 5.x
- 已配置 `.env` 文件，包含 Neo4j 连接信息：
  ```
  NEO4J_URI=bolt://localhost:7687
  NEO4J_USER=neo4j
  NEO4J_PASSWORD=your_password
  QWEN_API_KEY=your_qwen_api_key  # chat.py 需要
  QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # 可选
  ```

### 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

**依赖说明：**
- `neo4j` - Neo4j 图数据库驱动
- `chromadb` - 向量数据库（用于 chat.py 的 GraphRAG）
- `python-dotenv` - 环境变量管理
- `requests` - HTTP 请求（chat.py 调用 Qwen API）

## 🚀 数据导入流程

按以下顺序执行脚本，确保数据完整性和关系正确建立：

### 1. 清空数据库（可选，若需从头开始）

```bash
uv run python clear_neo4j.py
```

### 2. 创建 Schema（约束与索引）

```bash
uv run python run_neo4j_cypher.py
```

或直接执行：
```bash
cypher-shell -u neo4j -p <password> -f neo4j_schema.cypher
```

这将创建：
- 节点唯一约束（Chemical, AdditiveCode, Function, FoodCategory, FoodCategoryGroup, Flavoring）
- 普通索引（用于加速查询）
- 关系属性索引

### 3. 导入食品分类系统（表 E.1）

```bash
uv run python load_categories_to_neo4j.py
```

**功能：**
- 从 `cache/page_244～254.md` 解析表 E.1 食品分类系统
- 创建 `FoodCategory` 节点，包含：
  - `code`：食品分类号（如 "01.02.03"）
  - `name`：食品名称
  - `level`：层级深度（1=第一层，2=第二层，3=第三层）
- 建立 `HAS_SUBCATEGORY` 层级关系（父分类 → 子分类）
- 从 `cache/page_149、150.md` 解析表 A.2 例外食品类别
- 创建 `FoodCategoryGroup`（code: `FOOD_ADDITIVE_EXCEPTIONS`）
- 建立 `CONTAINS` 关系

### 4. 导入食品添加剂数据（表 A.1）

```bash
uv run python load_cache_to_neo4j.py
```

**功能：**
- 从 `cache/` 目录解析食品添加剂数据（排除表 E.1 和表 A.2 文件）
- 创建 `Chemical` 节点（食品添加剂）
- 创建 `AdditiveCode` 节点（CNS/INS 编码）
- 创建 `Function` 节点（功能，如增稠剂、着色剂）
- 建立关系：
  - `AdditiveCode -[:REFERS_TO]-> Chemical`
  - `Chemical -[:HAS_FUNCTION]-> Function`
  - `Chemical -[:PERMITTED_IN]-> FoodCategory`（具体食品分类许可）
  - `Chemical -[:PERMITTED_IN_GROUP]-> FoodCategoryGroup`（各类食品除外规则）
- 自动设置 `FoodCategory.level` 属性

### 5. 导入食品用香料数据（表 B.2 和 B.3）

```bash
uv run python load_flavorings_to_neo4j.py
```

**功能：**
- 从 `cache/page_153～167.md` 解析**天然香料**名单（表 B.2）
- 从 `cache/page_168～225.md` 解析**合成香料**名单（表 B.3）
- 创建 `Flavoring` 节点，包含：
  - `code`：编码（N001, S0001 等）
  - `name_zh`：中文名
  - `name_en`：英文名
  - `flavoring_type`：类型（"natural" 或 "synthetic"）
  - `fema_number`：FEMA 编号（可选）

### 6. 导入不得添加香料的食品名单（表 B.1）

```bash
uv run python load_no_flavoring_list_to_neo4j.py
```

**功能：**
- 从 `cache/page_152.md` 解析"不得添加食品用香料、香精的食品名单"
- 创建 `FoodCategoryGroup`（code: `NO_FLAVORING_ALLOWED`）
- 建立 `FoodCategoryGroup -[:CONTAINS]-> FoodCategory` 关系
- 处理脚注a的例外情况：
  - 13.01（较大婴儿和幼儿配方食品）：允许使用香兰素、乙基香兰素、香荚兰豆浸膏（提取物）
  - 13.02（婴幼儿谷类辅助食品）：允许使用香兰素
  - 建立 `Flavoring -[:PERMITTED_IN]-> FoodCategory` 关系，标记为例外

## 📊 数据模型

### 节点类型

| 节点 | 说明 | 唯一标识 |
|------|------|----------|
| `Chemical` | 食品添加剂 | `id` (CNS/INS) |
| `AdditiveCode` | 添加剂编码（CNS/INS） | `(code_type, code)` |
| `Function` | 功能 | `name` |
| `FoodCategory` | 食品分类 | `code` |
| `FoodCategoryGroup` | 食品分类集合 | `code` |
| `Flavoring` | 食品用香料 | `code` |

### 关系类型

| 关系 | 方向 | 说明 |
|------|------|------|
| `REFERS_TO` | AdditiveCode → Chemical | 编码指向添加剂 |
| `HAS_FUNCTION` | Chemical → Function | 添加剂具有功能 |
| `PERMITTED_IN` | Chemical/Flavoring → FoodCategory | 允许在食品分类中使用 |
| `PERMITTED_IN_GROUP` | Chemical → FoodCategoryGroup | 允许在食品分类组中使用 |
| `CONTAINS` | FoodCategoryGroup → FoodCategory | 组包含食品分类 |
| `HAS_SUBCATEGORY` | FoodCategory → FoodCategory | 食品分类层级关系 |

### FoodCategory 层级关系

食品分类号具有层级结构，例如：
- `01`（第一层）
- `01.02`（第二层）
- `01.02.03`（第三层）

通过 `HAS_SUBCATEGORY` 关系表示：
```
01 -[:HAS_SUBCATEGORY]-> 01.02 -[:HAS_SUBCATEGORY]-> 01.02.03
```

## 🔍 查询示例

### 查询某个食品分类的所有子分类
```cypher
MATCH (parent:FoodCategory {code: '01'})-[:HAS_SUBCATEGORY*]->(child:FoodCategory)
RETURN child
```

### 查询某个食品分类的所有父分类
```cypher
MATCH (child:FoodCategory {code: '01.02.03'})<-[:HAS_SUBCATEGORY*]-(parent:FoodCategory)
RETURN parent
```

### 查询第一层食品分类
```cypher
MATCH (fc:FoodCategory)
WHERE fc.level = 1
RETURN fc
```

### 查询某个添加剂允许使用的食品分类
```cypher
MATCH (c:Chemical {id: '08.002'})-[:PERMITTED_IN]->(fc:FoodCategory)
RETURN fc.code, fc.name, fc.level
```

### 查询不得添加香料的食品分类
```cypher
MATCH (g:FoodCategoryGroup {code: 'NO_FLAVORING_ALLOWED'})-[:CONTAINS]->(fc:FoodCategory)
RETURN fc.code, fc.name
```

### 查询脚注a例外情况（允许使用的香料）
```cypher
MATCH (f:Flavoring)-[r:PERMITTED_IN]->(fc:FoodCategory)
WHERE r.exception_note IS NOT NULL
RETURN f.name_zh, fc.code, fc.name, r.max_usage, r.unit, r.exception_note
```

## 📁 项目文件说明

### 核心脚本

| 文件 | 说明 |
|------|------|
| `load_all_data.py` | **一键导入所有数据（推荐使用）** |
| `load_categories_to_neo4j.py` | 导入食品分类系统（E.1）和例外类别（A.2） |
| `load_cache_to_neo4j.py` | 导入食品添加剂数据（A.1） |
| `load_flavorings_to_neo4j.py` | 导入食品用香料数据（B.2、B.3） |
| `load_no_flavoring_list_to_neo4j.py` | 导入不得添加香料的食品名单（B.1） |
| `clear_neo4j.py` | 清空数据库 |
| `run_neo4j_cypher.py` | 执行 Cypher 脚本 |
| `chat.py` | 基于知识图谱的问答系统 |

### Schema 和配置

| 文件 | 说明 |
|------|------|
| `neo4j_schema.cypher` | Schema 定义（约束、索引、说明） |
| `requirements.txt` | Python 依赖（仅知识图谱相关） |
| `pyproject.toml` | 项目配置 |
| `.env` | 环境变量配置（Neo4j 连接信息等） |

### 文档

| 文件 | 说明 |
|------|------|
| `README.md` | 项目说明和使用指南 |
| `neo4j_load_flow.md` | 数据入库流程说明 |
| `neo4j_schema_design.md` | Schema 设计文档 |

### 数据目录

| 目录 | 说明 |
|------|------|
| `cache/` | PDF 解析后的 Markdown 文件（数据源） |
| `pdfs/` | PDF 源文件 |
| `chroma_graphrag/` | ChromaDB 向量数据库（chat.py 使用） |
| `output/` | PDF 解析输出（可选，可删除） |

## ⚠️ 注意事项

1. **推荐使用自动化脚本**：`load_all_data.py` 会自动按正确顺序执行所有步骤
2. **执行顺序很重要**：如果手动执行，必须先执行 Schema，然后按顺序执行数据导入脚本
3. **FoodCategoryGroup 代码更新**：`TABLE_A2_EXCEPTIONS` 已更新为 `FOOD_ADDITIVE_EXCEPTIONS`
4. **层级关系**：`FoodCategory` 的层级关系通过 `HAS_SUBCATEGORY` 自动建立
5. **level 属性**：所有 `FoodCategory` 节点都会自动设置 `level` 属性
6. **香料数据依赖**：运行 `load_no_flavoring_list_to_neo4j.py` 前，必须先运行 `load_flavorings_to_neo4j.py`

## 🎯 下一步

导入完成后，可以使用 `chat.py` 进行基于知识图谱的问答查询。
