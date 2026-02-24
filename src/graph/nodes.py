from __future__ import annotations

import re
from typing import Dict, List

from ..evaluation.eval_harness import ChunkRecord
from ..rag_answer import _extract_org_hint, generate_answer, generate_money_rank_answer
from .state import ChatState, OrgInfo, QueryIntent


_ASSET_DIRECT_RE = re.compile(
    r"(표|테이블|이미지|그림|도표|캡션|첨부|원문\s*(표|이미지)|근거\s*(이미지|표))"
)
_ASSET_CONTEXT_OBJECT_RE = re.compile(r"(사진|화면|스크린샷|캡처|원본|첨부본)")
_ASSET_CONTEXT_ACTION_RE = re.compile(r"(보여|띄워|확인|첨부|제시|출력|찾아)")
_MONEY_OBJECT_RE = re.compile(r"(비용|금액|예산|사업비|보증금|가격)")
_MONEY_STANDALONE_RE = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?:예산|금액|비용|보증금|사업비|총사업비|예정가격|기초금액|입찰금액|계약금액|청구금액|투입비)"
    r"(?:은|는|이|가|을|를|의|에|으로|로|도|만)?(?![가-힣A-Za-z0-9])"
)


def _is_asset_intent(query: str) -> bool:
    q = query or ""
    if _ASSET_DIRECT_RE.search(q):
        return True
    return bool(_ASSET_CONTEXT_OBJECT_RE.search(q) and _ASSET_CONTEXT_ACTION_RE.search(q))


def _is_money_intent(query: str) -> bool:
    q = query or ""
    if _MONEY_STANDALONE_RE.search(q):
        return True
    return bool(re.search(r"얼마", q) and "얼마나" not in q and _MONEY_OBJECT_RE.search(q))


def parse_query(query: str) -> QueryIntent:
    q = query.strip()
    is_frequency_query = bool(re.search(r"얼마나\s*(자주|빈도|횟수|주기)", q))
    query_type = "generic"
    if re.search(r"(사업비|예산|금액|총사업비|예정가격|기초금액)", q) and re.search(
        r"(가장|상위|top|순위|많은|큰|높은)", q, re.IGNORECASE
    ):
        query_type = "money_rank"
    elif _is_asset_intent(q):
        query_type = "asset"
    elif re.search(r"비율|퍼센트|%", q):
        query_type = "percent"
    elif _is_money_intent(q):
        query_type = "money"
    elif re.search(r"마감|일자|언제|날짜", q):
        query_type = "date"
    elif re.search(r"기간|몇\s*개월|며칠|몇\s*회", q) or is_frequency_query:
        query_type = "period"
    elif re.search(r"문의처|연락처|전화", q):
        query_type = "contact"
    keywords = re.findall(r"[0-9A-Za-z가-힣]+", q)
    return QueryIntent(raw_query=q, query_type=query_type, keywords=keywords)


def parse_org(query: str) -> OrgInfo:
    org_hint = _extract_org_hint(query)
    if not org_hint:
        return OrgInfo()
    return OrgInfo(org_name=org_hint, matched=True)


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
    if state.intent.query_type == "money_rank":
        ans = generate_money_rank_answer(state.intent.raw_query, chunk_contexts)
    else:
        ans = generate_answer(state.intent.raw_query, chunk_contexts, answer_model=model)
    state.answer = str(ans.get("answer", "문서에 해당 정보가 없습니다."))
    state.status = str(ans.get("status", "not_found"))
    raw_citations = ans.get("citations", [])
    if isinstance(raw_citations, list):
        state.citations = [int(x) for x in raw_citations if isinstance(x, int) or str(x).isdigit()]
    else:
        state.citations = []
    return state
