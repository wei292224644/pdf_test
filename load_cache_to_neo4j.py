#!/usr/bin/env python3
"""
将 cache 目录下所有 .md 中的食品添加剂数据解析并写入 Neo4j，
遵循 neo4j_load_examples.cypher 的 Schema 与入库流程。
"""
import os
import re
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv
from neo4j import GraphDatabase

from embedding_ollama import get_embedding, text_for_embedding

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# 「各类食品（表A.2…除外）」的识别模式，捕获完整除外编号
# 支持两种表述：1）1～68  2）1~4、6~9、11~30、32~49、54~61、63~68 等多段
RE_GROUP_RULE = re.compile(
    r"各类食品[，,]?\s*表\s*A\.?2[^|]*?(?:编号为)?\s*([0-9～~\-－–、，\d\s]+?)\s*的食品类别除外",
    re.IGNORECASE,
)
# CNS / INS / 功能（支持 **CNS号**： 和 **CNS号：** 两种格式）
# 匹配模式：*+CNS号*+[：:]*+值 或 CNS号[：:]值（*可能在CNS号前后）
RE_CNS = re.compile(r"\*+CNS号\*+[：:]\s*([^\n*]+)|\*+CNS号[：:]\*+\s*([^\n*]+)|CNS号\*+[：:]\*+\s*([^\n*]+)|CNS号[：:]\s*([^\n]+)")
RE_INS = re.compile(r"\*+INS号\*+[：:]\s*([^\n*]+)|\*+INS号[：:]\*+\s*([^\n*]+)|INS号\*+[：:]\*+\s*([^\n*]+)|INS号[：:]\s*([^\n]+)")
RE_FUNCTION = re.compile(r"\*+功能\*+[：:]\s*([^\n|*]+)|\*+功能[：:]\*+\s*([^\n|*]+)|功能\*+[：:]\*+\s*([^\n|*]+)|功能[：:]\s*([^\n|]+)")


def normalize_exclude_group(s: str) -> str:
    """将 1～68、1~68、1–68 等统一为规范形式（保留 1~62、64~68 等多段）"""
    s = s.strip().replace("～", "~").replace("－", "-").replace("\u2013", "~")  # en-dash
    return re.sub(r"\s+", "", s)


def expand_exclude_group(s: str) -> list[int]:
    """将 1~68 或 1~4、6~9、11~30、32~49、54~61、63~68 等展开为整数数组 [1,2,3,4,6,7,...,68]"""
    s = normalize_exclude_group(s)
    if not s:
        return list(range(1, 69))  # 默认 1~68
    result: list[int] = []
    parts = re.split(r"[、，,]", s)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[~\-]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            result.extend(range(a, b + 1))
        elif part.isdigit():
            result.append(int(part))
    return sorted(set(result))


def parse_table_row(line: str) -> tuple[str, str, str, str] | None:
    """解析表行：| code | name | max_usage | note |，返回 (code, name, max_usage, note) 或 None"""
    line = line.strip()
    if not line.startswith("|") or line == "|" or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < 4:
        return None
    return parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else ""


def is_group_rule_row(code: str, name: str) -> bool:
    """是否为「各类食品（表A.2…除外）」类规则行"""
    if not code or code.strip() in ("—", "-", "–"):
        return "各类食品" in name and "表A.2" in name.replace(" ", "") and "除外" in name
    return False


def extract_exclude_group(name: str) -> str:
    """从食品名称/描述中提取除外编号，如 1~68"""
    m = RE_GROUP_RULE.search(name)
    if m:
        return normalize_exclude_group(m.group(1))
    return "1~68"


def extract_scope_from_name(name: str) -> str:
    """从食品名称中提取范围限定（括号内部分），如「其他油脂或油脂制品（仅限植脂末）」→「仅限植脂末」"""
    if not name:
        return ""
    m = re.search(r"[（(]([^）)]+)[）)]\s*$", name)
    return m.group(1).strip() if m else ""


def infer_unit(max_usage: str, table_header_has_g_kg: bool) -> str:
    """从最大使用量或表头推断单位"""
    max_usage = (max_usage or "").strip()
    if "g/L" in max_usage or "g/l" in max_usage.lower():
        return "g/L"
    if "g/kg" in max_usage or "g/kg" in max_usage.lower():
        return "g/kg"
    return "g/kg" if table_header_has_g_kg else "g/kg"


