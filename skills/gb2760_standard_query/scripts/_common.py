import os
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

import requests
from typing import List

load_dotenv()

OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

print(OLLAMA_EMBED_URL, OLLAMA_EMBED_MODEL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

def get_driver() -> Any:
    """获取 Neo4j driver。调用方负责关闭。"""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_embedding(text: str) -> List[float] | None:
    """
    对单段文本调用 Ollama 生成 embedding 向量。
    返回 float 列表，失败返回 None。
    """
    if not (text or "").strip():
        return None
    try:
        r = requests.post(
            OLLAMA_EMBED_URL,
            json={"model": OLLAMA_EMBED_MODEL, "input": text.strip()},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        embeddings = data.get("embeddings")
        if embeddings and len(embeddings) > 0:
            return list(embeddings[0])
        return None
    except Exception as e:
        import sys

        print(f"⚠️ Ollama embedding 失败: {e}", file=sys.stderr)
        return None


__all__ = ["get_driver", "get_embedding"]
