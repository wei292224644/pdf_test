#!/usr/bin/env python3
"""
Demo2: 使用 langextract 分析 GB2760-2024 食品添加剂使用标准文档
提取关键词、重要信息和结构化数据
"""

import argparse
import os
import json
from pathlib import Path
import sys
import textwrap

import dotenv
import langextract as lx
from langextract.providers.openai import OpenAILanguageModel

dotenv.load_dotenv(override=True)

# Qwen API 配置
DEFAULT_MODEL = "qwen3-max-preview"
# DEFAULT_MODEL = "qwen-plus-2025-12-01"
DEFAULT_API_URL = os.environ.get(
    "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_API_KEY = os.environ.get("QWEN_API_KEY", "sk-03f3eb5bc4cf446bafa1c76e762f65ad")
OUTPUT_DIR = "test_output"

# 目标文件路径
TARGET_MD_FILE = "output/GB2760-2024/vlm/GB2760-2024.md"


def ensure_output_directory() -> Path:
    """Create output directory if it doesn't exist."""
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(exist_ok=True)
    return output_path


def validate_and_clean_extractions(
    result: lx.data.AnnotatedDocument,
) -> lx.data.AnnotatedDocument:
    """
    验证和清理提取结果，确保所有 extraction_text 都是有效类型

    Args:
        result: 原始提取结果

    Returns:
        清理后的提取结果
    """
    if not result or not result.extractions:
        return result

    cleaned_extractions = []
    for ext in result.extractions:
        # 确保 extraction_text 是字符串、整数或浮点数
        if ext.extraction_text is None:
            continue

        # 检查类型
        if not isinstance(ext.extraction_text, (str, int, float)):
            # 尝试转换为字符串
            try:
                # 如果是列表或其他可迭代对象，取第一个元素或连接
                if hasattr(ext.extraction_text, "__iter__") and not isinstance(
                    ext.extraction_text, str
                ):
                    ext.extraction_text = " ".join(str(x) for x in ext.extraction_text)
                else:
                    ext.extraction_text = str(ext.extraction_text)
            except Exception as e:
                print(f"  警告: 无法转换提取项 '{ext.extraction_class}': {e}")
                continue

        # 确保字符串不为空
        if isinstance(ext.extraction_text, str) and not ext.extraction_text.strip():
            continue

        cleaned_extractions.append(ext)

    # 更新结果
    result.extractions = cleaned_extractions
    return result


def print_header(title: str, width: int = 80) -> None:
    """Print a formatted header."""
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_section(title: str, width: int = 60) -> None:
    """Print a formatted section."""
    print(f"\n▶ {title}")
    print("-" * width)


def read_markdown_file(file_path: str) -> str:
    """读取 Markdown 文件内容"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"错误: 文件不存在: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"错误: 读取文件失败: {e}")
        sys.exit(1)


def extract_keywords_from_gb2760(
    text: str, model: OpenAILanguageModel
) -> lx.data.AnnotatedDocument | None:
    """从 GB2760 文档中提取关键词"""
    print_section("提取关键词和重要术语")

    prompt = textwrap.dedent(
        """\
        从食品安全国家标准文档中提取以下信息：
        1. 食品添加剂名称（包括中文名、英文名）
        2. 标准编号和版本信息
        3. 重要术语和定义
        4. 章节标题和结构
        5. 关键数据（最大使用量、残留量等）
        
        要求：
        - 使用文档中的确切文本
        - 按出现顺序提取
        - 为每个提取项添加相关属性（如类型、章节等）
        """
    )

    examples = [
        lx.data.ExampleData(
            text="本标准规定了食品添加剂的使用原则、允许使用的食品添加剂品种、使用范围及最大使用量或残留量。",
            extractions=[
                lx.data.Extraction(
                    extraction_class="标准范围",
                    extraction_text="食品添加剂的使用原则、允许使用的食品添加剂品种、使用范围及最大使用量或残留量",
                ),
            ],
        ),
        lx.data.ExampleData(
            text="本标准代替GB2760—2014《食品安全国家标准 食品添加剂使用标准》。",
            extractions=[
                lx.data.Extraction(
                    extraction_class="标准编号",
                    extraction_text="GB2760—2014",
                ),
                lx.data.Extraction(
                    extraction_class="标准名称",
                    extraction_text="食品安全国家标准 食品添加剂使用标准",
                ),
            ],
        ),
    ]

    # 限制文本长度以避免超出 token 限制
    max_text_length = 5000  # 保留空间给 prompt 和 examples
    if len(text) > max_text_length:
        text_preview = text[:max_text_length] + "\n\n[文档已截断，仅分析前部分内容]"
    else:
        text_preview = text

    print(f"  文档长度: {len(text)} 字符")
    print(f"  分析长度: {len(text_preview)} 字符")
    print("  正在提取...")

    try:
        # 使用更保守的配置
        result = lx.extract(
            text_or_documents=text_preview,
            prompt_description=prompt,
            examples=examples,
            model=model,
            show_progress=True,
            fence_output=True,
            use_schema_constraints=False,
            max_char_buffer=1000,  # 限制缓冲区大小
        )

        # 验证和清理结果
        if result:
            result = validate_and_clean_extractions(result)
            print(f"\n  ✓ 提取完成")
            print(
                f"  提取项数量: {len(result.extractions) if result.extractions else 0}"
            )
        else:
            print(f"\n  ✓ 提取完成（无结果）")

        return result

    except ValueError as e:
        if "Extraction text must be a string" in str(e):
            print(f"  ✗ 提取失败: 数据格式错误")
            print(f"  提示: 模型返回的数据格式不正确")
            print(f"  建议: 尝试简化 prompt 或 examples")
        else:
            print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None
    except Exception as e:
        print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def extract_food_additives(
    text: str, model: OpenAILanguageModel
) -> lx.data.AnnotatedDocument | None:
    """提取食品添加剂相关信息"""
    print_section("提取食品添加剂使用规定")

    prompt = textwrap.dedent(
        """\
        从文档中提取食品添加剂的使用规定，包括：
        1. 食品添加剂名称（中文名、英文名）
        2. 使用范围（适用的食品类别）
        3. 最大使用量或残留量
        4. 功能类别（如防腐剂、着色剂等）
        5. INS号、CNS号等编码
        
        要求：
        - 提取表格中的具体数据
        - 保持数据的准确性
        - 为每个添加剂添加属性信息
        """
    )

    examples = [
        lx.data.ExampleData(
            text="表 A.1 食品添加剂的允许使用品种、使用范围以及最大使用量或残留量",
            extractions=[
                lx.data.Extraction(
                    extraction_class="表格标题",
                    extraction_text="表 A.1 食品添加剂的允许使用品种、使用范围以及最大使用量或残留量",
                    attributes={"表格编号": "A.1"},
                ),
            ],
        ),
    ]

    # 查找包含表格的部分（通常在文档后半部分）
    # 这里简化处理，分析整个文档
    max_text_length = 5000
    if len(text) > max_text_length:
        # 尝试找到表格部分
        table_marker = "表 A."
        table_index = text.find(table_marker)
        if table_index > 0:
            # 从表格开始分析
            text_preview = text[table_index : table_index + max_text_length]
            print(f"  找到表格部分，从位置 {table_index} 开始分析")
        else:
            text_preview = text[:max_text_length] + "\n\n[文档已截断]"
    else:
        text_preview = text

    print(f"  分析文本长度: {len(text_preview)} 字符")
    print("  正在提取食品添加剂信息...")

    try:
        # 使用更保守的配置，避免数据格式错误
        result = lx.extract(
            text_or_documents=text_preview,
            prompt_description=prompt,
            examples=examples,
            model=model,
            show_progress=True,
            fence_output=True,
            use_schema_constraints=False,
            # 添加额外的配置以避免格式错误
            max_char_buffer=1000,  # 限制缓冲区大小
        )

        # 验证和清理结果
        if result:
            result = validate_and_clean_extractions(result)
            print(f"\n  ✓ 提取完成")
            print(
                f"  提取项数量: {len(result.extractions) if result.extractions else 0}"
            )
        else:
            print(f"\n  ✓ 提取完成（无结果）")

        return result

    except ValueError as e:
        if "Extraction text must be a string" in str(e):
            print(f"  ✗ 提取失败: 数据格式错误")
            print(f"  提示: 模型返回的数据格式不正确")
            print(f"  建议: 尝试简化 prompt 或 examples")
        else:
            print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None
    except Exception as e:
        print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def extract_document_structure(
    text: str, model: OpenAILanguageModel
) -> lx.data.AnnotatedDocument | None:
    """提取文档结构（章节、附录等）"""
    print_section("提取文档结构")

    prompt = textwrap.dedent(
        """\
        提取文档中食品添加剂的允许使用品种、使用范围1)以及最大使用量或残留量：
        1. 食品添加剂名称（中文名、英文名）
        2. 使用范围（适用的食品类别）
        3. 最大使用量或残留量
        4. 功能类别（如防腐剂、着色剂等）+
        5. INS号、CNS号等编码
        
        要求：
        - 提取文档中的具体数据
        - 保持数据的准确性
        
        使用范围的结构是table结构，需要从<td>结构中提取完整的食品分类号、食品名称、最大使用量、备注信息。
        每个食品添加剂至少能提取到1条使用范围信息。
        整块内容都会包在<td></td>结构中，需要从<td></td>结构中提取完整的数据。
        """
    )

    examples = [
        lx.data.ExampleData(
            text="""#$\mathbf{L}(+)$ -酒石酸， $dl$ -酒石酸
