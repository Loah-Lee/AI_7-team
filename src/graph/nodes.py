from __future__ import annotations

import re
from typing import Dict, List

from ..evaluation.eval_harness import ChunkRecord
from ..rag_answer import generate_answer
from .state import ChatState, OrgInfo, QueryIntent


def parse_query(query: str) -> QueryIntent:
    q = query.strip()
    query_type = "generic"
    if re.search(r"(표|테이블|이미지|그림|도표|캡션|첨부|원문\s*(표|이미지)|근거\s*(이미지|표))", q):
        query_type = "asset"
    elif re.search(r"비율|퍼센트|%", q):
        query_type = "percent"
    elif re.search(r"예산|금액|비용|얼마", q):
        query_type = "money"
    elif re.search(r"마감|일자|언제|날짜", q):
        query_type = "date"
    elif re.search(r"기간|몇\s*개월|며칠", q):
        query_type = "period"
    elif re.search(r"문의처|연락처|전화", q):
        query_type = "contact"
    keywords = re.findall(r"[0-9A-Za-z가-힣]+", q)
    return QueryIntent(raw_query=q, query_type=query_type, keywords=keywords)


def parse_org(query: str) -> OrgInfo:
    tok = query.strip().split()
    if not tok:
        return OrgInfo()
    cand = tok[0]
    matched = bool(re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|원)$", cand) or cand.startswith("한국"))
    return OrgInfo(org_name=cand if matched else "", matched=matched)


def _to_chunk_records(contexts: List[Dict[str, object]]) -> List[ChunkRecord]:
    out: List[ChunkRecord] = []
    for item in contexts:
        source_path = str(item.get("source_path", ""))
        try:
            chunk_index = int(item.get("chunk_index", -1))
        except Exception:
            chunk_index = -1
        out.append(
            ChunkRecord(
                source_path=source_path,
                chunk_index=chunk_index,
                chunk_id=str(item.get("chunk_id", "")),
                text=str(item.get("text", "")),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
            )
        )
    return out


def generate_answer_node(
    state: ChatState,
    contexts: List[Dict[str, object]],
    model: str = "gpt-5-nano",
) -> ChatState:
    state.contexts = contexts
    chunk_contexts = _to_chunk_records(contexts)
    ans = generate_answer(state.intent.raw_query, chunk_contexts, answer_model=model)
    state.answer = str(ans.get("answer", "문서에 해당 정보가 없습니다."))
    state.status = str(ans.get("status", "not_found"))
    raw_citations = ans.get("citations", [])
    if isinstance(raw_citations, list):
        state.citations = [int(x) for x in raw_citations if isinstance(x, int) or str(x).isdigit()]
    else:
        state.citations = []
    return state
