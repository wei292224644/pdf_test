#!/usr/bin/env python3
"""
将 cache 目录下香料名单（page_153.md 至 page_167.md 天然香料，page_168.md 至 page_225.md 合成香料）
解析并写入 Neo4j Flavoring 节点。
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def parse_flavoring_table_row(line: str) -> tuple[str, str, str, str, str] | None:
    """解析香料表格行：| 序号 | 编码 | 香料中文名称 | 香料英文名称 | FEMA 编号 |"""
    line = line.strip()
    if not line.startswith("|") or line == "|" or "---" in line:
        return None
    parts = [p.strip() for p in line.split("|")[1:-1]]
    if len(parts) < 4:
        return None
    # 序号、编码、中文名、英文名、FEMA编号
    seq = parts[0] if len(parts) > 0 else ""
    code = parts[1] if len(parts) > 1 else ""
    name_zh = parts[2] if len(parts) > 2 else ""
    name_en = parts[3] if len(parts) > 3 else ""
    fema = parts[4] if len(parts) > 4 else ""
    return seq, code, name_zh, name_en, fema


def parse_flavorings_from_content(content: str, flavoring_type: str) -> list[dict]:
    """从 markdown 内容中解析香料列表"""
    flavorings = []
    lines = content.split("\n")
    in_table = False
    
    for line in lines:
        # 检测表格开始
        if "序号" in line and "编码" in line and "|" in line:
            in_table = True
            continue
        if not in_table:
            continue
        # 跳过分隔行
        if "---" in line or (line.strip().startswith("|") and re.match(r"\|[\s\-|]+\|", line)):
            continue
        
        row = parse_flavoring_table_row(line)
        if not row:
            continue
        
        seq, code, name_zh, name_en, fema = row
        if not code or code.strip() in ("—", "-", "–", ""):
            continue
        
        # 清理数据
        code = code.strip()
        name_zh = name_zh.strip()
        name_en = name_en.strip().replace("<br>", " ").replace("\n", " ")  # 处理换行
        fema = fema.strip() if fema and fema.strip() not in ("—", "-", "–") else ""
        
        flavorings.append({
            "code": code,
            "name_zh": name_zh,
            "name_en": name_en,
            "fema_number": fema,
            "flavoring_type": flavoring_type,
        })
    
    return flavorings


def cypher_escape(s: str) -> str:
    """Cypher 字符串内单引号转义"""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "''")


def load_flavoring(driver, flavoring: dict) -> None:
    """将单个香料写入 Neo4j"""
    code = flavoring["code"]
    name_zh = flavoring["name_zh"]
    name_en = flavoring["name_en"]
    fema_number = flavoring.get("fema_number", "")
    flavoring_type = flavoring["flavoring_type"]
    
    with driver.session() as session:
        session.run(
            """
            MERGE (f:Flavoring { code: $code })
            SET f.name_zh = $name_zh,
                f.name_en = $name_en,
                f.flavoring_type = $flavoring_type,
                f.fema_number = $fema_number
            """,
            {
                "code": code,
                "name_zh": name_zh,
                "name_en": name_en,
                "flavoring_type": flavoring_type,
                "fema_number": fema_number,
            },
        )


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"
    
    if not cache_dir.is_dir():
        print("cache 目录不存在。")
        return
    
    # 天然香料：page_153.md 至 page_167.md
    natural_files = [f"page_{i}.md" for i in range(153, 168)]
    # 合成香料：page_168.md 至 page_225.md
    synthetic_files = [f"page_{i}.md" for i in range(168, 226)]
    
    all_flavorings = []
    
    # 解析天然香料
    print("解析天然香料名单...")
    for filename in natural_files:
        filepath = cache_dir / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        flavorings = parse_flavorings_from_content(content, "natural")
        all_flavorings.extend(flavorings)
        print(f"  {filename}: 解析到 {len(flavorings)} 个天然香料")
    
    # 解析合成香料
    print("解析合成香料名单...")
    for filename in synthetic_files:
        filepath = cache_dir / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        flavorings = parse_flavorings_from_content(content, "synthetic")
        all_flavorings.extend(flavorings)
        print(f"  {filename}: 解析到 {len(flavorings)} 个合成香料")
    
    # 按 code 去重
    seen_codes = set()
    unique_flavorings = []
    for f in all_flavorings:
        if f["code"] not in seen_codes:
            seen_codes.add(f["code"])
            unique_flavorings.append(f)
    
    print(f"\n总共解析到 {len(all_flavorings)} 个香料，去重后 {len(unique_flavorings)} 个将写入 Neo4j。")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return
    
    # 写入香料数据
    for i, flavoring in enumerate(unique_flavorings):
        try:
            load_flavoring(driver, flavoring)
            print(f"  [{i+1}/{len(unique_flavorings)}] {flavoring['name_zh']} ({flavoring['code']})")
        except Exception as e:
            print(f"  [{i+1}] {flavoring['code']} 失败: {e}")
    
    driver.close()
    print("\n香料数据写入完成。")
    print("在 Neo4j Browser 中查看: MATCH (f:Flavoring) RETURN f LIMIT 100")


if __name__ == "__main__":
    main()
