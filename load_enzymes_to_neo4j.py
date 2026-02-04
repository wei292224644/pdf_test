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
    """清理文本：移除 <br>、<sup> 标签，规范化空白字符"""
    text = re.sub(r"<br>", " ", text)
    text = re.sub(r"<sup>[^<]*</sup>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_organism_name(text: str) -> tuple[str, str]:
    """
    解析生物体名称，支持多种格式：
    - 中文 （英文）
    - 中文 *英文*
    - 纯英文
    - 复杂格式：瘤胃球菌 CAG55 （Ruminococcus sp. CAG55）
    """
    text = clean_text(text)
    
    # 格式1: 中文（英文）
    match_paren_zh = re.match(r"^(.+?)[（(](.+?)[）)]$", text)
    if match_paren_zh:
        name_zh = match_paren_zh.group(1).strip()
        name_en = match_paren_zh.group(2).strip()
        name_en = re.sub(r"\*+", "", name_en).strip()
        if name_zh and name_en and not re.search(r"[\u4e00-\u9fff]", name_en):
            return (name_zh, name_en)
    
    # 移除斜体标记
    text_no_italic = re.sub(r"\*+", "", text).strip()
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text_no_italic))
    
    if has_chinese:
        # 格式2: 中文  （英文）
        match_paren = re.match(r"^(.+?)\s+[（(](.+?)[）)]$", text_no_italic)
        if match_paren:
            return (match_paren.group(1).strip(), match_paren.group(2).strip())
        
        # 格式3: 中文 英文（无括号）
        match = re.match(r"^([\u4e00-\u9fff\s、，,]+?)\s+([A-Za-z\s,\.\-\d\(\)]+)$", text_no_italic)
        if match:
            return (match.group(1).strip(), match.group(2).strip())
        
        # 只有中文
        return (text_no_italic, "")
    else:
        # 只有英文
        return ("", text_no_italic)


def parse_enzymes_from_content(content: str) -> list[dict]:
    """
    解析酶制剂表格内容
    
    逻辑：
    - 使用 \n 来确定换行
    - 如果前缀为 | | |，那么就可以认定为是上一个酶的内容（续行）
    """
    enzymes = []
    lines = content.split("\n")
    
    in_table = False
    current_enzyme = None
    
    for line in lines:
        # 检测表格开始
        if ("C.3" in line and ("食品用酶制剂" in line or "序号" in line)) or (
            "序号" in line and "酶" in line and "来源" in line
        ):
            in_table = True
            continue
        
        if not in_table:
            continue
        
        # 跳过分隔行（只包含 |、空格、横线的行）
        if line.strip().startswith("|"):
            line_content = re.sub(r"[|\s\-]", "", line.strip())
            if not line_content:
                continue
        
        # 检查是否是表格行
        if not line.strip().startswith("|"):
            continue
        
        # 解析表格行
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 4:
            continue
        
        seq = parts[0].strip()
        enzyme_name = parts[1].strip()
        source = parts[2].strip()
        donor = parts[3].strip()
        
        # 判断是否是续行：前缀为 | | |
        is_continuation = seq == "" and enzyme_name == "" and source != ""
        
        if is_continuation:
            # 续行：属于当前酶
            if current_enzyme and source:
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
                source_organism = (
                    f"{source_zh}|{source_en}"
                    if source_zh and source_en
                    else (source_zh or source_en)
                )
                donor_organism = (
                    f"{donor_zh}|{donor_en}"
                    if (donor_zh or donor_en) and donor_zh and donor_en
                    else (donor_zh or donor_en or None)
                )
                
                # 直接添加，不进行去重（保留所有行，即使有重复）
                current_enzyme["source_pairs"].append(
                    {
                        "source_organism": source_organism,
                        "source_zh": source_zh,
                        "source_en": source_en,
                        "donor_organism": donor_organism,
                        "donor_zh": donor_zh if donor_zh else None,
                        "donor_en": donor_en if donor_en else None,
                    }
                )
        else:
            # 新酶：序号列有数字
            if seq and seq.isdigit():
                # 保存之前的酶
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
                elif re.search(r"[（(].*?[）)].*?[（(].*?[）)]", enzyme_name_clean):
                    # 找到最后一个括号对作为英文名
                    match_en = re.search(
                        r"[（(]([^）(]+(?:[（(][^）)]+[）)])*)[）)]$", enzyme_name_clean
                    )
                    if match_en:
                        # 提取最后一个括号对之前的内容作为中文名
                        last_paren_start = enzyme_name_clean.rfind(match_en.group(0))
                        enzyme_name_zh = enzyme_name_clean[:last_paren_start].strip()
                        # 提取最后一个括号对中的内容作为英文名（去掉内部括号）
                        en_text = match_en.group(1).strip()
                        # 如果英文名内部还有括号，提取最外层的部分
                        if "（" in en_text or "(" in en_text:
                            # 提取第一个括号之前的部分作为英文名
                            en_match = re.match(r"^([^（(]+)", en_text)
                            if en_match:
                                enzyme_name_en = en_match.group(1).strip()
                            else:
                                enzyme_name_en = en_text
                        else:
                            enzyme_name_en = en_text
                    else:
                        # 如果无法解析，使用 parse_organism_name
                        enzyme_name_zh, enzyme_name_en = parse_organism_name(
                            enzyme_name_clean
                        )
                # 处理括号格式：中文名 （英文名）
                elif "（" in enzyme_name_clean or "(" in enzyme_name_clean:
                    # 使用 parse_organism_name 来解析（它支持括号格式）
                    enzyme_name_zh, enzyme_name_en = parse_organism_name(
                        enzyme_name_clean
                    )
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
                        source_organism = (
                            f"{source_zh}|{source_en}"
                            if source_zh and source_en
                            else (source_zh or source_en)
                        )
                        donor_organism = (
                            f"{donor_zh}|{donor_en}"
                            if (donor_zh or donor_en) and donor_zh and donor_en
                            else (donor_zh or donor_en or None)
                        )
                        
                        current_enzyme["source_pairs"].append(
                            {
                                "source_organism": source_organism,
                                "source_zh": source_zh,
                                "source_en": source_en,
                                "donor_organism": donor_organism,
                                "donor_zh": donor_zh if donor_zh else None,
                                "donor_en": donor_en if donor_en else None,
                            }
                        )
    
    # 保存最后一个酶
    if current_enzyme:
        enzymes.append(current_enzyme)
    
    return enzymes