@dataclass
class Permission:
    type: str  # "group" | "category"
    # group（各类食品除外规则；每条规则单独一条关系，保留 exclude_group 与完整描述）
    max_usage: str = ""
    exclude_group: str = ""  # 规范化的除外编号，如 1~68 或 1~4、6~9、11~30、32~49、54~61、63~68
    group_rule_description: str = ""  # 原始完整描述，如「各类食品，表A.2中编号为1~4、6~9、…的食品类别除外」
    # category
    code: str = ""
    name: str = ""
    unit: str = "g/kg"
    note: str = ""
    scope: str = ""  # 范围限定，如「仅限植脂末」「仅限粉末油脂」，用于同一 code 多条许可区分


@dataclass
class AdditiveBlock:
    name_zh: str = ""
    name_en: str = ""
    cns_list: list[str] = field(default_factory=list)  # 可多个，如 08.014、08.015
    ins_list: list[str] = field(default_factory=list)   # 可多个或 —
    functions: list[str] = field(default_factory=list)  # 可多个，如 稳定剂、凝固剂
    permissions: list[Permission] = field(default_factory=list)


def parse_additive_blocks(content: str) -> list[AdditiveBlock]:
    """从一篇 markdown 内容中解析出多个添加剂块（不校验文件正确性，假定内容有效）"""
    blocks: list[AdditiveBlock] = []
    raw_blocks = re.split(r"\n##\s+", content)
    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n")
        if not lines:
            continue
        # 第一行：中文名（可能含括号别名）；若以 ## 开头则去掉（段首无换行时 split 未拆开）
        name_zh = lines[0].strip().lstrip("#").strip()
        name_en = ""
        cns_list: list[str] = []
        ins_list: list[str] = []
        functions: list[str] = []
        permissions: list[Permission] = []
        table_header_has_g_kg = False
        in_table = False

        i = 1
        while i < len(lines):
            line = lines[i]
            if not in_table:
                # 英文名：通常第二行，无冒号
                if not name_en and line.strip() and "号" not in line and "功能" not in line and not line.strip().startswith("|"):
                    name_en = line.strip()
                    i += 1
                    continue
                cns_m = RE_CNS.search(line)
                if cns_m:
                    # 取第一个非空的捕获组
                    cns_raw = next((g for g in cns_m.groups() if g), "").strip()
                    cns_list = [c.strip() for c in re.split(r"[、,，]", cns_raw) if re.match(r"[\d.]+", c.strip())]
                    i += 1
                    continue
                ins_m = RE_INS.search(line)
                if ins_m:
                    # 取第一个非空的捕获组
                    ins_raw = next((g for g in ins_m.groups() if g), "").strip()
                    if ins_raw not in ("—", "-", "–", ""):
                        ins_list = [c.strip() for c in re.split(r"[、,，]", ins_raw) if c.strip() and c.strip() not in ("—", "-")]
                    i += 1
                    continue
                func_m = RE_FUNCTION.search(line)
                if func_m:
                    # 取第一个非空的捕获组
                    func_raw = next((g for g in func_m.groups() if g), "").strip()
                    functions = [f.strip() for f in re.split(r"[、,，]", func_raw) if f.strip()]
                    i += 1
                    continue
                if "食品分类号" in line and "|" in line:
                    in_table = True
                    table_header_has_g_kg = "g/kg" in line
                    i += 1
                    continue
            else:
                # 表分隔行
                if "---" in line or (line.strip().startswith("|") and re.match(r"\|[\s\-|]+\|", line)):
                    i += 1
                    continue
                row = parse_table_row(line)
                if not row:
                    i += 1
                    continue
                code, name, max_usage, note = row
                if is_group_rule_row(code, name):
                    permissions.append(
                        Permission(
                            type="group",
                            max_usage=max_usage or "按生产需要适量使用",
                            exclude_group=extract_exclude_group(name),
                            group_rule_description=name.strip(),  # 保留原始表述，两种方式都体现
                        )
                    )
                else:
                    unit = infer_unit(max_usage, table_header_has_g_kg)
                    if "g/L" in (max_usage or ""):
                        unit = "g/L"
                    scope = extract_scope_from_name(name)
                    permissions.append(
                        Permission(
                            type="category",
                            code=code,
                            name=name,
                            max_usage=max_usage or "",
                            unit=unit,
                            note=note or "",
                            scope=scope,
                        )
                    )
            i += 1

        if name_zh and (cns_list or ins_list):
            blocks.append(
                AdditiveBlock(
                    name_zh=name_zh,
                    name_en=name_en,
                    cns_list=cns_list,
                    ins_list=ins_list,
                    functions=functions,
                    permissions=permissions,
                )
            )
    return blocks


