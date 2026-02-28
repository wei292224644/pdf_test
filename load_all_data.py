#!/usr/bin/env python3
"""
自动化数据导入脚本：从清空数据库到完整数据录入
按正确顺序执行所有导入步骤
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def check_neo4j_connection() -> bool:
    """检查 Neo4j 连接"""
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}")
        print(f"   请确认 Neo4j 已启动且 .env 配置正确")
        return False


def run_script(script_name: str, description: str) -> bool:
    """运行一个 Python 脚本"""
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        print(f"❌ 脚本不存在: {script_name}")
        return False
    
    print(f"\n{'='*60}")
    print(f"📋 {description}")
    print(f"{'='*60}")
    
    try:
        # 使用 subprocess 运行脚本，保持输出
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=False,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"❌ 脚本执行失败: {script_name}")
        print(f"   错误码: {e.returncode}")
        return False
    except Exception as e:
        print(f"❌ 执行脚本时出错: {e}")
        return False


def clear_database():
    """清空数据库"""
    print("\n" + "="*60)
    print("🗑️  步骤 1: 清空数据库")
    print("="*60)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("MATCH (n) DETACH DELETE n")
            result.consume()
        driver.close()
        print("✅ 数据库已清空（约束与索引保留）")
        return True
    except Exception as e:
        print(f"❌ 清空数据库失败: {e}")
        driver.close()
        return False


def create_schema():
    """创建 Schema（约束与索引）"""
    print("\n" + "="*60)
    print("📐 步骤 2: 创建 Schema（约束与索引）")
    print("="*60)
    
    root = Path(__file__).resolve().parent
    schema_file = root / "neo4j_schema.cypher"
    
    if not schema_file.exists():
        print(f"❌ Schema 文件不存在: {schema_file}")
        return False
    
    # 导入 run_neo4j_cypher 的函数
    sys.path.insert(0, str(root))
    try:
        from run_neo4j_cypher import split_cypher_statements
        
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        try:
            driver.verify_connectivity()
        except Exception as e:
            print(f"❌ Neo4j 连接失败: {e}")
            return False
        
        text = schema_file.read_text(encoding="utf-8")
        statements = split_cypher_statements(text)
        
        success_count = 0
        error_count = 0
        
        for i, stmt in enumerate(statements):
            try:
                with driver.session() as session:
                    session.run(stmt)
                success_count += 1
            except Exception as e:
                error_count += 1
                print(f"  ⚠️  语句 {i+1} 执行失败: {e}")
        
        driver.close()
        
        if error_count == 0:
            print(f"✅ Schema 创建成功: {success_count} 条语句执行成功")
            return True
        else:
            print(f"⚠️  Schema 创建部分成功: {success_count} 条成功, {error_count} 条失败")
            return True  # 部分失败也继续（可能是 IF NOT EXISTS 的情况）
    except Exception as e:
        print(f"❌ 创建 Schema 失败: {e}")
        return False


def main():
    """主函数：按顺序执行所有导入步骤"""
    print("\n" + "="*60)
    print("🚀 GB 2760 食品添加剂知识图谱 - 自动化数据导入")
    print("="*60)
    
    # 检查连接
    if not check_neo4j_connection():
        sys.exit(1)
    
    steps = [
        ("clear_database", "清空数据库", clear_database),
        ("create_schema", "创建 Schema", create_schema),
        ("load_categories_to_neo4j.py", "导入食品分类系统（表 E.1 和表 A.2）", None),
        ("load_cache_to_neo4j.py", "导入食品添加剂数据（表 A.1）", None),
        ("load_flavorings_to_neo4j.py", "导入食品用香料数据（表 B.2 和 B.3）", None),
        ("load_no_flavoring_list_to_neo4j.py", "导入不得添加香料名单（表 B.1）", None),
        ("load_processing_aids_to_neo4j.py", "导入食品工业用加工助剂数据（表 C.1 和 C.2）", None),
        ("load_enzymes_to_neo4j.py", "导入食品用酶制剂数据（表 C.3）", None),
        ("create_vector_indexes.py", "创建向量索引（embedding，用于语义检索）", None),
    ]
    
    failed_steps = []
    
    for step_name, description, func in steps:
        if func:
            # 直接调用函数
            success = func()
        else:
            # 运行脚本
            success = run_script(step_name, description)
        
        if not success:
            failed_steps.append((step_name, description))
            print(f"\n❌ 步骤失败: {description}")
            response = input("是否继续执行后续步骤？(y/n): ").strip().lower()
            if response != 'y':
                print("\n⚠️  用户取消，停止执行")
                break
    
    # 总结
    print("\n" + "="*60)
    print("📊 导入完成总结")
    print("="*60)
    
    if failed_steps:
        print(f"❌ 失败的步骤 ({len(failed_steps)} 个):")
        for step_name, description in failed_steps:
            print(f"   - {description} ({step_name})")
        print("\n⚠️  部分步骤失败，请检查错误信息并手动修复")
        sys.exit(1)
    else:
        print("✅ 所有步骤执行成功！")
        print("\n📊 已导入的数据：")
        print("   - 食品分类系统（E.1）")
        print("   - 食品添加剂（A.1）")
        print("   - 食品用香料（B.2、B.3）")
        print("   - 不得添加香料的食品名单（B.1）")
        print("   - 食品工业用加工助剂（C.1、C.2）")
        print("   - 食品用酶制剂（C.3）")
        print("   - 向量索引（embedding，用于语义检索）")
        print("\n💡 提示：")
        print("   - 可以使用 chat.py 进行查询测试")
        print("   - 在 Neo4j Browser 中查看数据: MATCH (n) RETURN n LIMIT 100")
        print("="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，停止执行")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
