#!/usr/bin/env python3
"""
使用 Ollama 的 qwen3-embedding:4b 生成文本向量，供入库 Neo4j 前写入节点 embedding 属性。
需本地已启动 Ollama 并拉取模型: ollama pull qwen3-embedding:4b
"""
import os
import requests
from typing import List

OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b")


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


def get_embeddings_batch(texts: List[str]) -> List[List[float] | None]:
    """
    对多段文本批量调用 Ollama（一次请求），返回与 texts 同序的 embedding 列表。
    某条失败则对应位置为 None。
    """
    texts = [t if (t or "").strip() else "" for t in texts]
    if not texts:
        return []
    try:
        r = requests.post(
            OLLAMA_EMBED_URL,
            json={"model": OLLAMA_EMBED_MODEL, "input": texts},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        embeddings = data.get("embeddings", [])
        return [list(vec) if vec else None for vec in embeddings]
    except Exception as e:
        import sys
        print(f"⚠️ Ollama embedding 批量失败: {e}", file=sys.stderr)
        return [None] * len(texts)


def text_for_embedding(*parts: str) -> str:
    """将若干字段拼成一段用于 embedding 的文本，空段自动忽略。"""
    return " ".join(p for p in parts if p and str(p).strip()).strip()
