#!/usr/bin/env python3
"""
将 cache 目录下加工助剂名单（page_226.md C.1，page_227.md 至 page_232.md C.2）
解析并写入 Neo4j ProcessingAid 节点。
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from embedding_ollama import get_embedding, text_for_embedding

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def parse_footnotes(content: str) -> dict[str, str]:
    """解析文件末尾的脚注说明，返回 {脚注引用: 脚注内容}"""
    footnotes = {}
    lines = content.split("\n")
    
    # 查找脚注部分（通常以 > 开头）
    for line in lines:
        line = line.strip()
        # 匹配格式：> <sup>10)</sup> 包括磷酸（湿法）...
        match = re.match(r'>\s*<sup>(\d+)\)</sup>\s*(.+)', line)
        if match:
            ref = match.group(1) + ")"
            note = match.group(2).strip()
            footnotes[ref] = note
    
    return footnotes


def parse_table_row_c1(line: str) -> tuple[str, str, str] | None:
    """解析 C.1 表格行：| 序号 | 助剂中文名称 | 助剂英文名称 |"""
    line = line.strip()
    if not line.startswith("|") or line == "|" or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < 3:
        return None
    seq = parts[0] if len(parts) > 0 else ""
    name_zh = parts[1] if len(parts) > 1 else ""
    name_en = parts[2] if len(parts) > 2 else ""
    return seq, name_zh, name_en


def parse_table_row_c2(line: str) -> tuple[str, str, str, str, str] | None:
    """解析 C.2 表格行：|序号|助剂中文名称|助剂英文名称|功能|使用范围|"""
    line = line.strip()
    if not line.startswith("|") or line == "|" or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < 5:
        return None
    seq = parts[0] if len(parts) > 0 else ""
    name_zh = parts[1] if len(parts) > 1 else ""
    name_en = parts[2] if len(parts) > 2 else ""
    function = parts[3] if len(parts) > 3 else ""
    usage_scope = parts[4] if len(parts) > 4 else ""
    return seq, name_zh, name_en, function, usage_scope


def extract_footnote_ref(name_zh: str) -> tuple[str, str]:
    """从名称中提取脚注引用，返回 (清理后的名称, 脚注引用)"""
    # 匹配 <sup>10)</sup> 格式
    match = re.search(r'<sup>(\d+)\)</sup>', name_zh)
    if match:
        ref = match.group(1) + ")"
        cleaned_name = re.sub(r'<sup>\d+\)</sup>', '', name_zh).strip()
        return cleaned_name, ref
    return name_zh, ""


def parse_processing_aids_c1(content: str) -> list[dict]:
    """解析 C.1 类型加工助剂（可在各类食品加工过程中使用）"""
    aids = []
    lines = content.split("\n")
    in_table = False
    
    for line in lines:
        # 检测表格开始
        if "表 C.1" in line or ("序号" in line and "助剂中文名称" in line and "助剂英文名称" in line):
            in_table = True
            continue
        if not in_table:
            continue
        # 跳过分隔行
        if "---" in line or (line.strip().startswith("|") and re.match(r"\|[\s\-|]+\|", line)):
            continue
        # 遇到下一个表或章节，停止
        if "表 C.2" in line or "##" in line:
            break
        
        row = parse_table_row_c1(line)
        if not row:
            continue
        
        seq, name_zh, name_en = row
        if not name_zh or not name_en:
            continue
        
        # 清理数据
        seq = seq.strip()
        name_zh = name_zh.strip()
        name_en = name_en.strip()
        
        # 生成 code
        code = f"PA{seq.zfill(3)}"
        
        aids.append({
            "code": code,
            "name_zh": name_zh,
            "name_en": name_en,
            "type": "unlimited",
            "sequence_no": int(seq) if seq.isdigit() else 0,
        })
    
    return aids


def parse_processing_aids_c2(content: str) -> list[dict]:
    """解析 C.2 类型加工助剂（需要规定功能和使用范围）"""
    aids = []
    lines = content.split("\n")
    in_table = False
    
    # 先解析脚注
    footnotes = parse_footnotes(content)
    
    for line in lines:
        # 检测表格开始
        if "表 C.2" in line or ("序号" in line and "助剂中文名称" in line and "功能" in line and "使用范围" in line):
            in_table = True
            continue
        if not in_table:
            continue
        # 跳过分隔行
        if "---" in line or (line.strip().startswith("|") and re.match(r"\|[\s\-|]+\|", line)):
            continue
        # 遇到下一个表或章节，停止
        if "表 C.3" in line or ("##" in line and "C.3" in line):
            break
        
        row = parse_table_row_c2(line)
        if not row:
            continue
        
        seq, name_zh, name_en, function, usage_scope = row
        if not name_zh or not name_en:
            continue
        
        # 清理数据
        seq = seq.strip()
        name_zh = name_zh.strip()
        name_en = name_en.strip()
        function = function.strip()
        usage_scope = usage_scope.strip()
        
        # 提取脚注引用
        cleaned_name, footnote_ref = extract_footnote_ref(name_zh)
        note = footnotes.get(footnote_ref, "")
        
        # 生成 code
        code = f"PA{seq.zfill(3)}"
        
        aids.append({
            "code": code,
            "name_zh": cleaned_name,
            "name_en": name_en,
            "type": "limited",
            "function": function,
            "usage_scope": usage_scope,
            "footnote_ref": footnote_ref if footnote_ref else None,
            "note": note if note else None,
            "sequence_no": int(seq) if seq.isdigit() else 0,
        })
    
    return aids


def load_processing_aid(driver, aid: dict) -> None:
    """将单个加工助剂写入 Neo4j；入库前对名称/功能/范围做 Ollama embedding。"""
    text = text_for_embedding(
        aid["name_zh"],
        aid["name_en"],
        aid.get("function", ""),
        aid.get("usage_scope", ""),
    )
    emb = get_embedding(text) if text else None

    with driver.session() as session:
        params = {
            "code": aid["code"],
            "name_zh": aid["name_zh"],
            "name_en": aid["name_en"],
            "type": aid["type"],
            "sequence_no": aid.get("sequence_no", 0),
        }
        if emb:
            params["embedding"] = emb

        if aid["type"] == "limited":
            params["function"] = aid.get("function", "")
            params["usage_scope"] = aid.get("usage_scope", "")
            params["footnote_ref"] = aid.get("footnote_ref")
            params["note"] = aid.get("note")

            if emb:
                session.run(
                    """
                    MERGE (pa:ProcessingAid { code: $code })
                    SET pa.name_zh = $name_zh,
                        pa.name_en = $name_en,
                        pa.type = $type,
                        pa.function = $function,
                        pa.usage_scope = $usage_scope,
                        pa.footnote_ref = $footnote_ref,
                        pa.note = $note,
                        pa.sequence_no = $sequence_no,
                        pa.embedding = $embedding
                    """,
                    params,
                )
            else:
                session.run(
                    """
                    MERGE (pa:ProcessingAid { code: $code })
                    SET pa.name_zh = $name_zh,
                        pa.name_en = $name_en,
                        pa.type = $type,
                        pa.function = $function,
                        pa.usage_scope = $usage_scope,
                        pa.footnote_ref = $footnote_ref,
                        pa.note = $note,
                        pa.sequence_no = $sequence_no
                    """,
                    params,
                )
        else:
            if emb:
                session.run(
                    """
                    MERGE (pa:ProcessingAid { code: $code })
                    SET pa.name_zh = $name_zh,
                        pa.name_en = $name_en,
                        pa.type = $type,
                        pa.sequence_no = $sequence_no,
                        pa.embedding = $embedding
                    """,
                    params,
                )
            else:
                session.run(
                    """
                    MERGE (pa:ProcessingAid { code: $code })
                    SET pa.name_zh = $name_zh,
                        pa.name_en = $name_en,
                        pa.type = $type,
                        pa.sequence_no = $sequence_no
                    """,
                    params,
                )


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"
    
    if not cache_dir.is_dir():
        print("cache 目录不存在。")
        return
    
    all_aids = []
    
    # 解析 C.1 类型（page_226.md）
    print("解析 C.1 类型加工助剂（可在各类食品加工过程中使用）...")
    c1_file = cache_dir / "page_226.md"
    if c1_file.exists():
        content = c1_file.read_text(encoding="utf-8")
        aids = parse_processing_aids_c1(content)
        all_aids.extend(aids)
        print(f"  page_226.md: 解析到 {len(aids)} 个加工助剂")
    
    # 解析 C.2 类型（page_227.md 至 page_232.md）
    print("解析 C.2 类型加工助剂（需要规定功能和使用范围）...")
    c2_files = [f"page_{i}.md" for i in range(227, 233)]
    for filename in c2_files:
        filepath = cache_dir / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        aids = parse_processing_aids_c2(content)
        all_aids.extend(aids)
        print(f"  {filename}: 解析到 {len(aids)} 个加工助剂")
    
    # 按 code 去重
    seen_codes = set()
    unique_aids = []
    for aid in all_aids:
        if aid["code"] not in seen_codes:
            seen_codes.add(aid["code"])
            unique_aids.append(aid)
    
    print(f"\n总共解析到 {len(all_aids)} 个加工助剂，去重后 {len(unique_aids)} 个将写入 Neo4j。")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return
    
    # 写入数据
    for i, aid in enumerate(unique_aids):
        try:
            load_processing_aid(driver, aid)
            print(f"  [{i+1}/{len(unique_aids)}] {aid['name_zh']} ({aid['code']}, {aid['type']})")
        except Exception as e:
            print(f"  [{i+1}] {aid['code']} 失败: {e}")
    
    driver.close()
    print("\n加工助剂数据写入完成。")
    print("在 Neo4j Browser 中查看: MATCH (pa:ProcessingAid) RETURN pa LIMIT 100")


if __name__ == "__main__":
    main()
