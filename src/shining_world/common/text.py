"""文本工具：分句、token 估算（中文按字、英文按词近似）。"""

from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_CJK_RE = re.compile(r"[一-鿿]")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def normalize_ws(text: str) -> str:
    """压缩多余空白并去首尾。"""
    return re.sub(r"[ \t]+", " ", text).strip()


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文字数 + 英文词数×1.3。"""
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    return int(cjk + words * 1.3)


def chunk_text(text: str, max_chars: int = 400, overlap: int = 40) -> list[str]:
    """按句子切块，带少量重叠，用于向量库切片。"""
    text = normalize_ws(text)
    if not text:
        return []
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(buf) + len(sentence) <= max_chars:
            buf += sentence
            continue
        if buf:
            chunks.append(buf)
        buf = sentence[-(max_chars - overlap) :] if len(sentence) > max_chars else sentence
        if len(buf) > max_chars:
            chunks.append(buf[:max_chars])
            buf = buf[max_chars:]
    if buf:
        chunks.append(buf)
    return chunks