#$\mathbf{L}(+)$ -tartaric acid, $dl$ -tartaric acid

CNS号 01.111，01.313

INS号 334，一

功能 酸度调节剂  

<table><tr><td>食品分类号</td><td>食品名称</td><td>最大使用量</td><td>备注</td></tr><tr><td>04.02.02.03</td><td>腌渍的蔬菜</td><td>3.0g/kg</td><td>以酒石酸计</td></tr><tr><td>05.02</td><td>糖果</td><td>30g/kg</td><td>以酒石酸计</td></tr><tr><td>06.03.02.05</td><td>油炸面制品</td><td>10.0g/kg</td><td>以酒石酸计</td></tr><tr><td>06.05.02.01</td><td>粉丝、粉条</td><td>2.0g/kg</td><td>以酒石酸计</td></tr><tr><td>06.11</td><td>面糊(如用于鱼和禽肉的拖面糊)、裹粉、煎炸粉</td><td>10.0g/kg</td><td>以酒石酸计</td></tr><tr><td>12.10.01</td><td>固体复合调味料</td><td>10.0g/kg</td><td>以酒石酸计</td></tr><tr><td>14.02.03</td><td>果蔬汁(浆)类饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.03.02</td><td>植物蛋白饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.03.03</td><td>复合蛋白饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.04</td><td>碳酸饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.05</td><td>茶、咖啡、植物(类)饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.07</td><td>特殊用途饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>14.08</td><td>风味饮料</td><td>5.0g/kg</td><td>以酒石酸计,以即饮状态计,相应的固体饮料按稀释倍数增加使用量</td></tr><tr><td>15.03.01</td><td>葡萄酒</td><td>4.0g/L</td><td>以酒石酸计</td></tr></table>""",
            extractions=[
                lx.data.Extraction(
                    extraction_class="食品添加剂中文名称",
                    extraction_text="$\mathbf{L}(+)$ -酒石酸， $dl$ -酒石酸",
                ),
                lx.data.Extraction(
                    extraction_class="食品添加剂英文名称",
                    extraction_text="$\mathbf{L}(+)$ -tartaric acid, $dl$ -tartaric acid",
                ),
                lx.data.Extraction(
                    extraction_class="CNS号",
                    extraction_text="CNS号 01.111，01.313",
                ),
                lx.data.Extraction(
                    extraction_class="INS号",
                    extraction_text="INS号 334，一",
                ),
                lx.data.Extraction(
                    extraction_class="功能", extraction_text="酸度调节剂"
                ),
                lx.data.Extraction(
                    extraction_class="食品分类号",
                    extraction_text="04.02.02.03",
                    attributes={"key": "04.02.02.03"},
                ),
                lx.data.Extraction(
                    extraction_class="食品名称",
                    extraction_text="腌渍的蔬菜",
                    attributes={"key": "04.02.02.03"},
                ),
                lx.data.Extraction(
                    extraction_class="最大使用量",
                    extraction_text="3.0g/kg",
                    attributes={"key": "04.02.02.03"},
                ),
                lx.data.Extraction(
                    extraction_class="备注",
                    extraction_text="以酒石酸计",
                    attributes={"key": "04.02.02.03"},
                ),
                lx.data.Extraction(
                    extraction_class="食品分类号",
                    extraction_text="05.02",
                    attributes={"key": "05.02"},
                ),
                lx.data.Extraction(
                    extraction_class="食品名称",
                    extraction_text="糖果",
                    attributes={"key": "05.02"},
                ),
                lx.data.Extraction(
                    extraction_class="最大使用量",
                    extraction_text="30g/kg",
                    attributes={"key": "05.02"},
                ),
                lx.data.Extraction(
                    extraction_class="备注",
                    extraction_text="以酒石酸计",
                    attributes={"key": "05.02"},
                ),
            ],
        )
    ]

    # 分析文档的前部分以获取结构
    text_preview = text[:10000]  # 文档结构通常在前面

    print(f"  分析文档结构（前 {len(text_preview)} 字符）")
    print("  正在提取...")

    try:
        # 使用更保守的配置
        result = lx.extract(
            text_or_documents=text_preview,
            prompt_description=prompt,
            examples=examples,
            model=model,
            fence_output=True,
            use_schema_constraints=False,
            extraction_passes=3,
            temperature=0.3,
        )

        # 验证和清理结果
        if result:
            result = validate_and_clean_extractions(result)
            print(f"\n  ✓ 提取完成")
            print(
                f"  提取项数量: {len(result.extractions) if result.extractions else 0}"
            )
        else:
            print(f"\n  ✓ 提取完成（无结果）")

        return result

    except ValueError as e:
        if "Extraction text must be a string" in str(e):
            print(f"  ✗ 提取失败: 数据格式错误")
            print(f"  提示: 模型返回的数据格式不正确")
            print(f"  建议: 尝试简化 prompt 或 examples")
        else:
            print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None
    except Exception as e:
        print(f"  ✗ 提取失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def print_extraction_summary(extractions: list[lx.data.Extraction]) -> None:
    """打印提取结果摘要"""
    if not extractions:
        print("  未找到提取项")
        return

    # 按类型分组
    by_class = {}
    for ext in extractions:
        cls = ext.extraction_class
        if cls not in by_class:
            by_class[cls] = []
        by_class[cls].append(ext)

    print(f"\n  提取结果统计:")
    print(f"  总提取项: {len(extractions)}")
    print(f"  类型数量: {len(by_class)}")
    print(f"\n  按类型分布:")
    for cls, items in sorted(by_class.items()):
        print(f"    • {cls}: {len(items)} 项")
        # 显示前3个示例
        for item in items[:3]:
            text_preview = item.extraction_text[:60]
            if len(item.extraction_text) > 60:
                text_preview += "..."
            print(f"      - {text_preview}")


def save_results(
    results: dict[str, lx.data.AnnotatedDocument | None],
    output_dir: Path,
    base_name: str = "gb2760_analysis",
) -> None:
    """保存所有提取结果"""
    print_header("保存结果")

    saved_files = []

    for name, result in results.items():
        if result is None:
            print(f"  ✗ 跳过 {name}（无结果）")
            continue

        # 保存 JSONL
        jsonl_file = f"{base_name}_{name}.jsonl"
        jsonl_path = output_dir / jsonl_file

        try:
            lx.io.save_annotated_documents(
                [result], output_name=jsonl_file, output_dir=str(output_dir)
            )
            print(f"  ✓ 已保存 {jsonl_path}")

            # 生成 HTML 可视化
            html_file = f"{base_name}_{name}.html"
            html_path = output_dir / html_file

            try:
                html_content = lx.visualize(str(jsonl_path))
                with open(html_path, "w", encoding="utf-8") as f:
                    if hasattr(html_content, "data"):
                        f.write(html_content.data)
                    else:
                        f.write(str(html_content))
                print(f"  ✓ 已生成 {html_path}")
                saved_files.append((jsonl_path, html_path))
            except Exception as e:
                print(f"  ✗ 生成 HTML 失败 {html_path}: {e}")

        except Exception as e:
            print(f"  ✗ 保存失败 {jsonl_file}: {e}")

    return saved_files


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="分析 GB2760-2024 食品添加剂使用标准文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 使用默认配置
    python demo2.py

    # 指定 API Key
    python demo2.py --api-key "your-api-key"

    # 指定不同的 MD 文件
    python demo2.py --file "path/to/file.md"

输出:
    结果保存在 test_output/ 目录
    - JSONL 文件：提取的结构化数据
    - HTML 文件：交互式可视化
        """,
    )

    parser.add_argument(
        "--file",
        default=TARGET_MD_FILE,
        help=f"要分析的 Markdown 文件路径（默认: {TARGET_MD_FILE}）",
    )

    parser.add_argument(
        "--skip",
        nargs="+",
        choices=["keywords", "additives", "structure"],
        help="跳过特定的提取任务",
    )

    args = parser.parse_args()
    skip_tasks = set(args.skip or [])

    # 初始化模型
    model = OpenAILanguageModel(
        model_id=DEFAULT_MODEL,
        base_url=DEFAULT_API_URL,
        api_key=DEFAULT_API_KEY,
    )

    print_header("GB2760-2024 文档分析")
    print("\n配置:")
    print(f"  文件: {args.file}")
    print(f"  输出目录: {OUTPUT_DIR}/")

    # 读取文件
    print("\n读取文件...")
    text = read_markdown_file(args.file)
    print(f"✓ 文件读取成功 ({len(text)} 字符)")

    output_dir = ensure_output_directory()
    print(f"✓ 输出目录就绪: {output_dir}/")

    # 执行提取任务
    print_header("执行提取任务")
    results = {}

    try:
        result = extract_document_structure(text, model)
        results["structure"] = result

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("保存已完成的结果...")
    except Exception as e:
        print(f"\n\n✗ 执行错误: {e}")
        import traceback

        traceback.print_exc()
        print("\n保存已完成的结果...")

    # 打印摘要
    print_header("提取结果摘要")
    for name, result in results.items():
        if result is not None:
            print(f"\n{name.upper()}:")
            print_extraction_summary(result.extractions)

    # 保存结果
    if results:
        base_name = Path(args.file).stem
        save_results(results, output_dir, base_name)

    # 总结
    print_header("分析完成")

    successful = sum(1 for r in results.values() if r is not None)
    print(f"\n✓ 成功完成 {successful}/{len(results)} 个提取任务")

    if results:
        print(f"\n输出文件在 {output_dir}/:")
        for name, result in results.items():
            if result is not None:
                base_name = Path(args.file).stem
                print(f"  • {base_name}_{name}.jsonl - 提取数据")
                print(f"  • {base_name}_{name}.html  - 可视化")

        print("\n查看结果:")
        if results.get("keywords"):
            base_name = Path(args.file).stem
            print(f"  open {output_dir}/{base_name}_keywords.html")
        print("\n或本地服务器:")
        print(f"  python -m http.server 8000 --directory {output_dir}")
        print("  然后访问 http://localhost:8000")


if __name__ == "__main__":
    main()