def chemical_id(block: AdditiveBlock) -> str:
    """Chemical 唯一 id：优先第一个 CNS，否则第一个 INS，否则用 name_zh 的 slug"""
    if block.cns_list:
        return block.cns_list[0].strip()
    if block.ins_list:
        return block.ins_list[0].strip()
    return re.sub(r"[^\w\u4e00-\u9fff\-.]", "_", block.name_zh)[:64]


def is_valid_chemical_id(cid: str) -> bool:
    """是否为有效的添加剂 id（CNS 如 01.104 或 INS 如 160e），用于过滤噪音块"""
    if not cid or len(cid) < 2:
        return False
    if cid in ("。", "08", "02", "04", "05", "10", "12", "14", "17", "18", "19", "20"):
        return False
    if re.match(r"^\d{2}\.\d{2,4}$", cid):
        return True
    if re.match(r"^[\w.()\-]+$", cid) and len(cid) >= 3:
        return True
    return False


def is_noise_block(block: AdditiveBlock) -> bool:
    """是否为噪音块（章节标题等），应跳过"""
    cid = chemical_id(block)
    if not is_valid_chemical_id(cid):
        return True
    noise_titles = ("食品添加剂的使用规定", "表 A", "附录A", "目次", "前言", "范围", "术语")
    if any(t in (block.name_zh or "") for t in noise_titles):
        return True
    return False


def cypher_escape(s: str) -> str:
    """Cypher 字符串内单引号转义：' -> ''；并避免反斜杠问题"""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "''")


def calculate_level(code: str) -> int:
    """计算食品分类号的层级深度，如 '01' -> 1, '01.02' -> 2, '01.02.03' -> 3"""
    if not code:
        return 0
    return code.count(".") + 1


def run_parameterized(driver, stmt: str, params: dict) -> None:
    with driver.session() as session:
        session.run(stmt, params)


