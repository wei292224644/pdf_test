"""
基于 neo4j_schema.cypher 动态 Schema 解析的对话式查询工具。

功能：
1. 启动时读取 `neo4j_schema.cypher`，把约束、索引和注释当作“真实 Schema”提供给 LLM。
2. 用户用自然语言提问（偏技术/查询导向），LLM 根据 Schema 生成只读 Cypher。
3. 脚本执行生成的 Cypher，将结果以表格形式罗列出来，并同时展示原始 Cypher。

与 chat.py 的区别：
- 不做复杂的业务解释，不使用向量检索，只专注于 “问题 → Cypher → 结果列表” 这一闭环。
- 不依赖手写的 Schema 字符串，而是直接使用当前项目中的 `neo4j_schema.cypher` 文件。
"""

import os
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from deepagents.backends import LocalShellBackend
from dotenv import load_dotenv


# LangChain / DeepAgents 相关（仅支持 Agent 模式，要求相关依赖已安装）
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

load_dotenv()

BASE_DIR = Path(__file__).parent
SCHEMA_FILE = BASE_DIR / "neo4j_schema.cypher"
LOG_DIR = BASE_DIR / "logs"
AGENT_LOG_FILE = LOG_DIR / "agent.log"

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Qwen API 配置
QWEN_API_URL = os.getenv(
    "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("LLM_MODEL", "qwen-turbo")


def load_schema_text() -> str:
    """读取 neo4j_schema.cypher 文件内容，如果失败则返回空字符串。"""
    try:
        return SCHEMA_FILE.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 无法读取 schema 文件 {SCHEMA_FILE}: {e}", file=sys.stderr)
        return ""


def extract_cypher_from_text(text: str) -> Optional[str]:
    """从模型输出中提取一条 Cypher，只接受只读查询。"""
    if not text:
        return None
    text = text.strip()

    # 若使用 ```cypher ... ``` 包裹，先剥掉外层
    if "```" in text:
        parts = text.split("```")
        best_block = None
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.lower().startswith("cypher"):
                p = p[6:].strip()
            lower = p.lower()
            # 既接受 MATCH 也接受仅有 CALL 的查询块
            if "match" in lower or "call" in lower:
                best_block = p
                break
        if best_block:
            text = best_block

    # 只允许 READ 查询（MATCH/OPTIONAL MATCH/CALL 等），拒绝 CREATE/SET/DELETE 等
    upper = text.upper()
    if any(
        k in upper
        for k in (
            " CREATE ",
            " MERGE ",
            " DELETE ",
            " SET ",
            " REMOVE ",
            " DROP ",
            " DETACH ",
        )
    ):
        return None

    if "MATCH" in upper or "CALL" in upper:
        return text.strip()
    return None


def generate_cypher(schema_text: str, user_query: str) -> Optional[str]:
    """
    兼容旧接口：保留函数签名，但当前流程使用 LangChain Agent，
    不直接通过本函数生成 Cypher。返回 None。
    """
    return None


# ===================== 基于向量 + Cypher 的底层工具 =====================


def build_deep_agent(schema_text: str):
    """
    使用 DeepAgents + skills/gb2760 构建一个深度 Agent：
    - 通过 Agent Skills 机制加载 `skills/gb2760/SKILL.md`；
    - 由 DeepAgents 负责规划 / 工具选择 / 自我反思；
    - 本文件只负责提供系统提示词和调用入口。
    """
    llm = ChatOpenAI(
        model=QWEN_MODEL,
        openai_api_key=QWEN_API_KEY,
        openai_api_base=QWEN_API_URL,
        temperature=0.1,
    )

    base_dir = os.path.dirname(os.path.abspath(__file__))
    system_prompt = f"""你是一个专门针对食品安全的专家助手。

回答要求：
1. 执行本 Skill 的脚本时，必须使用**相对于项目根的路径**（例如 python script/vector_search_food_category.py 或 python skills/gb2760-standard-query/scripts/vector_search_food_category.py），不要使用 /skills/ 开头的绝对路径。
2. 回答用中文，结构清晰，可以使用编号列表列出结论或添加剂。
3. 如果用户问题不属于任何 Skill 工具的适用范围，要明确说明当前能力不适用，并给出合理的解释。
"""
    # Backend 工厂：框架会传入 ToolRuntime，但 FilesystemBackend/LocalShellBackend 的 root_dir 必须是 str/Path，不能传 rt
    backend = lambda rt: LocalShellBackend(
        root_dir=base_dir,
        virtual_mode=True,
        inherit_env=True,
    )
    agent = create_deep_agent(
        model=llm,
        # system_prompt=system_prompt,
        skills=["./skills/"],
        backend=backend,
        debug=True,
    )
    return agent


def print_records(records: List[Dict[str, Any]]) -> None:
    """以简单表格形式打印查询结果。"""
    if not records:
        print("（无记录）")
        return

    # 汇总所有键，保证每行列一致
    keys: List[str] = []
    for r in records:
        for k in r.keys():
            if k not in keys:
                keys.append(k)

    # 打印表头
    print(" | ".join(keys))
    print("-" * (len(" | ".join(keys)) + 2))

    # 打印每一行
    for r in records:
        row = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, (dict, list)):
                row.append(json.dumps(v, ensure_ascii=False))
            else:
                row.append("" if v is None else str(v))
        print(" | ".join(row))


