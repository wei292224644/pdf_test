#!/usr/bin/env python3
"""
将 cache 目录下酶制剂名单（page_233.md 至 page_242.md）
解析并写入 Neo4j Enzyme、EnzymeSource 和 Organism 节点。

设计说明：
- 一个酶可以有多个来源-供体配对
- 每个配对用 EnzymeSource 节点表示
- Enzyme -[:HAS_SOURCE]-> EnzymeSource -[:FROM_ORGANISM]-> Organism（来源）
- EnzymeSource -[:USES_DONOR]-> Organism（供体，可选）
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


def clean_text(text: str) -> str:
    """清理文本，移除 HTML 标签和多余空格"""
    text = re.sub(r'<br>', ' ', text)
    text = re.sub(r'<sup>[^<]*</sup>', '', text)  # 移除上标
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_organism_name(text: str) -> tuple[str, str]:
    """解析生物体名称，提取中文名和英文名
    支持多种格式：
    - "枯草芽孢杆菌 （Bacillus subtilis）" -> ("枯草芽孢杆菌", "Bacillus subtilis")
    - "黑曲霉 *Aspergillus niger*" -> ("黑曲霉", "Aspergillus niger")
    - "*Aspergillus fijiensis*" -> ("", "Aspergillus fijiensis")
    - "大麦、山芋、大豆、小麦和麦芽（barley, taro, soya, wheat and malted barley）" -> ("大麦、山芋、大豆、小麦和麦芽", "barley, taro, soya, wheat and malted barley")
    - "瘤胃球菌 CAG55 （Ruminococcus sp. CAG55）" -> ("瘤胃球菌 CAG55", "Ruminococcus sp. CAG55")
    """
    text = clean_text(text)
    
    # 处理中文括号格式：中文名 （英文名）
    match_paren_zh = re.match(r'^(.+?)[（(](.+?)[）)]$', text)
    if match_paren_zh:
        name_zh = match_paren_zh.group(1).strip()
        name_en = match_paren_zh.group(2).strip()
        # 移除可能的斜体标记
        name_en = re.sub(r'\*+', '', name_en).strip()
        # 检查英文名是否包含中文，如果不包含则认为是有效的英文名
        if name_zh and name_en and not re.search(r'[\u4e00-\u9fff]', name_en):
            return (name_zh, name_en)
    
    # 处理斜体格式：中文名 *英文名* 或 *英文名*
    # 先移除所有斜体标记，然后分离中英文
    text_no_italic = re.sub(r'\*+', '', text).strip()
    
    # 检查是否包含中文
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text_no_italic))
    
    if has_chinese:
        # 有中文，尝试分离
        # 匹配：中文部分 + 空格 + 英文部分（英文部分可能包含括号）
        # 先尝试匹配括号格式
        match_paren = re.match(r'^(.+?)\s+[（(](.+?)[）)]$', text_no_italic)
        if match_paren:
            name_zh = match_paren.group(1).strip()
            name_en = match_paren.group(2).strip()
            return (name_zh, name_en)
        
        # 匹配：中文部分 + 空格 + 英文部分
        match = re.match(r'^([\u4e00-\u9fff\s、，,]+?)\s+([A-Za-z\s,\.\-\d\(\)]+)$', text_no_italic)
        if match:
            name_zh = match.group(1).strip()
            name_en = match.group(2).strip()
            return (name_zh, name_en)
        # 如果无法分离，整个作为中文名
        return (text_no_italic, "")
    else:
        # 没有中文，整个作为英文名
        return ("", text_no_italic)


def parse_enzymes_from_content(content: str) -> list[dict]:
    """从 markdown 内容中解析酶制剂列表"""
    enzymes = []
    lines = content.split("\n")
    in_table = False
    current_enzyme = None
    
    for line in lines:
        # 检测表格开始：支持 "C.3"、"表 C.3"、"C.3（续）" 等格式
        if ("C.3" in line and ("食品用酶制剂" in line or "序号" in line)) or \
           ("序号" in line and "酶" in line and "来源" in line):
            in_table = True
            continue
        if not in_table:
            continue
        # 跳过分隔行（只匹配真正的分隔行，如 |------|-----|------|）
        # 分隔行的特征是：只包含 |、空格、横线，不包含其他字符
        if line.strip().startswith("|"):
            # 检查是否是分隔行：移除所有 |、空格、横线后应该为空
            line_content = re.sub(r'[|\s\-]', '', line.strip())
            if not line_content or line_content == "":
                continue
        
        # 解析表格行
        if line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 4:
                continue
            
            seq = parts[0].strip()
            enzyme_name = parts[1].strip()
            source = parts[2].strip()
            donor = parts[3].strip()
            
            # 处理序号列：如果序号列有数字，说明是新酶
            if seq and seq.isdigit():
                # 新酶，保存之前的酶
                if current_enzyme:
                    enzymes.append(current_enzyme)
                
                # 解析酶名称（格式：中文名 （英文名）或 中文名<br>英文名）
                # 特殊格式：蛋白酶（包括乳凝块酶）（Protease（including milk clotting enzymes））
                enzyme_name_zh = ""
                enzyme_name_en = ""
                
                # 先清理文本
                enzyme_name_clean = clean_text(enzyme_name)
                
                # 处理 <br> 格式
                if "<br>" in enzyme_name:
                    parts_name = enzyme_name.split("<br>")
                    enzyme_name_zh = clean_text(parts_name[0])
                    if len(parts_name) > 1:
                        enzyme_name_en = clean_text(parts_name[1])
                # 处理嵌套括号格式：中文名（中文说明）（英文名（英文说明））
                # 例如：蛋白酶（包括乳凝块酶）（Protease（including milk clotting enzymes））
                elif re.search(r'[（(].*?[）)].*?[（(].*?[）)]', enzyme_name_clean):
                    # 找到最后一个括号对作为英文名
                    # 从右往左找最后一个完整的括号对
                    # 匹配格式：...（英文名（英文说明））
                    match_en = re.search(r'[（(]([^）(]+(?:[（(][^）)]+[）)])*)[）)]$', enzyme_name_clean)
                    if match_en:
                        # 提取最后一个括号对之前的内容作为中文名
                        last_paren_start = enzyme_name_clean.rfind(match_en.group(0))
                        enzyme_name_zh = enzyme_name_clean[:last_paren_start].strip()
                        # 提取最后一个括号对中的内容作为英文名（去掉内部括号）
                        en_text = match_en.group(1).strip()
                        # 如果英文名内部还有括号，提取最外层的部分
                        if '（' in en_text or '(' in en_text:
                            # 提取第一个括号之前的部分作为英文名
                            en_match = re.match(r'^([^（(]+)', en_text)
                            if en_match:
                                enzyme_name_en = en_match.group(1).strip()
                            else:
                                enzyme_name_en = en_text
                        else:
                            enzyme_name_en = en_text
                    else:
                        # 如果无法解析，使用 parse_organism_name
                        enzyme_name_zh, enzyme_name_en = parse_organism_name(enzyme_name_clean)
                # 处理括号格式：中文名 （英文名）
                elif "（" in enzyme_name_clean or "(" in enzyme_name_clean:
                    # 使用 parse_organism_name 来解析（它支持括号格式）
                    enzyme_name_zh, enzyme_name_en = parse_organism_name(enzyme_name_clean)
                else:
                    # 没有英文名，整个作为中文名
                    enzyme_name_zh = enzyme_name_clean
                
                current_enzyme = {
                    "code": f"ENZ{seq.zfill(3)}",
                    "name_zh": enzyme_name_zh,
                    "name_en": enzyme_name_en,
                    "sequence_no": int(seq),
                    "source_pairs": [],  # 来源-供体配对列表
                }
                
                # 如果这一行也有来源信息（序号行可能同时包含第一个来源）
                if source:
                    # 解析来源生物体名称
                    source_zh, source_en = parse_organism_name(source)
                    if source_zh or source_en:
                        # 解析供体生物体名称（如果有）
                        donor_zh = ""
                        donor_en = ""
                        if donor and donor not in ("—", "-", "–", ""):
                            donor_zh, donor_en = parse_organism_name(donor)
                        
                        # 创建来源-供体配对
                        source_organism = f"{source_zh}|{source_en}" if source_zh and source_en else (source_zh or source_en)
                        donor_organism = f"{donor_zh}|{donor_en}" if (donor_zh or donor_en) and donor_zh and donor_en else (donor_zh or donor_en or None)
                        
                        current_enzyme["source_pairs"].append({
                            "source_organism": source_organism,
                            "source_zh": source_zh,
                            "source_en": source_en,
                            "donor_organism": donor_organism,
                            "donor_zh": donor_zh if donor_zh else None,
                            "donor_en": donor_en if donor_en else None,
                        })
                # 跳过后续处理，因为序号行已经处理完毕
                continue
            
            # 处理续行：序号为空但来源有内容，属于当前酶
            # 注意：序号为空的行，酶名列也为空，但来源列有内容，这些都属于上一个有序号的酶
            if not seq and source and current_enzyme:
                # 解析来源生物体名称
                source_zh, source_en = parse_organism_name(source)
                if not source_zh and not source_en:
                    continue  # 跳过无效的来源
                
                # 解析供体生物体名称（如果有）
                donor_zh = ""
                donor_en = ""
                if donor and donor not in ("—", "-", "–", ""):
                    donor_zh, donor_en = parse_organism_name(donor)
                
                # 创建来源-供体配对
                # 使用 source_zh + source_en 作为 source_organism 标识
                source_organism = f"{source_zh}|{source_en}" if source_zh and source_en else (source_zh or source_en)
                donor_organism = f"{donor_zh}|{donor_en}" if (donor_zh or donor_en) and donor_zh and donor_en else (donor_zh or donor_en or None)
                
                # 检查是否已存在相同的来源-供体配对
                pair_exists = False
                for pair in current_enzyme["source_pairs"]:
                    if (pair["source_organism"] == source_organism and 
                        pair["donor_organism"] == donor_organism):
                        pair_exists = True
                        break
                
                if not pair_exists:
                    current_enzyme["source_pairs"].append({
                        "source_organism": source_organism,
                        "source_zh": source_zh,
                        "source_en": source_en,
                        "donor_organism": donor_organism,
                        "donor_zh": donor_zh if donor_zh else None,
                        "donor_en": donor_en if donor_en else None,
                    })
    
    # 保存最后一个酶
    if current_enzyme:
        enzymes.append(current_enzyme)
    
    return enzymes


def load_organism(driver, name_zh: str, name_en: str) -> None:
    """创建或获取生物体节点"""
    with driver.session() as session:
        session.run(
            """
            MERGE (o:Organism { name_zh: $name_zh, name_en: $name_en })
            """,
            {
                "name_zh": name_zh,
                "name_en": name_en,
            },
        )


def load_enzyme(driver, enzyme: dict) -> None:
    """将酶制剂及其来源-供体配对写入 Neo4j"""
    with driver.session() as session:
        # 创建或更新酶节点
        session.run(
            """
            MERGE (e:Enzyme { code: $code })
            SET e.name_zh = $name_zh,
                e.name_en = $name_en,
                e.sequence_no = $sequence_no
            """,
            {
                "code": enzyme["code"],
                "name_zh": enzyme["name_zh"],
                "name_en": enzyme["name_en"],
                "sequence_no": enzyme.get("sequence_no", 0),
            },
        )
        
        # 处理每个来源-供体配对
        for pair in enzyme["source_pairs"]:
            source_zh = pair["source_zh"]
            source_en = pair["source_en"]
            source_organism = pair["source_organism"]
            donor_zh = pair.get("donor_zh")
            donor_en = pair.get("donor_en")
            donor_organism = pair.get("donor_organism")
            
            # 创建或获取来源生物体节点
            if source_zh or source_en:
                load_organism(driver, source_zh or "", source_en or "")
            
            # 创建 EnzymeSource 节点
            session.run(
                """
                MERGE (es:EnzymeSource {
                    enzyme_code: $enzyme_code,
                    source_organism: $source_organism,
                    donor_organism: COALESCE($donor_organism, '')
                })
                SET es.donor_organism = $donor_organism
                """,
                {
                    "enzyme_code": enzyme["code"],
                    "source_organism": source_organism,
                    "donor_organism": donor_organism,
                },
            )
            
            # 建立 Enzyme -[:HAS_SOURCE]-> EnzymeSource 关系
            session.run(
                """
                MATCH (e:Enzyme { code: $enzyme_code })
                MATCH (es:EnzymeSource {
                    enzyme_code: $enzyme_code,
                    source_organism: $source_organism,
                    donor_organism: COALESCE($donor_organism, '')
                })
                MERGE (e)-[:HAS_SOURCE]->(es)
                """,
                {
                    "enzyme_code": enzyme["code"],
                    "source_organism": source_organism,
                    "donor_organism": donor_organism,
                },
            )
            
            # 建立 EnzymeSource -[:FROM_ORGANISM]-> Organism 关系（来源）
            if source_zh or source_en:
                session.run(
                    """
                    MATCH (es:EnzymeSource {
                        enzyme_code: $enzyme_code,
                        source_organism: $source_organism,
                        donor_organism: COALESCE($donor_organism, '')
                    })
                    MATCH (o:Organism { name_zh: $source_zh, name_en: $source_en })
                    MERGE (es)-[:FROM_ORGANISM]->(o)
                    """,
                    {
                        "enzyme_code": enzyme["code"],
                        "source_organism": source_organism,
                        "donor_organism": donor_organism,
                        "source_zh": source_zh or "",
                        "source_en": source_en or "",
                    },
                )
            
            # 建立 EnzymeSource -[:USES_DONOR]-> Organism 关系（供体，如果有）
            if donor_zh or donor_en:
                load_organism(driver, donor_zh or "", donor_en or "")
                session.run(
                    """
                    MATCH (es:EnzymeSource {
                        enzyme_code: $enzyme_code,
                        source_organism: $source_organism,
                        donor_organism: COALESCE($donor_organism, '')
                    })
                    MATCH (o:Organism { name_zh: $donor_zh, name_en: $donor_en })
                    MERGE (es)-[:USES_DONOR]->(o)
                    """,
                    {
                        "enzyme_code": enzyme["code"],
                        "source_organism": source_organism,
                        "donor_organism": donor_organism,
                        "donor_zh": donor_zh or "",
                        "donor_en": donor_en or "",
                    },
                )


def main():
    root = Path(__file__).resolve().parent
    cache_dir = root / "cache"
    
    if not cache_dir.is_dir():
        print("cache 目录不存在。")
        return
    
    all_enzymes = []
    
    # 解析酶制剂（page_233.md 至 page_242.md）
    print("解析酶制剂名单...")
    enzyme_files = [f"page_{i}.md" for i in range(233, 243)]
    for filename in enzyme_files:
        filepath = cache_dir / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        enzymes = parse_enzymes_from_content(content)
        all_enzymes.extend(enzymes)
        print(f"  {filename}: 解析到 {len(enzymes)} 个酶制剂")
    
    # 按 code 合并（同一个酶可能出现在多个文件中）
    enzyme_dict = {}
    for enzyme in all_enzymes:
        code = enzyme["code"]
        if code in enzyme_dict:
            # 合并来源-供体配对
            existing_pairs = {
                (p["source_organism"], p["donor_organism"])
                for p in enzyme_dict[code]["source_pairs"]
            }
            for p in enzyme["source_pairs"]:
                pair_key = (p["source_organism"], p["donor_organism"])
                if pair_key not in existing_pairs:
                    enzyme_dict[code]["source_pairs"].append(p)
        else:
            enzyme_dict[code] = enzyme
    
    unique_enzymes = list(enzyme_dict.values())
    
    print(f"\n总共解析到 {len(all_enzymes)} 个酶制剂记录，合并后 {len(unique_enzymes)} 个酶将写入 Neo4j。")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return
    
    # 写入数据
    for i, enzyme in enumerate(unique_enzymes):
        try:
            load_enzyme(driver, enzyme)
            print(f"  [{i+1}/{len(unique_enzymes)}] {enzyme['name_zh']} ({enzyme['code']}, {len(enzyme['source_pairs'])} 个来源-供体配对)")
        except Exception as e:
            print(f"  [{i+1}] {enzyme['code']} 失败: {e}")
            import traceback
            traceback.print_exc()
    
    driver.close()
    print("\n酶制剂数据写入完成。")
    print("在 Neo4j Browser 中查看: MATCH (e:Enzyme)-[:HAS_SOURCE]->(es:EnzymeSource)-[:FROM_ORGANISM]->(o:Organism) RETURN e, es, o LIMIT 50")


if __name__ == "__main__":
    main()