def load_organism(driver, name_zh: str, name_en: str) -> None:
    """创建或更新生物体节点"""
    with driver.session() as session:
        session.run(
            """
            MERGE (o:Organism { name_zh: $name_zh, name_en: $name_en })
            """,
            {"name_zh": name_zh or "", "name_en": name_en or ""},
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
            # 确保 donor_organism 为空字符串而不是 None
            donor_organism_value = donor_organism if donor_organism is not None else ""
            session.run(
                """
                MERGE (es:EnzymeSource {
                    enzyme_code: $enzyme_code,
                    source_organism: $source_organism,
                    donor_organism: $donor_organism
                })
                """,
                {
                    "enzyme_code": enzyme["code"],
                    "source_organism": source_organism,
                    "donor_organism": donor_organism_value,
                },
            )
            
            # 建立 Enzyme -[:HAS_SOURCE]-> EnzymeSource 关系
            session.run(
                """
                MATCH (e:Enzyme { code: $enzyme_code })
                MATCH (es:EnzymeSource {
                    enzyme_code: $enzyme_code,
                    source_organism: $source_organism,
                    donor_organism: $donor_organism
                })
                MERGE (e)-[:HAS_SOURCE]->(es)
                """,
                {
                    "enzyme_code": enzyme["code"],
                    "source_organism": source_organism,
                    "donor_organism": donor_organism_value,
                },
            )
            
            # 建立 EnzymeSource -[:FROM_ORGANISM]-> Organism 关系（来源）
            if source_zh or source_en:
                session.run(
                    """
                    MATCH (es:EnzymeSource {
                        enzyme_code: $enzyme_code,
                        source_organism: $source_organism,
                        donor_organism: $donor_organism
                    })
                    MATCH (o:Organism { name_zh: $source_zh, name_en: $source_en })
                    MERGE (es)-[:FROM_ORGANISM]->(o)
                    """,
                    {
                        "enzyme_code": enzyme["code"],
                        "source_organism": source_organism,
                        "donor_organism": donor_organism_value,
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
                        donor_organism: $donor_organism
                    })
                    MATCH (o:Organism { name_zh: $donor_zh, name_en: $donor_en })
                    MERGE (es)-[:USES_DONOR]->(o)
                    """,
                    {
                        "enzyme_code": enzyme["code"],
                        "source_organism": source_organism,
                        "donor_organism": donor_organism_value,
                        "donor_zh": donor_zh or "",
                        "donor_en": donor_en or "",
                    },
                )


def main():
    """主函数：读取所有酶制剂文件并导入 Neo4j"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    cache_dir = Path("cache")
    enzyme_files = sorted(
        [
            f
            for f in cache_dir.glob("page_*.md")
            if 233 <= int(f.stem.split("_")[1]) <= 242
        ]
    )
    
    print(f"找到 {len(enzyme_files)} 个酶制剂文件")
    
    all_enzymes = {}
    
    for file_path in enzyme_files:
        print(f"处理文件: {file_path.name}")
        content = file_path.read_text(encoding="utf-8")
        enzymes = parse_enzymes_from_content(content)
        
        # 合并相同序号的酶（可能跨文件）
        # 注意：跨页面的相同序号酶应该合并，保留所有source_pairs（即使有重复）
        for enzyme in enzymes:
            code = enzyme["code"]
            if code in all_enzymes:
                # 合并 source_pairs：直接追加，不进行去重（保留所有配对）
                all_enzymes[code]["source_pairs"].extend(enzyme["source_pairs"])
                # 如果酶名称不同，使用更完整的名称（保留两个名称中更完整的）
                if enzyme.get("name_zh") and not all_enzymes[code].get("name_zh"):
                    all_enzymes[code]["name_zh"] = enzyme["name_zh"]
                if enzyme.get("name_en") and not all_enzymes[code].get("name_en"):
                    all_enzymes[code]["name_en"] = enzyme["name_en"]
            else:
                all_enzymes[code] = enzyme
    
    print(f"\n共解析出 {len(all_enzymes)} 个酶制剂")
    
    # 导入 Neo4j
    for enzyme in all_enzymes.values():
        load_enzyme(driver, enzyme)
        print(
            f"导入酶: {enzyme['name_zh']} ({enzyme['name_en']}) - {len(enzyme['source_pairs'])} 个来源-供体配对"
        )
    
    driver.close()
    print("\n导入完成！")
    print(
        "\n可以在 Neo4j Browser 中运行以下查询查看结果："
    )
    print(
        "MATCH (e:Enzyme)-[:HAS_SOURCE]->(es:EnzymeSource)-[:FROM_ORGANISM]->(source:Organism)"
    )
    print("OPTIONAL MATCH (es)-[:USES_DONOR]->(donor:Organism)")
    print("RETURN e.name_zh, source.name_zh, donor.name_zh")
    print("LIMIT 50")


if __name__ == "__main__":
    main()