def _message_to_log_lines(msg: Any) -> tuple[str, list[str]]:
    """把单条消息转为 (角色/类型标签, 内容行列表)，便于写入日志。"""
    lines: list[str] = []
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type") or "message"
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False, indent=2)
        lines.append(str(content)[:50000])  # 单条过长则截断
        return role, lines
    # LangChain 消息对象
    name = type(msg).__name__
    if "Human" in name or (hasattr(msg, "type") and getattr(msg, "type", "") == "human"):
        role = "USER"
        content = getattr(msg, "content", "")
        lines.append(str(content)[:50000])
        return role, lines
    if "AI" in name or (hasattr(msg, "type") and getattr(msg, "type", "") == "ai"):
        role = "AI"
        content = getattr(msg, "content", "") or ""
        if content:
            lines.append(str(content)[:50000])
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                lines.append(f"  [tool_call] name={tc.get('name')} args={json.dumps(tc.get('args', {}), ensure_ascii=False)[:2000]}")
            else:
                lines.append(f"  [tool_call] {tc}")
        return role, lines
    if "Tool" in name or (hasattr(msg, "type") and getattr(msg, "type", "") == "tool"):
        tool_name = getattr(msg, "name", "tool") or "tool"
        role = f"TOOL({tool_name})"
        content = getattr(msg, "content", "")
        lines.append(str(content)[:10000])  # 工具结果可能很长
        return role, lines
    role = name
    content = getattr(msg, "content", str(msg))
    lines.append(str(content)[:50000])
    return role, lines


def _write_agent_log(query: str, result: dict | None, error: str | None, final_answer: Any) -> None:
    """将本次 Agent 执行过程写入 logs/agent.log。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(AGENT_LOG_FILE, "a", encoding="utf-8") as f:
        ts = datetime.now().isoformat()
        f.write("\n")
        f.write("=" * 80 + "\n")
        f.write(f"[{ts}] 问题: {query}\n")
        f.write("=" * 80 + "\n")
        if error:
            f.write(f"[ERROR] {error}\n")
        if result and "messages" in result:
            msgs = result.get("messages") or []
            for i, msg in enumerate(msgs):
                role, content_lines = _message_to_log_lines(msg)
                f.write(f"\n--- [{i+1}] {role} ---\n")
                for line in content_lines:
                    f.write(line + "\n")
        f.write("\n--- 最终回答 ---\n")
        f.write(str(final_answer) + "\n")
        f.write("=" * 80 + "\n\n")


def run_single_query(schema_text: str, query_text: str) -> None:
    """
    单次交互：使用 DeepAgents Agent 自动分析问题、调用 skills/gb2760 中声明的工具，并用中文回答。
    执行过程会追加写入 logs/agent.log，便于分析。
    """
    print(f"❓ 问题: {query_text}\n")

    result = None
    output = None
    err_msg = None
    try:
        agent = build_deep_agent(schema_text)

        # DeepAgents 返回的是一个 LangGraph 编译后的图，直接 invoke 即可
        result = agent.invoke({"messages": [{"role": "user", "content": query_text}]})
    except Exception as e:
        err_msg = str(e)
        print(f"❌ Agent 执行失败: {e}", file=sys.stderr)
        _write_agent_log(query_text, result=None, error=err_msg, final_answer=None)
        return

    try:
        if isinstance(result, dict) and "messages" in result:
            msgs = result["messages"]
            if isinstance(msgs, list) and msgs:
                last = msgs[-1]
                if hasattr(last, "content"):
                    output = last.content
    except Exception:
        pass
    if output is None:
        output = result

    _write_agent_log(query_text, result=result, error=None, final_answer=output)
    print("📊 回答：")
    print(output)


def chat_loop(schema_text: str) -> None:
    """简单对话循环：用户反复提问，生成并执行 Cypher。"""
    while True:
        try:
            user_input = input("❓ 请输入查询问题（输入 quit/exit 退出）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见！")
            break

        run_single_query(schema_text, user_input)
        print("\n" + "=" * 80 + "\n")


def main() -> None:
    schema_text = load_schema_text()
    if not schema_text:
        print(
            "⚠️ 未能加载 neo4j_schema.cypher，仍可提问，但生成的 Cypher 可能不可靠。",
            file=sys.stderr,
        )

    # 若通过命令行参数传入问题，则只回答这一问；否则进入交互模式
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        run_single_query(schema_text, question)
    else:
        chat_loop(schema_text)


if __name__ == "__main__":
    main()
