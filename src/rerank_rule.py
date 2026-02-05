from __future__ import annotations

import re
from typing import Dict, List


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", text.lower())


def _score_candidate(query: str, text: str) -> float:
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(text))
    overlap = len(q_tokens & c_tokens)

    score = overlap * 2.0

    q_lower = query.lower().strip()
    t_lower = text.lower()
    if q_lower and q_lower in t_lower:
        score += 3.0

    if re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", query) and re.search(
        r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text
    ):
        score += 2.0

    if re.search(r"\d+%|\d+\s*퍼센트", query) and re.search(r"\d+%|\d+\s*퍼센트", text):
        score += 1.5

    if re.search(r"\d", query) and re.search(r"\d", text):
        score += 0.5

    score -= min(len(text), 5000) * 0.0001
    return score


def rerank_rule(query: str, candidates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    scored = []
    for idx, cand in enumerate(candidates):
        text = str(cand.get("text", ""))
        score = _score_candidate(query, text)
        scored.append((score, idx, cand))

    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    return [cand for _, _, cand in scored]