def load_block(
    driver,
    block: AdditiveBlock,
    group_code: str = "FOOD_ADDITIVE_EXCEPTIONS",
    function_embedding_cache: dict | None = None,
) -> None:
    """将单个添加剂块写入 Neo4j（与 neo4j_load_examples.cypher 流程一致）；入库前对 Chemical/Function 做 Ollama embedding。"""
    cid = chemical_id(block)
    name_zh = cypher_escape(block.name_zh)
    name_en = cypher_escape(block.name_en)
    if function_embedding_cache is None:
        function_embedding_cache = {}

    # 入库前 embedding（Ollama qwen3-embedding:4b）
    chemical_text = text_for_embedding(block.name_zh, block.name_en, *block.functions)
    chem_emb = get_embedding(chemical_text)
    params_chemical = {"id": cid, "name_zh": block.name_zh, "name_en": block.name_en}
    if chem_emb:
        params_chemical["embedding"] = chem_emb

    # 1. MERGE Chemical
    if chem_emb:
        run_parameterized(
            driver,
            "MERGE (c:Chemical { id: $id }) SET c.name_zh = $name_zh, c.name_en = $name_en, c.embedding = $embedding",
            params_chemical,
        )
    else:
        run_parameterized(
            driver,
            "MERGE (c:Chemical { id: $id }) SET c.name_zh = $name_zh, c.name_en = $name_en",
            {"id": cid, "name_zh": block.name_zh, "name_en": block.name_en},
        )

    # 2. AdditiveCode REFERS_TO Chemical（每个 CNS / INS）
    for code in block.cns_list:
        code = code.strip()
        if not code:
            continue
        run_parameterized(
            driver,
            """
            MERGE (ac:AdditiveCode { code_type: 'CNS', code: $code })
            WITH ac
            MATCH (c:Chemical { id: $cid })
            MERGE (ac)-[:REFERS_TO]->(c)
            """,
            {"code": code, "cid": cid},
        )
    for code in block.ins_list:
        code = code.strip()
        if not code:
            continue
        run_parameterized(
            driver,
            """
            MERGE (ac:AdditiveCode { code_type: 'INS', code: $code })
            WITH ac
            MATCH (c:Chemical { id: $cid })
            MERGE (ac)-[:REFERS_TO]->(c)
            """,
            {"code": code, "cid": cid},
        )

    # 3. HAS_FUNCTION（每个功能）；Function 节点入库前 embedding
    for func in block.functions:
        func = func.strip()
        if not func:
            continue
        if func not in function_embedding_cache:
            function_embedding_cache[func] = get_embedding(func)
        func_emb = function_embedding_cache[func]
        if func_emb:
            run_parameterized(
                driver,
                """
                MERGE (f:Function { name: $name })
                SET f.embedding = $embedding
                WITH f
                MATCH (c:Chemical { id: $cid })
                MERGE (c)-[:HAS_FUNCTION]->(f)
                """,
                {"name": func, "embedding": func_emb, "cid": cid},
            )
        else:
            run_parameterized(
                driver,
                """
                MERGE (f:Function { name: $name })
                WITH f
                MATCH (c:Chemical { id: $cid })
                MERGE (c)-[:HAS_FUNCTION]->(f)
                """,
                {"name": func, "cid": cid},
            )

    # 4a. PERMITTED_IN_GROUP（同一添加剂可有多种「各类食品除外」规则，用 CREATE 各建一条；exclude_group 存为整数数组）
    for p in block.permissions:
        if p.type != "group":
            continue
        exclude_list = expand_exclude_group(p.exclude_group or "1~68")
        run_parameterized(
            driver,
            """
            MATCH (c:Chemical { id: $cid })
            MATCH (g:FoodCategoryGroup { code: $group_code })
            CREATE (c)-[r:PERMITTED_IN_GROUP]->(g)
            SET r.max_usage = $max_usage, r.exclude_group = $exclude_group, r.group_rule_description = $group_rule_description
            """,
            {
                "cid": cid,
                "group_code": group_code,
                "max_usage": p.max_usage or "按生产需要适量使用",
                "exclude_group": exclude_list,  # 整数数组，如 [1,2,3,4,6,7,...,68]
                "group_rule_description": p.group_rule_description or "",
            },
        )

    # 4b. PERMITTED_IN（具体食品分类；同一 code 多条不同限定/用量用 CREATE 各建一条，带 scope）
    # FoodCategory 按 code 唯一：若已存在则不覆盖 name；关系上保存当前行的完整名称 category_name 与范围 scope
    for p in block.permissions:
        if p.type != "category":
            continue
        level = calculate_level(p.code)
        run_parameterized(
            driver,
            """
            MERGE (fc:FoodCategory { code: $code })
            ON CREATE SET fc.name = $name, fc.level = $level
            ON MATCH SET fc.level = $level
            WITH fc
            MATCH (c:Chemical { id: $cid })
            CREATE (c)-[r:PERMITTED_IN]->(fc)
            SET r.max_usage = $max_usage, r.unit = $unit, r.note = $note,
                r.scope = $scope, r.category_name = $category_name
            """,
            {
                "cid": cid,
                "code": p.code,
                "name": p.name,
                "level": level,
                "max_usage": p.max_usage,
                "unit": p.unit,
                "note": p.note or "",
                "scope": p.scope or "",
                "category_name": p.name or "",  # 当前行完整食品名称，便于后续按条处理
            },
        )


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"

    if not cache_dir.is_dir():
        print("cache 目录不存在。")
        return
    
    # 排除食品分类与例外类别文件（表 E.1: 245～254，表 A.2: 149、150），只解析添加剂
    exclude_names = {f"page_{p}.md" for p in [149, 150, *range(245, 255)]}
    md_files = sorted(f for f in cache_dir.glob("*.md") if f.name not in exclude_names)
    print(f"读取 cache 下 {len(md_files)} 个 .md 文件（已排除表 E.1 / 表 A.2 的 category 文件）。")
    
    all_blocks: list[AdditiveBlock] = []
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        blocks = parse_additive_blocks(text)
        all_blocks.extend(blocks)

    # 按 chemical_id 去重，保留首次出现
    seen_ids: set[str] = set()
    unique_blocks: list[AdditiveBlock] = []
    for b in all_blocks:
        cid = chemical_id(b)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        unique_blocks.append(b)

    # cache 内容均为表 A.1 添加剂，不做噪音过滤，全部写入
    print(f"解析到 {len(all_blocks)} 个添加剂块，去重后 {len(unique_blocks)} 个将写入 Neo4j。")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return

    # 预置 FoodCategoryGroup（若尚未存在）
    with driver.session() as session:
        session.run(
            "MERGE (g:FoodCategoryGroup { code: 'FOOD_ADDITIVE_EXCEPTIONS' }) SET g.name = '各类食品（表A.2中编号为1~68的食品类别除外）'"
        )

    function_embedding_cache: dict[str, list | None] = {}
    for i, block in enumerate(unique_blocks):
        try:
            load_block(driver, block, function_embedding_cache=function_embedding_cache)
            print(f"  [{i+1}/{len(unique_blocks)}] {block.name_zh} (id={chemical_id(block)})")
        except Exception as e:
            print(f"  [{i+1}] {block.name_zh} 失败: {e}")

    driver.close()
    print("写入完成。")
    print("在 Neo4j Browser 中查看全部添加剂: MATCH (c:Chemical) RETURN c  （若只看到少量节点，请取消或调大 LIMIT）")


if __name__ == "__main__":
    main()
