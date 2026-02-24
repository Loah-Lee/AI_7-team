from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .evaluation.eval_harness import (
    ChunkRecord,
    DenseRetriever,
    HybridRetriever,
    QueryRecord,
    TfidfRetriever,
    evaluate_query,
    load_joined_metadata,
    load_queries,
)
from .evaluation.rerank_openai import rerank_openai
from .evaluation.rerank_rule import rerank_rule
from .retrievers.dense_openai import DenseEmbedder, DenseIndex
from .retrievers.chroma_store import search_chroma
from .retrievers.rich_tfidf_search import (
    ChunkRecord as LexicalChunkRecord,
    _build_tfidf,
    load_chunks_rich,
    tfidf_scores,
)


_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_FRACTION_OF_100_RE = re.compile(r"(?:100|백)\s*분의\s*(\d+(?:\.\d+)?)")
_MONEY_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:원|만원|천원|억원)\b")
_MONEY_LOOSE_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")
_BUDGET_KEYWORD_RE = re.compile(r"(사업예산|사업비|총사업비|예정가격|기초금액|금액|예산)")
_MONEY_OBJECT_RE = re.compile(r"(비용|금액|예산|사업비|보증금|가격)")
_MONEY_STANDALONE_RE = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?:예산|금액|비용|보증금|사업비|총사업비|예정가격|기초금액|입찰금액|계약금액|청구금액|투입비)"
    r"(?:은|는|이|가|을|를|의|에|으로|로|도|만)?(?![가-힣A-Za-z0-9])"
)
_DATE_RE = re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}\s*월\s*\d{1,2}\s*일\b")
# 접수일자 표기에서 자주 등장하는 YYMMDD(예: 240131) 형식
_DATE_COMPACT_RE = re.compile(r"\b\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b")
_PERIOD_RE = re.compile(r"\b\d+\s*(?:개월|개월간|일|일간|년)\b")
_CONTACT_RE = re.compile(r"(?:\d{2,3}-\d{3,4}-\d{4}|@|담당자|문의처|연락처|전화)")
_MONEY_VALUE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(원|만원|천원|억원)")
_ALNUM_CODE_RE = re.compile(r"\b[A-Za-z가-힣0-9]{1,10}-[A-Za-z0-9가-힣]{1,10}(?:-[A-Za-z0-9가-힣]{1,10})?\b")
_ORG_SUFFIX_RE = re.compile(
    r"(공사|공단|재단|재단법인|사단법인|법인|대학교|대학|병원|의료원|정보원|진흥원|연구원|협회|위원회|조직위원회|사무국|센터|서비스|은행|공항|학교)$"
)
_ORG_STOPWORDS = {
    "무엇",
    "어떤",
    "얼마",
    "얼마나",
    "언제",
    "왜",
    "어떻게",
    "질문",
    "답변",
    "문서",
    "요약",
    "설명",
}
_PLACEHOLDER_PREFIXES = (
    "요약 생성을 위해 관련 문맥을 확보했습니다",
    "정확한 값 추출에는 실패했습니다",
)
_INTERNAL_ANSWER_TERM_RE = re.compile(
    r"(청크|컨텍스트|프롬프트|리트리버|retriever|context|prompt|chunk)",
    flags=re.IGNORECASE,
)
_GUIDANCE_CUE_RE = re.compile(r"(필요하시면|원하시면|추가로|더 자세히|도움이 필요하시면)")
_FACTOID_STOPWORDS = {
    "무엇",
    "어떤",
    "얼마",
    "얼마나",
    "어디",
    "언제",
    "누가",
    "해주세요",
    "알려줘",
    "질문",
    "답변",
    "문서",
    "기준",
}


def _dedupe_keep_order(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        s = str(item or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _normalize_query_token(token: str) -> str:
    t = (token or "").strip().lower()
    if not t:
        return ""
    # 한국어 조사/어미를 단순 제거해 질의 핵심어를 정규화
    suffixes = [
        "입니다",
        "입니까",
        "일까요",
        "일지",
        "인가요",
        "인가",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "에",
        "의",
        "와",
        "과",
        "로",
        "으로",
        "도",
        "만",
    ]
    for sfx in suffixes:
        if len(t) > len(sfx) + 1 and t.endswith(sfx):
            t = t[: -len(sfx)]
            break
    return t


def _query_focus_terms(query: str) -> List[str]:
    generic = {
        "문서",
        "기준",
        "항목",
        "내용",
        "질문",
        "답변",
        "표",
        "테이블",
        "이미지",
        "그림",
        "사진",
        "도표",
        "값",
        "일자",
        "날짜",
        "언제",
        "무엇",
    }
    out: List[str] = []
    for raw in re.findall(r"[0-9A-Za-z가-힣]+", query or ""):
        tok = _normalize_query_token(raw)
        if len(tok) < 2:
            continue
        if tok in _FACTOID_STOPWORDS or tok in generic:
            continue
        out.append(tok)
    return _dedupe_keep_order(out)


def _normalize_compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _query_target_segment(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    m = re.search(r"(?:문서|사업)?에서[, ]*(.+)$", q)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return q


def _query_numeric_spans(query: str) -> List[str]:
    out: List[str] = []
    q = query or ""
    for m in re.finditer(r"\d[\d,]*(?:\s*(?:~|→|-)\s*\d[\d,]*)?", q):
        token = re.sub(r"\s+", "", m.group(0))
        if len(token) >= 2:
            out.append(token)
    return _dedupe_keep_order(out)


def _to_numeric(token: str) -> float | None:
    t = re.sub(r"[,\s]", "", str(token or ""))
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    try:
        return float(t)
    except Exception:
        return None


def _query_single_numeric_target(query: str) -> float | None:
    spans = _query_numeric_spans(_query_target_segment(query))
    singles: List[float] = []
    for span in spans:
        if re.search(r"[~\-–—→]", span):
            continue
        val = _to_numeric(span)
        if val is not None:
            singles.append(val)
    if len(singles) == 1:
        return singles[0]
    return None


def _window_has_range_covering_target(window: str, target: float) -> bool:
    w = (window or "").replace(" ", "")
    # 예: 1,000~2,000 / 1000-2000
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:~|\-|–|—|→)\s*(\d[\d,]*(?:\.\d+)?)", w):
        lo = _to_numeric(m.group(1))
        hi = _to_numeric(m.group(2))
        if lo is None or hi is None:
            continue
        low, high = (lo, hi) if lo <= hi else (hi, lo)
        if low <= target <= high:
            return True

    # 예: 1,000이상2,000미만 / 1000이상2000이하
    for m in re.finditer(
        r"(\d[\d,]*(?:\.\d+)?)이상(\d[\d,]*(?:\.\d+)?)(미만|이하|초과|이상)",
        w,
    ):
        lo = _to_numeric(m.group(1))
        hi = _to_numeric(m.group(2))
        if lo is None or hi is None:
            continue
        low, high = (lo, hi) if lo <= hi else (hi, lo)
        upper_kw = m.group(3)
        if upper_kw == "미만":
            if low <= target < high:
                return True
        elif upper_kw == "이하":
            if low <= target <= high:
                return True
        elif upper_kw == "초과":
            if low < target < high:
                return True
        elif upper_kw == "이상":
            if low <= target <= high:
                return True
    return False


def _window_has_any_numeric_range(window: str) -> bool:
    w = (window or "").replace(" ", "")
    if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:~|\-|–|—|→)\s*\d[\d,]*(?:\.\d+)?", w):
        return True
    if re.search(r"\d[\d,]*(?:\.\d+)?이상\d[\d,]*(?:\.\d+)?(?:미만|이하|초과|이상)", w):
        return True
    return False


def _query_table_terms(query: str) -> List[str]:
    target = _query_target_segment(query)
    base = _query_focus_terms(target)
    for token in _query_numeric_spans(target):
        base.append(token)
    return _dedupe_keep_order(base)


def _overlap_count(text: str, terms: Sequence[str]) -> float:
    hay = _normalize_compact(text)
    if not hay:
        return 0.0
    hay_alt = hay.replace("0", "o")
    score = 0.0
    generic_terms = {"항목", "내용", "문서", "사업", "기준", "값", "값은", "선수", "지표"}
    for term in terms:
        tok = _normalize_compact(term)
        if len(tok) < 2:
            continue
        tok_alt = tok.replace("0", "o")
        if tok in hay or tok_alt in hay_alt:
            if tok in generic_terms:
                w = 0.35
            elif re.search(r"[a-z]", tok):
                w = 1.6
            elif len(tok) >= 4:
                w = 1.2
            else:
                w = 1.0
            score += w
    return score


def _preferred_plane_side(query: str) -> str:
    q = query or ""
    if re.search(r"오른쪽\s*평면도", q):
        return "오른쪽"
    if re.search(r"왼쪽\s*평면도", q):
        return "왼쪽"
    return ""


def _terminal_field_token(query: str) -> str:
    q = _query_target_segment(query)
    m_field = re.search(
        r"(수량|번호|기간|일자|날짜|비율|치수|길이|가로|세로|tatk|tdef|tprb)\s*은",
        q,
        re.IGNORECASE,
    )
    if m_field:
        return _normalize_compact(m_field.group(1))

    patterns = [
        r"([0-9A-Za-z가-힣]+)\s*값(?:은|는)",
        r"([0-9A-Za-z가-힣]+)\s*(?:은|는)\??$",
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if not m:
            continue
        tok = _normalize_compact(m.group(1))
        if len(tok) >= 2 and tok not in {"무엇", "얼마", "몇", "값"}:
            return tok
    return ""


def _extract_image_alt_json_objects(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    s = text or ""
    i = 0
    while True:
        start = s.find("![{", i)
        if start < 0:
            break
        j = start + 2  # points to '{'
        depth = 0
        in_str = False
        esc = False
        end = -1
        while j < len(s):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end < 0:
            i = start + 3
            continue
        raw = s[start + 2 : end + 1]
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            pass
        i = end + 1
    return out


def _extract_code_blocks(text: str) -> List[str]:
    return re.findall(r"```(?:[^\n`]*)\n?([\s\S]*?)```", text or "")


def _parse_tsv_table_block(block: str) -> Dict[str, object] | None:
    rows: List[List[str]] = []
    for line in (block or "").splitlines():
        raw = line.rstrip()
        if not raw.strip():
            continue
        if "\t" not in raw:
            continue
        cells = [c.strip() for c in raw.split("\t")]
        rows.append(cells)
    if len(rows) < 2:
        return None
    headers = rows[0]
    body = rows[1:]
    max_len = max(len(headers), *(len(r) for r in body))
    headers = headers + [""] * (max_len - len(headers))
    norm_rows: List[List[str]] = []
    for row in body:
        norm_rows.append(row + [""] * (max_len - len(row)))
    return {"type": "table", "title": "", "headers": headers, "rows": norm_rows}


def _extract_table_payloads(text: str) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for obj in _extract_image_alt_json_objects(text):
        if str(obj.get("type", "")).strip().lower() == "table":
            out.append(obj)
    for block in _extract_code_blocks(text):
        parsed = _parse_tsv_table_block(block)
        if parsed is not None:
            out.append(parsed)
    return out


def _value_kind_bonus(value: str, kind: str) -> float:
    v = value or ""
    if kind == "period":
        return 0.5 if _PERIOD_RE.search(v) else -0.2
    if kind == "date":
        return 0.5 if (_DATE_RE.search(v) or _DATE_COMPACT_RE.search(v)) else -0.2
    if kind == "money":
        return 0.6 if _MONEY_RE.search(v) else -0.3
    if kind == "percent":
        return 0.5 if (_PERCENT_RE.search(v) or _FRACTION_OF_100_RE.search(v)) else -0.2
    if re.search(r"\d", v):
        return 0.3
    return 0.0


def _is_value_seeking_query(query: str) -> bool:
    q = query or ""
    return bool(
        re.search(
            r"(값|수량|번호|코드|일자|날짜|기간|비율|치수|가로|세로|폭|높이|길이|얼마|몇)",
            q,
        )
    )


def _is_complex_comparison_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if re.search(r"(비교|차이|각각|동시에|모두|종합|요약|어떻게\s*다른)", q):
        return True
    if len(q) >= 35 and re.search(r"(의무|절차|요구사항|충족)", q):
        return True
    return False


def _is_min_period_query(query: str) -> bool:
    q = _normalize_compact(query)
    return ("최소" in q) and ("사업기간" in q)


def _score_factoid_candidate(query: str, text: str, value: str, kind: str) -> float:
    w = _match_window(text or "", value or "", radius=150)
    wl = w.lower()
    target_query = _query_target_segment(query)
    focus_terms = _query_focus_terms(target_query)
    overlap = sum(1 for t in focus_terms if t and t in wl)
    score = 0.5 * overlap + _value_kind_bonus(value, kind)

    q = target_query
    if kind == "period":
        if "최소" in q and "최소" in w:
            score += 1.0
        if "평균" in q and "평균" in w:
            score += 1.0
        if "최대" in q and "최대" in w:
            score += 1.0
        for span in _query_numeric_spans(q):
            if span and span in _normalize_compact(w):
                score += 0.8
                break
        # 단일 수치 규모(예: 1500) 질의는 해당 수치를 포함하는 구간 행을 강하게 우선
        target_num = _query_single_numeric_target(q)
        if target_num is not None:
            if _window_has_range_covering_target(w, target_num):
                score += 2.2
            elif _window_has_any_numeric_range(w):
                score -= 1.2
        if _is_min_period_query(q):
            if re.search(r"\d+(?:\.\d+)?\s*개월\s*이상", value or ""):
                score += 1.0
            elif re.search(r"\d+\s*개월", value or ""):
                score -= 0.6
            if re.search(r"\d+\.\d+\s*개월", value or ""):
                score -= 1.4
    if _is_value_seeking_query(q) and not re.search(r"\d|[A-Za-z]", value or ""):
        score -= 0.6
    if len((value or "").strip()) > 120:
        score -= 0.7
    return score


def _extract_table_value_candidates(query: str, kind: str, text: str) -> List[Tuple[float, str]]:
    candidates: List[Tuple[float, str]] = []
    tables = _extract_table_payloads(text)
    if not tables:
        return candidates

    target_query = _query_target_segment(query)
    terms = _query_table_terms(target_query)
    if not terms:
        return candidates
    preferred_side = _preferred_plane_side(target_query)
    terminal_field = _terminal_field_token(target_query)

    for table in tables:
        table_title = str(table.get("title", "") or "")
        headers_raw = table.get("headers")
        rows_raw = table.get("rows")
        headers: List[str] = []
        if isinstance(headers_raw, list):
            headers = [str(h or "").strip() for h in headers_raw]
        rows: List[List[str]] = []
        if isinstance(rows_raw, list):
            for r in rows_raw:
                if isinstance(r, list):
                    rows.append([str(x or "").strip() for x in r])
                elif isinstance(r, dict):
                    rows.append([str(v or "").strip() for _, v in sorted(r.items())])
        if not rows:
            continue

        col_scores: Dict[int, float] = {}
        if headers:
            for ci, h in enumerate(headers):
                score = _overlap_count(h, terms)
                if preferred_side and preferred_side in h:
                    score += 2
                if terminal_field and terminal_field in _normalize_compact(h):
                    score += 3
                col_scores[ci] = score
        best_col = -1
        best_col_score = 0.0
        if col_scores:
            best_col, best_col_score = max(col_scores.items(), key=lambda x: x[1])

        for row in rows:
            if not row:
                continue
            row_text = " | ".join(row)
            row_score = _overlap_count(row_text, terms)
            target_num = _query_single_numeric_target(target_query)
            if target_num is not None and re.search(r"(규모|구간)", target_query):
                if _window_has_range_covering_target(row_text, target_num):
                    row_score += 2.6
                elif _window_has_any_numeric_range(row_text):
                    row_score -= 1.3
            if row_score <= 0:
                continue

            picked_idx = -1
            if best_col >= 0 and best_col_score > 0 and best_col < len(row):
                picked_idx = best_col
            else:
                label_idx = -1
                label_score = 0
                for ci, cell in enumerate(row):
                    s = _overlap_count(cell, terms)
                    if s > label_score:
                        label_score = s
                        label_idx = ci
                if label_idx >= 0 and (label_idx + 1) < len(row):
                    picked_idx = label_idx + 1
                elif len(row) > 1:
                    picked_idx = 1

            if picked_idx < 0 or picked_idx >= len(row):
                continue
            value = str(row[picked_idx] or "").strip()
            if not value:
                continue
            if picked_idx == 0 and len(row) > 1:
                # 다열 표의 첫 열은 보통 row key이므로 값 후보에서 제외
                continue

            score = (1.6 * row_score) + (1.2 * max(0, best_col_score)) + _value_kind_bonus(value, kind)
            if kind == "period" and _is_min_period_query(target_query):
                title_compact = _normalize_compact(table_title)
                if "최소" in title_compact and "사업기간" in title_compact:
                    score += 1.2
                elif title_compact:
                    score -= 0.8
                if re.search(r"\d+(?:\.\d+)?\s*개월\s*이상", value):
                    score += 0.8
                elif re.search(r"\d+\s*개월", value):
                    score -= 0.4
                if re.search(r"\d+\.\d+\s*개월", value):
                    score -= 1.2
            if "|" in value and ("분할" in target_query or "구간" in target_query):
                score += 0.6
            if "번호" in target_query and re.fullmatch(r"\d{1,2}", value):
                score -= 1.6
            if "번호" in target_query:
                if _ALNUM_CODE_RE.search(value) or re.search(r"\b\d{4}-\d{2,4}\b", value):
                    score += 2.0
                if len(value) > 30:
                    score -= 2.2
            if "수량" in target_query and not re.search(r"(식|개|건|명|대)", value):
                score -= 1.0
            if "tatk" in target_query.lower():
                if re.fullmatch(r"\d+(?:\.\d+)?", value):
                    score += 0.6
                else:
                    score -= 1.0
            if ("가로" in target_query or "세로" in target_query or "치수" in target_query) and not re.search(
                r"\d",
                value,
            ):
                score -= 1.0
            if len(value) > 120:
                score -= 0.7
            candidates.append((score, value))

    # 동일 값은 최고 점수만 유지
    by_value: Dict[str, float] = {}
    for score, value in candidates:
        prev = by_value.get(value)
        if prev is None or score > prev:
            by_value[value] = score
    return sorted([(s, v) for v, s in by_value.items()], key=lambda x: x[0], reverse=True)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_client():
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    from openai import OpenAI  # type: ignore

    return OpenAI(api_key=api_key)


def _load_chunks_b(joined_chunks_path: Path) -> List[ChunkRecord]:
    rich_chunks = load_chunks_rich(Path("notebooks") / "data_chunks_rich")
    joined_meta = load_joined_metadata(joined_chunks_path)
    return [
        ChunkRecord(
            source_path=item.source_path,
            chunk_index=item.chunk_index,
            chunk_id=item.chunk_id,
            text=item.text,
            metadata=joined_meta.get(
                (item.source_path, item.chunk_index),
                item.metadata if isinstance(item.metadata, dict) else None,
            ),
        )
        for item in rich_chunks
    ]


def _build_retriever(
    *,
    retriever_kind: str,
    chunks_b: Sequence[ChunkRecord],
    dense_index_b: Path,
    hybrid_alpha: float,
    table_multiplier: float,
    chroma_persist_dir: Path,
    chroma_collection: str,
    chroma_model: str,
    chroma_org_filter: bool,
    chroma_org_filter_mode: str,
    chroma_score_weight: float,
    lexical_score_weight: float,
    chroma_noise_mode: str,
    chroma_mmr: bool,
    chroma_mmr_lambda: float,
    chroma_query_rewrite: bool,
):
    kind = retriever_kind.lower()
    if kind == "tfidf":
        return TfidfRetriever("B", chunks_b)
    if kind == "chroma":
        return ChromaRetriever(
            chunks=chunks_b,
            persist_dir=chroma_persist_dir,
            collection_name=chroma_collection,
            model=chroma_model,
            org_hard_filter=chroma_org_filter,
            org_filter_mode=chroma_org_filter_mode,
            chroma_score_weight=chroma_score_weight,
            lexical_score_weight=lexical_score_weight,
            noise_mode=chroma_noise_mode,
            use_mmr=chroma_mmr,
            mmr_lambda=chroma_mmr_lambda,
            query_rewrite=chroma_query_rewrite,
        )

    if kind in {"dense", "hybrid"}:
        embedder = DenseEmbedder()
        dense_b = DenseIndex.load(dense_index_b / "index.npz", dense_index_b / "meta.json")
        if kind == "dense":
            return DenseRetriever("B", dense_b, embedder, table_multiplier, chunks_b)
        return HybridRetriever(
            "B",
            chunks_b,
            dense_b,
            embedder,
            hybrid_alpha,
            table_multiplier,
            org_hard_filter=True,
        )

    raise RuntimeError(f"지원하지 않는 retriever: {retriever_kind}")


class ChromaRetriever:
    name = "B"
    kind = "chroma"

    def __init__(
        self,
        *,
        chunks: Sequence[ChunkRecord],
        persist_dir: Path,
        collection_name: str,
        model: str,
        org_hard_filter: bool = False,
        org_filter_mode: str = "hard",
        chroma_score_weight: float = 0.7,
        lexical_score_weight: float = 0.3,
        noise_mode: str = "soft",
        use_mmr: bool = False,
        mmr_lambda: float = 0.85,
        query_rewrite: bool = False,
    ) -> None:
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._model = model
        self._org_hard_filter = bool(org_hard_filter)
        mode = str(org_filter_mode or "").strip().lower()
        if mode not in {"hard", "soft", "adaptive"}:
            mode = "hard" if self._org_hard_filter else "soft"
        self._org_filter_mode = mode
        cw = max(0.0, float(chroma_score_weight))
        lw = max(0.0, float(lexical_score_weight))
        if cw + lw <= 0:
            cw, lw = 0.7, 0.3
        denom = cw + lw
        self._chroma_weight = cw / denom
        self._lexical_weight = lw / denom
        self._noise_mode = str(noise_mode or "soft").lower()
        if self._noise_mode not in {"off", "soft", "hard"}:
            self._noise_mode = "soft"
        self._use_mmr = bool(use_mmr)
        self._mmr_lambda = max(0.0, min(1.0, float(mmr_lambda)))
        self._query_rewrite = bool(query_rewrite)

        self._lexical_chunks: List[LexicalChunkRecord] = [
            LexicalChunkRecord(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                chunk_id=c.chunk_id,
                text=c.text,
                metadata=c.metadata if isinstance(c.metadata, dict) else None,
            )
            for c in chunks
        ]
        self._lexical_vectors, self._lexical_idf = (
            _build_tfidf(self._lexical_chunks) if self._lexical_chunks else ([], {})
        )
        self._lexical_idx_map: Dict[Tuple[str, int], int] = {
            (c.source_path, c.chunk_index): i for i, c in enumerate(self._lexical_chunks)
        }
        self._lexical_chunk_map: Dict[Tuple[str, int], LexicalChunkRecord] = {
            (c.source_path, c.chunk_index): c for c in self._lexical_chunks
        }
        source_to_indices: Dict[str, set[int]] = defaultdict(set)
        for c in self._lexical_chunks:
            source_to_indices[c.source_path].add(c.chunk_index)
        self._source_index_set: Dict[str, set[int]] = {
            source: idxs for source, idxs in source_to_indices.items()
        }

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        q = unicodedata.normalize("NFC", query or "").strip()
        q_search = _rewrite_query_for_retrieval(q) if self._query_rewrite else q
        org = _extract_org_hint(q)
        kind = _question_kind(q)
        is_multi_entity_comparison = _is_multi_entity_comparison_query(q)

        # 2-pass 검색:
        # 1) 기관 후보가 있으면 기관 필터 결과를 우선
        # 2) 부족하면 전체 검색으로 보완
        results = []
        if org:
            filtered = []
            selected_org = org
            for cand in _org_filter_candidates(org, q):
                filtered = search_chroma(
                    query=q_search,
                    persist_dir=self._persist_dir,
                    collection_name=self._collection_name,
                    model=self._model,
                    top_k=k,
                    fetch_k=max(k * 50, 500),
                    org=cand,
                )
                if filtered:
                    selected_org = cand
                    break
            mode = self._org_filter_mode
            if is_multi_entity_comparison and mode == "hard":
                # 비교 질의에서 기관이 2개 이상 감지되면 hard filter를 완화해
                # 한쪽 기관으로의 과도한 편향을 줄인다.
                mode = "soft"
            if mode == "hard":
                results = filtered
                if not results:
                    # 기관 힌트가 빗나간 경우 전체 검색으로 최소한의 recall을 확보한다.
                    results = search_chroma(
                        query=q_search,
                        persist_dir=self._persist_dir,
                        collection_name=self._collection_name,
                        model=self._model,
                        top_k=k,
                        fetch_k=max(k * 30, 200),
                        org=None,
                    )
            else:
                unfiltered = search_chroma(
                    query=q_search,
                    persist_dir=self._persist_dir,
                    collection_name=self._collection_name,
                    model=self._model,
                    top_k=k,
                    fetch_k=max(k * 30, 200),
                    org=None,
                )
                if mode == "soft":
                    results = filtered + unfiltered
                else:
                    # adaptive:
                    # 기관 힌트 신뢰도가 높거나 기관 필터 결과가 충분하면 hard처럼 동작.
                    conf = _org_confidence(q, selected_org)
                    enough = len(filtered) >= max(5, k // 4)
                    if conf >= 0.9 or enough:
                        results = filtered
                    else:
                        results = filtered + unfiltered
        else:
            # 기관 힌트가 없더라도 검색을 수행해 0-retrieval을 줄인다.
            results = search_chroma(
                query=q_search,
                persist_dir=self._persist_dir,
                collection_name=self._collection_name,
                model=self._model,
                top_k=k,
                fetch_k=max(k * 30, 200),
                org=None,
            )

        scored: List[tuple[ChunkRecord, float, int]] = []
        seen: set[tuple[str, int]] = set()
        for pos, item in enumerate(results):
            try:
                chunk_index = int(item.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            source_path = str(item.get("source_path", ""))
            key = (source_path, chunk_index)
            if key in seen:
                continue
            seen.add(key)
            score = float(item.get("score", 0.0))
            chunk = ChunkRecord(
                source_path=source_path,
                chunk_index=chunk_index,
                chunk_id=str(item.get("chunk_id", "")),
                text=str(item.get("text", "")),
                metadata={
                    "org": item.get("org", ""),
                    "type": item.get("type", ""),
                    "source": item.get("source", source_path),
                },
            )
            scored.append((chunk, score, pos))

        if kind == "money" and scored:
            scored = self._expand_money_neighbor_candidates(scored)

        # 질의 내 영문/숫자 고신호 토큰(IP-NAVI 등)을 별도로 추적해
        # 해당 토큰이 실제 source/text에 나타나는 청크를 우선한다.
        signal_terms = _extract_signal_terms(q)
        signal_match_count: Dict[Tuple[str, int], int] = {}
        signal_any_match = False
        for c, _, _ in scored:
            key = (c.source_path, c.chunk_index)
            hay = f"{c.source_path}\n{c.text}".lower()
            cnt = sum(1 for t in signal_terms if t and t in hay)
            signal_match_count[key] = cnt
            if cnt > 0:
                signal_any_match = True

        # 캡션/테이블 JSON 잔재처럼 값 추출에 방해가 되는 노이즈 청크를 감점한다.
        # hard 모드에서는 강한 노이즈 청크를 사전에 제거한다.
        if self._noise_mode == "hard":
            hard_filtered: List[tuple[ChunkRecord, float, int]] = []
            for c, s, pos in scored:
                hits = _noise_hits(c.text)
                threshold = 1 if kind == "money" else 2
                if hits >= threshold and not _has_value_hint(c.text, kind):
                    continue
                hard_filtered.append((c, s, pos))
            if hard_filtered:
                scored = hard_filtered

        noise_penalty_map: Dict[Tuple[str, int], float] = {}
        for c, _, _ in scored:
            key = (c.source_path, c.chunk_index)
            hits = _noise_hits(c.text)
            if self._noise_mode == "off":
                noise_penalty_map[key] = 0.0
            elif self._noise_mode == "hard":
                unit_pen = 0.16 if kind == "money" else 0.10
                noise_penalty_map[key] = -unit_pen * hits
            else:
                unit_pen = 0.22 if kind == "money" else 0.18
                noise_penalty_map[key] = -unit_pen * hits

        lexical_score_map: Dict[Tuple[str, int], float] = {}
        if scored and self._lexical_chunks:
            all_lexical_scores = tfidf_scores(
                q,
                self._lexical_chunks,
                self._lexical_vectors,
                self._lexical_idf,
            )
            for c, _, _ in scored:
                key = (c.source_path, c.chunk_index)
                idx = self._lexical_idx_map.get(key)
                if idx is None:
                    lexical_score_map[key] = 0.0
                else:
                    lexical_score_map[key] = float(all_lexical_scores[idx])

            max_lex = max(lexical_score_map.values()) if lexical_score_map else 0.0
            if max_lex > 0:
                for key in list(lexical_score_map.keys()):
                    lexical_score_map[key] = lexical_score_map[key] / max_lex

        # same-source keyword rerank:
        # 소스 내에서 값/키워드 근거가 풍부한 청크를 우선하도록 조정
        def _keyword_bonus(qtext: str, text: str, source_path: str, org_hint: str | None) -> float:
            bonus = 0.0
            q_kind = _question_kind(qtext)
            if q_kind == "percent":
                if _PERCENT_RE.search(text) or _FRACTION_OF_100_RE.search(text):
                    bonus += 1.2
                else:
                    bonus -= 0.2
            elif q_kind == "money":
                if _MONEY_RE.search(text):
                    bonus += 1.2
                elif _BUDGET_KEYWORD_RE.search(text) and _MONEY_LOOSE_RE.search(text):
                    bonus += 0.8
                elif _BUDGET_KEYWORD_RE.search(text):
                    bonus += 0.2
                else:
                    bonus -= 0.2
            elif q_kind == "date":
                if _DATE_RE.search(text):
                    bonus += 1.0
                else:
                    bonus -= 0.1
            elif q_kind == "period":
                if _PERIOD_RE.search(text):
                    bonus += 1.0
                else:
                    bonus -= 0.1

            q_tokens = [t for t in re.findall(r"[0-9A-Za-z가-힣]+", qtext.lower()) if len(t) >= 2][:8]
            if q_tokens:
                overlap = sum(1 for t in q_tokens if t in text.lower())
                bonus += min(overlap * 0.1, 0.5)
            if org_hint:
                sp = source_path.lower().replace(" ", "")
                hint = org_hint.lower().replace(" ", "")
                if hint in sp:
                    bonus += 0.6
            return bonus

        source_best: Dict[str, float] = {}
        for c, _, _ in scored:
            b = _keyword_bonus(q, c.text, c.source_path, org)
            prev = source_best.get(c.source_path, -1.0)
            if b > prev:
                source_best[c.source_path] = b

        reranked = []
        for c, s, pos in scored:
            key = (c.source_path, c.chunk_index)
            lex = lexical_score_map.get((c.source_path, c.chunk_index), 0.0)
            kb = _keyword_bonus(q, c.text, c.source_path, org)
            sb = source_best.get(c.source_path, 0.0)
            signal_bonus = 0.0
            if signal_terms and signal_any_match:
                cnt = signal_match_count.get(key, 0)
                signal_bonus = min(0.25 * cnt, 0.75) if cnt > 0 else -0.30
            noise_pen = noise_penalty_map.get(key, 0.0)
            base = (self._chroma_weight * s) + (self._lexical_weight * lex)
            final = base + (0.26 * kb) + (0.12 * sb) + signal_bonus + noise_pen - (0.0001 * pos)
            reranked.append((c, final))
        reranked.sort(key=lambda x: x[1], reverse=True)

        if self._use_mmr and len(reranked) > 1:
            reranked = _apply_mmr_sparse(
                reranked,
                k=max(k, 1),
                lambda_mult=self._mmr_lambda,
                idx_map=self._lexical_idx_map,
                vectors=self._lexical_vectors,
            )

        out: List[ChunkRecord] = []
        for c, _ in reranked:
            out.append(c)
            if len(out) >= k:
                break
        return out[:k]

    def _expand_money_neighbor_candidates(
        self, scored: List[tuple[ChunkRecord, float, int]]
    ) -> List[tuple[ChunkRecord, float, int]]:
        expanded = list(scored)
        seen = {(c.source_path, c.chunk_index) for c, _, _ in expanded}
        top_seed = min(len(scored), 12)
        offsets = (-2, -1, 1, 2, 3)
        next_pos = len(expanded)

        for i in range(top_seed):
            c, s, _ = scored[i]
            src = c.source_path
            base_idx = c.chunk_index
            idx_set = self._source_index_set.get(src)
            if idx_set is None:
                continue
            for d in offsets:
                cand_idx = base_idx + d
                key = (src, cand_idx)
                if cand_idx < 0 or cand_idx not in idx_set or key in seen:
                    continue
                rec = self._lexical_chunk_map.get(key)
                if rec is None:
                    continue
                text = rec.text or ""
                if not (_BUDGET_KEYWORD_RE.search(text) or _MONEY_RE.search(text) or _MONEY_LOOSE_RE.search(text)):
                    continue
                neighbor = ChunkRecord(
                    source_path=rec.source_path,
                    chunk_index=rec.chunk_index,
                    chunk_id=rec.chunk_id,
                    text=rec.text,
                    metadata=rec.metadata if isinstance(rec.metadata, dict) else None,
                )
                # 인접 청크는 의미 보강용 후보이므로 소폭 낮은 초기점수를 부여한다.
                adj_score = s - (0.06 * abs(d))
                expanded.append((neighbor, adj_score, next_pos))
                next_pos += 1
                seen.add(key)

        return expanded


def _rerank(
    query: str,
    results: List[ChunkRecord],
    *,
    rerank_mode: str,
    llm_model: str,
) -> Tuple[List[ChunkRecord], float]:
    mode = rerank_mode.lower()
    if mode == "none" or not results:
        return results, 0.0

    if mode == "rule":
        candidates = [
            {
                "text": item.text,
                "source_path": item.source_path,
                "chunk_id": item.chunk_id,
                "metadata": item.metadata if isinstance(item.metadata, dict) else None,
            }
            for item in results
        ]
        ranked = rerank_rule(query, candidates)
        id_map = {item.chunk_id: item for item in results}
        return [id_map[item.get("chunk_id", "")] for item in ranked if item.get("chunk_id", "") in id_map], 0.0

    candidates = [
        {
            "text": item.text,
            "source_path": item.source_path,
            "chunk_id": item.chunk_id,
        }
        for item in results
    ]
    ranked, cost_usd = rerank_openai(query, candidates, model=llm_model)
    id_map = {item.chunk_id: item for item in results}
    reranked = [id_map[item.get("chunk_id", "")] for item in ranked if item.get("chunk_id", "") in id_map]
    return reranked, cost_usd


def _extract_output_text(response) -> str:
    text = getattr(response, "output_text", None) or ""
    if text:
        return text.strip()

    parts: List[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            ctype = getattr(content, "type", "")
            if ctype in {"output_text", "text"}:
                parts.append(str(getattr(content, "text", "")))
    return "\n".join(parts).strip()


def _parse_json_object(text: str) -> Dict[str, object]:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _question_kind(query: str) -> str:
    q = query.strip()
    if re.search(r"비율|퍼센트|%", q):
        return "percent"
    if re.search(r"마감|일자|언제|날짜", q):
        return "date"
    is_frequency_query = bool(re.search(r"얼마나\s*(자주|빈도|횟수|주기)", q))
    if re.search(r"기간|며칠|몇\s*개월|몇\s*회", q) or is_frequency_query:
        return "period"
    if re.search(r"문의|연락처|전화|이메일|담당자", q):
        return "contact"
    if _MONEY_STANDALONE_RE.search(q) or (
        re.search(r"얼마", q) and "얼마나" not in q and _MONEY_OBJECT_RE.search(q)
    ):
        return "money"
    if re.search(r"(개요|요약|정리|설명)", q):
        if not _is_value_seeking_query(q):
            return "overview"
    return "generic"


def _extract_signal_terms(query: str) -> List[str]:
    raw_terms = [
        t.lower().strip("-_/")
        for t in re.findall(r"[0-9A-Za-z][0-9A-Za-z\\-_/]{2,}", query or "")
        if len(t.strip("-_/")) >= 3
    ]
    # 한글 핵심어(예: 확정요청번호, 접수일자)도 signal rerank에 반영한다.
    for t in _query_focus_terms(_query_target_segment(query)):
        tok = (t or "").lower().strip()
        if len(tok) >= 2:
            raw_terms.append(tok)
    return _dedupe_keep_order(raw_terms)[:10]


def _noise_hits(text: str) -> int:
    t = (text or "").lower()
    hits = 0
    if '"summary"' in t and "]]" in t:
        hits += 1
    if "../data_assets/" in t:
        hits += 1
    if '"type": "table"' in t or '"type":"table"' in t:
        hits += 1
    if t.lstrip().startswith("!["):
        hits += 1
    return hits


def _sanitize_context_text(text: str) -> str:
    if not text:
        return ""
    t = text.replace("\r", "\n")
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", t)
    t = re.sub(r"\.\./data_assets/[^\s)]+", " ", t)
    t = re.sub(r"\]\(\.\./data_assets/[^\)\s]+\)", " ", t)
    t = re.sub(r"\{[\s\S]{0,200}?\"(?:summary|headers|rows|type)\"[\s\S]{0,200}?\}", " ", t)

    kept: List[str] = []
    for line in t.split("\n"):
        s = line.strip()
        if not s:
            continue
        if "../data_assets/" in s:
            continue
        if _noise_hits(s) >= 2:
            continue
        kept.append(s)
    out = re.sub(r"\s+", " ", " ".join(kept)).strip()
    return out[:2200]


def _sanitize_contexts_for_answer(contexts: Sequence[ChunkRecord]) -> List[ChunkRecord]:
    out: List[ChunkRecord] = []
    for c in contexts:
        clean_text = _sanitize_context_text(c.text or "")
        if not clean_text:
            clean_text = re.sub(r"\s+", " ", (c.text or "")).strip()[:600]
        out.append(
            ChunkRecord(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                chunk_id=c.chunk_id,
                text=clean_text,
                metadata=c.metadata if isinstance(c.metadata, dict) else None,
            )
        )
    return out


def _has_value_hint(text: str, kind: str) -> bool:
    t = text or ""
    if kind == "percent":
        return bool(_PERCENT_RE.search(t) or _FRACTION_OF_100_RE.search(t))
    if kind == "money":
        if _MONEY_RE.search(t):
            return True
        return bool(_BUDGET_KEYWORD_RE.search(t) and _MONEY_LOOSE_RE.search(t))
    if kind == "date":
        return bool(_DATE_RE.search(t))
    if kind == "period":
        return bool(_PERIOD_RE.search(t))
    if kind == "contact":
        return bool(_CONTACT_RE.search(t))
    if kind == "overview":
        return bool(re.search(r"(사업개요|과업\s*개요|추진\s*배경|사업\s*목적|주요\s*업무)", t))
    return bool(re.search(r"(예산|금액|기간|마감|문의|담당|연락처|입찰|평가)", t))


def _is_comparison_rewrite_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    return bool(re.search(r"(비교|차이|각각|동시에|모두|어떻게\s*다른|서로)", q))


def _comparison_rewrite_terms(query: str) -> List[str]:
    q = (query or "").strip()
    if not q:
        return []

    out: List[str] = []

    def _add(v: str) -> None:
        s = re.sub(r"\s+", " ", (v or "").strip())
        if not s:
            return
        if len(s) < 2:
            return
        if s not in out:
            out.append(s)

    head = q.split("에서", 1)[0].strip() if "에서" in q else q
    target = _query_target_segment(q)

    # 1) 인용부호 안 문서명/사업명 앵커
    quoted = re.findall(r"[\"'“”‘’]([^\"'“”‘’]{3,140})[\"'“”‘’]", q)
    for item in quoted[:4]:
        _add(item)

    # 2) "A와 B" 형태의 동적 엔티티 앵커
    parts = re.split(r"\s+(?:과|와|및)\s+", head)
    for part in parts[:4]:
        p = re.sub(r"[\"'“”‘’]", "", part).strip()
        if not p:
            continue
        if _ORG_SUFFIX_RE.search(p) or re.search(r"(용역|사업|시스템|공고|입찰|조직위원회|대회)", p):
            _add(p)

    # 3) 비교 질문의 핵심어(책임/제재/요구사항 등)는 질의에서 동적으로 추출
    for term in _query_focus_terms(target)[:8]:
        _add(term)

    # 4) 비교 질의 힌트
    _add("비교")
    _add("차이")
    return out[:18]


def _is_multi_entity_comparison_query(query: str) -> bool:
    q = (query or "").strip()
    if not _is_comparison_rewrite_query(q):
        return False

    quoted = re.findall(r"[\"'“”‘’]([^\"'“”‘’]{3,140})[\"'“”‘’]", q)
    if len(quoted) >= 2:
        return True

    head = q.split("에서", 1)[0].strip() if "에서" in q else q
    parts = re.split(r"\s+(?:과|와|및)\s+", head)
    meaningful = 0
    for part in parts:
        p = re.sub(r"[\"'“”‘’]", "", part).strip()
        if len(p) < 3:
            continue
        if _ORG_SUFFIX_RE.search(p) or re.search(r"(용역|사업|시스템|공고|입찰|조직위원회|대회)", p):
            meaningful += 1
    return meaningful >= 2


def _rewrite_query_for_retrieval(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q

    kind = _question_kind(q)
    additions: List[str] = []
    if _is_comparison_rewrite_query(q):
        additions.extend(_comparison_rewrite_terms(q))
    if kind == "money":
        additions += ["사업예산", "사업비", "총사업비", "예정가격", "기초금액", "금액"]
    elif kind == "date":
        additions += ["제안서 제출 마감일", "접수마감", "공고일", "제출일"]
    elif kind == "period":
        additions += ["사업기간", "수행기간", "계약기간", "개월", "일"]
    elif kind == "percent":
        additions += ["입찰보증금 비율", "평가비율", "기술평가 비중", "가격평가 비중"]
    elif kind == "contact":
        additions += ["문의처", "담당자", "연락처", "전화", "이메일"]

    for t in _extract_signal_terms(q):
        additions.append(t)

    seen = set()
    deduped: List[str] = []
    for tok in additions:
        s = tok.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    if not deduped:
        return q
    return f"{q} {' '.join(deduped)}"


def _sparse_cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, v in a.items():
        dot += v * b.get(k, 0.0)
    if dot == 0.0:
        return 0.0
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _apply_mmr_sparse(
    ranked: List[Tuple[ChunkRecord, float]],
    *,
    k: int,
    lambda_mult: float,
    idx_map: Dict[Tuple[str, int], int],
    vectors: Sequence[Dict[str, float]],
) -> List[Tuple[ChunkRecord, float]]:
    if not ranked:
        return []
    if len(ranked) <= 1 or k <= 1:
        return ranked[:k]

    rels = [s for _, s in ranked]
    min_rel, max_rel = min(rels), max(rels)
    denom = (max_rel - min_rel) if max_rel > min_rel else 1.0
    rel_norm = [(s - min_rel) / denom for _, s in ranked]

    selected: List[int] = [0]
    remaining = set(range(1, len(ranked)))

    while remaining and len(selected) < k:
        best_i = None
        best_score = -1e9
        for i in list(remaining):
            c_i, _ = ranked[i]
            idx_i = idx_map.get((c_i.source_path, c_i.chunk_index), -1)
            vec_i = vectors[idx_i] if 0 <= idx_i < len(vectors) else {}

            max_sim = 0.0
            for j in selected:
                c_j, _ = ranked[j]
                idx_j = idx_map.get((c_j.source_path, c_j.chunk_index), -1)
                vec_j = vectors[idx_j] if 0 <= idx_j < len(vectors) else {}
                sim = _sparse_cosine(vec_i, vec_j)
                if sim > max_sim:
                    max_sim = sim
            mmr_score = lambda_mult * rel_norm[i] - (1.0 - lambda_mult) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_i = i
        if best_i is None:
            break
        selected.append(best_i)
        remaining.discard(best_i)

    return [ranked[i] for i in selected][:k]


def _extract_org_hint(query: str) -> str | None:
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return None

    def _clean_org_token(token: str) -> str:
        tok = (token or "").strip()
        tok = tok.replace("㈜", "(주)")
        tok = tok.strip("`\"'“”‘’[]{}<>.,:;!?")
        tok = tok.replace("(주)", "").replace("주식회사", "").strip()
        if tok and not tok.startswith("("):
            tok = re.sub(r"\s*\([^)]*\)\s*$", "", tok).strip() or tok
        if len(tok) >= 2:
            tok = re.sub(r"(의|에서|와|과|및|은|는|이|가|을|를)$", "", tok)
        if "_" in tok:
            tok = tok.split("_", 1)[0]
        return tok.strip()

    def _looks_like_org_token(token: str) -> bool:
        tok = _clean_org_token(token)
        if not tok or tok in _ORG_STOPWORDS or len(tok) < 2:
            return False
        if tok.startswith(("한국", "대한", "국립", "국가", "재단법인", "사단법인", "(재)", "(사)", "주식회사")):
            return True
        if _ORG_SUFFIX_RE.search(tok):
            return True
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9.&-]{2,}", tok):
            return True
        if tok.endswith("사") and tok.startswith(("한국", "대한", "아시아")):
            return True
        return False

    head = q
    head_match = re.match(r"^(.{1,80}?)(?:의|에서|와|과|및)\b", q)
    if head_match:
        head = head_match.group(1).strip()

    raw_tokens = [t for t in head.split() if t.strip()]
    tokens = [_clean_org_token(t) for t in raw_tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None

    if tokens[0] in {"재단법인", "사단법인", "(재)", "(사)", "주식회사"} and len(tokens) >= 2:
        max_n = min(6, len(tokens))
        for n in range(2, max_n + 1):
            cand = " ".join(tokens[:n]).strip()
            if _looks_like_org_token(tokens[n - 1]) and len(cand) >= 3:
                return cand
        return " ".join(tokens[: min(3, len(tokens))]).strip()

    for n in range(min(3, len(tokens)), 0, -1):
        cand = " ".join(tokens[:n]).strip()
        if _looks_like_org_token(tokens[n - 1]) or (n == 1 and _looks_like_org_token(cand)):
            return cand

    for token in tokens[:5]:
        if _looks_like_org_token(token):
            return token
    return None


def _org_filter_candidates(org_hint: str | None, query: str) -> List[str]:
    base = re.sub(r"\s+", " ", (org_hint or "").strip())
    if not base:
        return []

    q = re.sub(r"\s+", " ", (query or "").strip())
    out: List[str] = []

    def _add(v: str) -> None:
        vv = re.sub(r"\s+", " ", (v or "").strip())
        if vv and vv not in out:
            out.append(vv)

    _add(base)

    # 법인 표기 변형: (사)/(재) + 기관명 형태를 보조 후보로 추가한다.
    # 일부 원문은 전각 괄호/문장부호((사）)를 사용하므로 함께 시도한다.
    if not re.match(r"^\((?:사|재)[\)）]", base):
        compact = base.replace(" ", "")
        for p in ("(사)", "(사）", "(재)", "(재）"):
            _add(f"{p}{base}")
            _add(f"{p}{compact}")
            _add(f"{p} {base}")

    if "(주)" in base:
        _add(base.replace("(주)", ""))
    elif "주식회사" in base:
        _add(base.replace("주식회사", ""))
    else:
        if base and f"{base}(주)" in q:
            _add(f"{base}(주)")
        if base and f"{base} (주)" in q:
            _add(f"{base} (주)")

    if "(용역)" in base:
        _add(base.replace("(용역)", ""))
    if base and re.search(rf"{re.escape(base)}\s*용역", q):
        _add(f"{base} (용역)")

    legal_prefixes = {"재단법인", "사단법인", "(재)", "(사)", "주식회사"}
    toks = [t for t in base.split() if t]
    if toks and toks[0] in legal_prefixes and len(toks) >= 3:
        _add(" ".join(toks[:2]))
        _add(" ".join(toks[1:3]))

    return out


def _org_confidence(query: str, org: str | None) -> float:
    if not org:
        return 0.0
    q = (query or "").strip()
    o = (org or "").strip()
    if not q or not o:
        return 0.0
    if (
        q.startswith(o + " ")
        or q.startswith(o + "의")
        or q.startswith(o + "에서")
        or q.startswith(o + "(")
    ) and _ORG_SUFFIX_RE.search(o):
        return 1.0
    if q.startswith(o) and len(o) >= 3:
        return 0.9
    if o in q and len(o) >= 3:
        return 0.7
    return 0.4


def _pick_matches(text: str, kind: str, query: str = "") -> List[str]:
    if kind == "percent":
        matches: List[str] = []
        for m in _FRACTION_OF_100_RE.findall(text):
            matches.append(f"{m}%")
        matches.extend(_PERCENT_RE.findall(text))
        return matches
    if kind == "money":
        strict = _MONEY_RE.findall(text)
        if strict:
            return strict
        if _BUDGET_KEYWORD_RE.search(text):
            loose = _MONEY_LOOSE_RE.findall(text)
            if loose:
                return loose
        return []
    if kind == "date":
        matches = _DATE_RE.findall(text)
        matches.extend(_DATE_COMPACT_RE.findall(text))
        return _dedupe_keep_order(matches)
    if kind == "period":
        return _PERIOD_RE.findall(text)
    if kind == "generic":
        matches: List[str] = []
        matches.extend(_ALNUM_CODE_RE.findall(text))
        matches.extend(re.findall(r"\b\d[\d,]*(?:\.\d+)?\s*(?:식|건|명|개|회|종)\b", text))
        # generic 질의에서 단순 숫자만 반환되며 오답이 급증한 케이스를 줄이기 위해,
        # 번호/코드 계열 질의에서만 bare number를 허용한다.
        if re.search(r"(번호|코드|\bid\b|\bno\b)", query or "", re.IGNORECASE):
            matches.extend(re.findall(r"\b\d+(?:\.\d+)?\b", text))
        return _dedupe_keep_order(matches)

    matches: List[str] = []
    for pattern in (_PERCENT_RE, _MONEY_RE, _DATE_RE, _PERIOD_RE):
        matches.extend(pattern.findall(text))
    return matches


def _factoid_tokens(query: str) -> List[str]:
    tokens = []
    for tok in re.findall(r"[0-9A-Za-z가-힣]+", (query or "").lower()):
        if len(tok) < 2:
            continue
        if tok in _FACTOID_STOPWORDS:
            continue
        tokens.append(tok)
    return tokens[:16]


def _match_window(text: str, value: str, radius: int = 120) -> str:
    t = text or ""
    v = value or ""
    if not t:
        return ""
    if not v:
        return t[: radius * 2]
    idx = t.find(v)
    if idx < 0:
        return t[: radius * 2]
    s = max(0, idx - radius)
    e = min(len(t), idx + len(v) + radius)
    return t[s:e]


def _is_factoid_match_relevant(query: str, text: str, value: str, kind: str) -> bool:
    window = _match_window(text, value)
    merged = window if kind in {"date", "period"} else f"{window} {text[:400]}"
    tokens = _factoid_tokens(query)
    overlap = sum(1 for t in tokens if t and t in merged.lower())

    if kind == "money":
        if not _BUDGET_KEYWORD_RE.search(merged):
            return False
    if kind == "period":
        # 규모/구간 기반 기간 질의는 질의 수치가 속한 구간 근거가 함께 있어야 한다.
        if re.search(r"(규모|구간)", query):
            target_num = _query_single_numeric_target(query)
            if target_num is not None:
                has_target_range = _window_has_range_covering_target(merged, target_num)
                compact = re.sub(r"\s+", "", merged)
                n_int = int(target_num) if float(target_num).is_integer() else None
                has_exact = False
                if n_int is not None:
                    has_exact = str(n_int) in compact or f"{n_int:,}" in compact
                if not has_target_range and not has_exact:
                    return False
        if re.search(r"(얼마나\s*(자주|빈도|주기)|주기|빈도|횟수|월\s*1회|매월|매주|매일)", query):
            if not re.search(r"(월\s*\d+\s*회|\d+\s*회|매월|매주|매일|주기|빈도)", merged):
                return False
        if "교육" in query and "교육" not in merged:
            return False
    if kind == "date":
        has_date_signal = bool(
            _DATE_RE.search(merged)
            or _DATE_COMPACT_RE.search(merged)
            or re.search(r"(마감|제출|접수|착수|종료)", merged)
        )
        if not has_date_signal:
            return False
        # 특정 키워드 하드코딩 대신 질의 핵심어와의 동적 문맥 일치를 요구한다.
        focus_terms = _query_focus_terms(query)
        if focus_terms:
            overlap = sum(1 for t in focus_terms if t in merged.lower())
            min_required = 1 if len(focus_terms) <= 2 else 2
            if overlap < min_required:
                return False
    if kind == "percent":
        if not (_PERCENT_RE.search(merged) or _FRACTION_OF_100_RE.search(merged)):
            return False

    return overlap >= 1


def _score_date_candidate(query: str, text: str, value: str) -> float:
    w = _match_window(text or "", value or "", radius=140)
    score = 0.0

    if re.fullmatch(r"\d{6}", value or ""):
        score += 2.0
    elif re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", value or ""):
        score += 0.4
    elif re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", value or ""):
        score += 0.2

    focus_terms = _query_focus_terms(query)
    if focus_terms:
        overlap = sum(1 for t in focus_terms if t in w.lower())
        score += 0.45 * overlap
        if overlap == 0:
            score -= 1.2

    if re.search(r"기간\s*필터", w):
        score -= 1.6

    return score


def _parse_top_n_for_rank_query(query: str, default: int = 3) -> int:
    q = query or ""
    m = re.search(r"\btop\s*(\d+)\b", q, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+)\s*(?:곳|기관|개|건)", q)
    if not m:
        return default
    try:
        n = int(m.group(1))
    except Exception:
        return default
    return max(1, min(n, 10))


def _extract_org_from_source(source_path: str) -> str:
    name = Path(source_path or "").name.strip()
    if not name:
        return ""
    base = re.sub(r"\.(?:pdf|hwp|docx?|txt)$", "", name, flags=re.IGNORECASE)
    if "_" in base:
        org = base.split("_", 1)[0].strip()
        if org:
            return org
    return base.strip()


def _extract_org_name(chunk: ChunkRecord) -> str:
    metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
    for key in ("org", "institution", "기관"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = metadata.get("meta")
    if isinstance(nested, dict):
        for key in ("발주 기관", "기관", "institution"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _extract_org_from_source(chunk.source_path)


def _parse_money_values(text: str) -> List[Tuple[float, str, int, int]]:
    out: List[Tuple[float, str, int, int]] = []
    if not text:
        return out
    for m in _MONEY_VALUE_RE.finditer(text):
        raw_num = m.group(1).replace(",", "")
        unit = m.group(2)
        try:
            num = float(raw_num)
        except Exception:
            continue
        multiplier = 1.0
        if unit == "억원":
            multiplier = 100_000_000.0
        elif unit == "만원":
            multiplier = 10_000.0
        elif unit == "천원":
            multiplier = 1_000.0
        value_won = num * multiplier
        out.append((value_won, m.group(0), m.start(), m.end()))
    return out


def _filter_budget_values(text: str, values: List[Tuple[float, str, int, int]]) -> List[Tuple[float, str, int, int]]:
    if not values:
        return []
    if _BUDGET_KEYWORD_RE.search(text):
        return values

    filtered: List[Tuple[float, str, int, int]] = []
    for item in values:
        _, _, s, e = item
        win = text[max(0, s - 28) : min(len(text), e + 28)]
        if _BUDGET_KEYWORD_RE.search(win):
            filtered.append(item)
    return filtered


def _user_guidance_tail(query: str, kind: str) -> str:
    if _is_complex_comparison_query(query):
        return "필요하시면 기관별 차이와 적용 포인트를 이어서 정리해드릴게요."
    if kind in {"money", "percent", "date", "period", "contact"}:
        return "필요하시면 근거 기준과 확인 포인트도 함께 안내해드릴게요."
    return "필요하시면 관련 기준을 더 자세히 안내해드릴게요."


def _format_user_facing_answer(answer: str, *, status: str, query: str, kind: str) -> str:
    text = str(answer or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return text
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = _INTERNAL_ANSWER_TERM_RE.sub("문서", text).strip()

    if status not in {"ok", "partial"}:
        return text
    if "문서에 해당 정보가 없습니다" in text:
        return text
    if _GUIDANCE_CUE_RE.search(text):
        return text

    guidance = _user_guidance_tail(query, kind)
    if "\n" in text:
        trimmed = text.rstrip()
        if not trimmed.endswith((".", "!", "?")):
            trimmed += "."
        return f"{trimmed}\n{guidance}"

    trimmed = text.rstrip()
    if not trimmed.endswith((".", "!", "?")):
        trimmed += "."
    return f"{trimmed} {guidance}"


def _finalize_answer_payload(
    payload: Dict[str, object],
    *,
    query: str,
    kind: str,
) -> Dict[str, object]:
    out = dict(payload)
    status = str(out.get("status", "")).strip().lower()
    answer = _format_user_facing_answer(
        str(out.get("answer", "")),
        status=status,
        query=query,
        kind=kind,
    )
    out["status"] = status
    out["answer"] = answer
    return out


def generate_money_rank_answer(
    query: str,
    contexts: Sequence[ChunkRecord],
) -> Dict[str, object]:
    if not contexts:
        return _finalize_answer_payload(
            {
            "status": "not_found",
            "answer": "문서에 해당 정보가 없습니다.",
            "citations": [],
            },
            query=query,
            kind="money",
        )

    top_n = _parse_top_n_for_rank_query(query, default=3)
    best_by_org: Dict[str, Tuple[float, str, int]] = {}

    for idx, c in enumerate(contexts, start=1):
        text = c.text or ""
        values = _parse_money_values(text)
        if not values:
            continue
        values = _filter_budget_values(text, values)
        if not values:
            continue
        best = max(values, key=lambda x: x[0])
        org = _extract_org_name(c).strip()
        if not org:
            continue
        prev = best_by_org.get(org)
        if prev is None or best[0] > prev[0]:
            best_by_org[org] = (best[0], best[1], idx)

    if not best_by_org:
        return _finalize_answer_payload(
            {
            "status": "not_found",
            "answer": "사업비 근거를 찾지 못했습니다.",
            "citations": [],
            },
            query=query,
            kind="money",
        )

    ranked = sorted(best_by_org.items(), key=lambda x: (-x[1][0], x[0]))[:top_n]
    lines = [f"{i}. {org} - {amount}" for i, (org, (_, amount, _)) in enumerate(ranked, start=1)]
    citations = sorted({ref_idx for _, (_, _, ref_idx) in ranked})

    status = "ok" if len(ranked) >= top_n else "partial"
    return _finalize_answer_payload(
        {
            "status": status,
            "answer": "\n".join(lines),
            "citations": citations,
        },
        query=query,
        kind="money",
    )


def _rule_based_answer(query: str, contexts: Sequence[ChunkRecord]) -> Dict[str, object]:
    if not contexts:
        return {
            "status": "not_found",
            "answer": "문서에 해당 정보가 없습니다.",
            "citations": [],
        }

    kind = _question_kind(query)
    use_factoid_guard = _env_flag("RAG_EXP5_FACTOID_GUARD", default=True)
    # 비교/복합 질의는 규칙 기반 단일 값 추출의 오답 위험이 높아 LLM 요약으로 넘긴다.
    if _is_complex_comparison_query(query):
        return {
            "status": "skip",
            "answer": "",
            "citations": [],
        }
    # generic 질의는 값 탐색형이 아니면 규칙 기반 추출을 시도하지 않는다.
    if kind == "generic" and not _is_value_seeking_query(query):
        return {
            "status": "skip",
            "answer": "",
            "citations": [],
        }
    # 개요/설명형 질의는 규칙 기반 placeholder를 만들지 않고 LLM 생성으로 넘긴다.
    if kind == "overview":
        return {
            "status": "skip",
            "answer": "",
            "citations": [],
        }

    table_candidates: List[Tuple[float, int, str]] = []
    for i, c in enumerate(contexts, start=1):
        for score, value in _extract_table_value_candidates(query, kind, c.text):
            if use_factoid_guard and kind in {"money", "period", "percent", "date"}:
                if not _is_factoid_match_relevant(query, c.text, value, kind):
                    continue
            table_candidates.append((score + 0.8, i, value))
    if table_candidates:
        best_score, best_idx, best_val = max(table_candidates, key=lambda x: x[0])
        if best_score >= 2.2:
            return {
                "status": "ok",
                "answer": f"근거 문구에서 확인된 값은 `{best_val}` 입니다.",
                "citations": [best_idx],
            }

    percent_keywords = ["입찰보증금", "입찰 보증금", "입찰금액", "입찰 금액", "보증금"]
    percent_exclude = ["기술능력", "평가", "배점", "협상적격"]
    percent_candidates: List[Tuple[float, int, str]] = []
    date_candidates: List[Tuple[float, int, str]] = []
    generic_candidates: List[Tuple[float, int, str]] = []

    for i, c in enumerate(contexts, start=1):
        matches = _pick_matches(c.text, kind, query=query)
        if not matches:
            continue

        if kind == "percent":
            text = c.text
            if any(k in text for k in percent_exclude) and not any(k in text for k in percent_keywords):
                continue
            for value in matches:
                if use_factoid_guard and not _is_factoid_match_relevant(query, text, value, kind):
                    continue
                score = _score_factoid_candidate(query, text, value, kind)
                if any(k in text for k in percent_keywords):
                    score += 0.8
                percent_candidates.append((score, i, value))
            continue

        if kind == "date":
            for value in matches:
                if use_factoid_guard and not _is_factoid_match_relevant(query, c.text, value, kind):
                    continue
                score = _score_date_candidate(query, c.text, value) + _score_factoid_candidate(
                    query, c.text, value, kind
                )
                date_candidates.append((score, i, value))
            continue

        for value in matches:
            if use_factoid_guard and kind != "generic":
                if not _is_factoid_match_relevant(query, c.text, value, kind):
                    continue
            score = _score_factoid_candidate(query, c.text, value, kind)
            generic_candidates.append((score, i, value))

    if kind == "date" and date_candidates:
        best_score, best_idx, best_val = max(date_candidates, key=lambda x: x[0])
        if best_score >= 0.0:
            return {
                "status": "ok",
                "answer": f"근거 문구에서 확인된 값은 `{best_val}` 입니다.",
                "citations": [best_idx],
            }

    if kind == "percent" and percent_candidates:
        _, idx, val = max(percent_candidates, key=lambda x: x[0])
        return {
            "status": "ok",
            "answer": f"근거 문구에서 확인된 값은 `{val}` 입니다.",
            "citations": [idx],
        }

    if generic_candidates:
        best_score, best_idx, best_val = max(generic_candidates, key=lambda x: x[0])
        min_score = 1.2 if kind == "generic" else 0.0
        if best_score >= min_score:
            return {
                "status": "ok",
                "answer": f"근거 문구에서 확인된 값은 `{best_val}` 입니다.",
                "citations": [best_idx],
            }

    return {
        "status": "skip",
        "answer": "",
        "citations": [],
    }


def generate_answer(
    query: str,
    contexts: Sequence[ChunkRecord],
    *,
    answer_model: str,
) -> Dict[str, object]:
    kind = _question_kind(query)
    cleaned_contexts = _sanitize_contexts_for_answer(contexts)
    # 사실형 질의는 표/코드블록 신호를 보존한 원문 context에서 규칙 추출을 먼저 수행한다.
    rule_contexts: Sequence[ChunkRecord] = contexts if kind != "overview" else cleaned_contexts
    rule_ans = _rule_based_answer(query, rule_contexts)
    if rule_ans["status"] == "ok":
        return _finalize_answer_payload(rule_ans, query=query, kind=kind)
    if not cleaned_contexts and rule_ans["status"] == "not_found":
        return _finalize_answer_payload(rule_ans, query=query, kind=kind)

    client = _get_client()
    use_structured_complex = _env_flag("RAG_EXP6_STRUCTURED_COMPLEX", default=False)
    is_complex_query = bool(
        re.search(r"(비교|차이|각각|모두|동시에|종합|요약|충족|의무|절차|요구사항)", query)
        and len(query) >= 30
    )

    instruction_parts = [
        "반드시 JSON으로만 답하세요.",
        "키는 status, answer, citations를 사용하세요.",
        "status는 'ok', 'partial', 'not_found' 중 하나만 사용하세요.",
        "정확한 값은 없지만 관련 문맥이 있으면 partial로 답하세요.",
        "근거가 전혀 없으면 answer를 '문서에 해당 정보가 없습니다.'로 반환하세요.",
        "문장 수를 인위적으로 제한하지 말고 핵심 정보만 간결하게 답하세요.",
        "answer는 사용자 안내형 톤으로 작성하세요. 첫 문장은 핵심 결론, 마지막에는 필요 시 한 문장 안내를 덧붙이세요.",
        "answer에 내부 용어(청크/컨텍스트/프롬프트/리트리버)는 사용하지 마세요.",
    ]
    if kind in {"money", "percent", "date", "period", "contact"}:
        instruction_parts.append(
            "사실형 질의에서는 질문의 핵심 값(숫자/기간/비율/연락처)을 답변 첫 문장에 직접 제시하세요."
        )
    if use_structured_complex and is_complex_query:
        instruction_parts.append(
            "복합/비교 질의이므로 answer를 다음 순서로 작성하세요: 1) 문서A 핵심, 2) 문서B 핵심, 3) 차이점 핵심."
        )
        instruction_parts.append(
            "각 섹션은 핵심 1~2항목 위주로 간결하게 작성하고 불필요한 배경 설명은 생략하세요."
        )

    payload = {
        "query": query,
        "contexts": [
            {
                "idx": i + 1,
                "source_path": c.source_path,
                "chunk_index": c.chunk_index,
                "text": c.text[:1800],
            }
            for i, c in enumerate(cleaned_contexts)
        ],
        "instruction": " ".join(instruction_parts),
    }

    response = client.responses.create(
        model=answer_model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}],
            }
        ],
    )
    text = _extract_output_text(response)
    data = _parse_json_object(text)

    status = str(data.get("status", "")).strip().lower()
    answer = str(data.get("answer", "")).strip()
    raw_citations = data.get("citations", [])

    citations: List[int] = []
    if isinstance(raw_citations, list):
        for item in raw_citations:
            try:
                idx = int(item)
            except Exception:
                continue
            if 1 <= idx <= len(cleaned_contexts):
                citations.append(idx)

    if status not in {"ok", "partial", "not_found"}:
        status = "partial" if answer else "not_found"

    if any(answer.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        answer = ""
        status = "not_found"

    if not answer:
        if rule_ans["status"] == "ok":
            return _finalize_answer_payload(rule_ans, query=query, kind=kind)
        answer = "문서에 해당 정보가 없습니다." if status == "not_found" else ""

    if "문서에 해당 정보가 없습니다" in answer:
        if rule_ans["status"] == "ok":
            return _finalize_answer_payload(rule_ans, query=query, kind=kind)
        status = "not_found"
    elif status == "not_found" and rule_ans["status"] == "ok":
        return _finalize_answer_payload(rule_ans, query=query, kind=kind)

    if not citations and rule_ans["status"] == "ok" and rule_ans["citations"]:
        citations = list(rule_ans["citations"])

    return _finalize_answer_payload(
        {
            "status": status,
            "answer": answer,
            "citations": citations,
        },
        query=query,
        kind=kind,
    )


def _expand_candidates_with_neighbors(
    ranked: Sequence[ChunkRecord],
    all_chunks: Sequence[ChunkRecord],
    *,
    target_k: int,
    neighbor_window: int = 1,
) -> List[ChunkRecord]:
    base = list(ranked)
    if not base or target_k <= 0 or neighbor_window <= 0:
        return base[:target_k]

    by_key: Dict[Tuple[str, int], ChunkRecord] = {
        (c.source_path, c.chunk_index): c for c in all_chunks
    }

    out: List[ChunkRecord] = []
    seen: set[Tuple[str, int]] = set()
    for c in base:
        key = (c.source_path, c.chunk_index)
        if key not in seen:
            out.append(c)
            seen.add(key)
        if len(out) >= target_k:
            break
        for delta in range(1, neighbor_window + 1):
            for ni in (c.chunk_index - delta, c.chunk_index + delta):
                nkey = (c.source_path, ni)
                n = by_key.get(nkey)
                if not n or nkey in seen:
                    continue
                out.append(n)
                seen.add(nkey)
                if len(out) >= target_k:
                    break
            if len(out) >= target_k:
                break
    return out[:target_k]


def _run_single_query(
    query: str,
    *,
    retriever,
    chunks_b: Sequence[ChunkRecord],
    top_k: int,
    context_k: int,
    rerank_mode: str,
    llm_model: str,
    answer_model: str,
    generate: bool,
) -> int:
    raw_results = retriever.retrieve(query, chunks_b, k=top_k)
    expanded_raw = _expand_candidates_with_neighbors(
        raw_results,
        chunks_b,
        target_k=max(top_k, min(top_k + 30, top_k * 2)),
        neighbor_window=1,
    )
    reranked, _ = _rerank(query, expanded_raw, rerank_mode=rerank_mode, llm_model=llm_model)
    contexts = _expand_contexts_with_neighbors(reranked, chunks_b, context_k=context_k, neighbor_window=1)
    print(f"query: {query}")
    if generate:
        ans = generate_answer(query, contexts, answer_model=answer_model)
        print(f"status: {ans['status']}")
        print(f"answer: {ans['answer']}")
        print("citations:")
        for idx in ans["citations"]:
            c = contexts[idx - 1]
            print(f"- [{idx}] {c.source_path} (chunk {c.chunk_index})")

        if not ans["citations"] and contexts:
            print("retrieved contexts:")
            for i, c in enumerate(contexts, start=1):
                preview = re.sub(r"\s+", " ", c.text).strip()[:180]
                print(f"- [{i}] {c.source_path} (chunk {c.chunk_index}) :: {preview}...")
    else:
        print("retrieved contexts:")
        for i, c in enumerate(contexts, start=1):
            preview = re.sub(r"\s+", " ", c.text).strip()[:180]
            print(f"- [{i}] {c.source_path} (chunk {c.chunk_index}) :: {preview}...")

    return 0


def _run_batch(
    query_path: Path,
    *,
    retriever,
    chunks_b: Sequence[ChunkRecord],
    top_k: int,
    context_k: int,
    rerank_mode: str,
    llm_model: str,
    answer_model: str,
    generate: bool,
    output_csv: Path,
) -> int:
    queries: List[QueryRecord] = load_queries(query_path)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    for q in queries:
        raw_results = retriever.retrieve(q.query, chunks_b, k=top_k)
        expanded_raw = _expand_candidates_with_neighbors(
            raw_results,
            chunks_b,
            target_k=max(top_k, min(top_k + 30, top_k * 2)),
            neighbor_window=1,
        )
        reranked, cost_usd = _rerank(
            q.query, expanded_raw, rerank_mode=rerank_mode, llm_model=llm_model
        )
        metrics_retrieve = evaluate_query(q, raw_results)
        metrics_rerank = evaluate_query(q, reranked)
        gold_sources = {src for src, _ in q.gold}
        retrieve_sources = [item.source_path for item in raw_results[:10]]
        rerank_sources = [item.source_path for item in reranked[:10]]
        retrieve_source_recall10 = (
            len(set(retrieve_sources) & gold_sources) / len(gold_sources) if gold_sources else 0.0
        )
        rerank_source_recall10 = (
            len(set(rerank_sources) & gold_sources) / len(gold_sources) if gold_sources else 0.0
        )

        answer_status = "skipped"
        answer = ""
        citations_json = "[]"
        if generate:
            contexts = _expand_contexts_with_neighbors(
                reranked, chunks_b, context_k=context_k, neighbor_window=1
            )
            ans = generate_answer(q.query, contexts, answer_model=answer_model)
            answer_status = str(ans["status"])
            answer = str(ans["answer"])
            citations_json = json.dumps(ans.get("citations", []), ensure_ascii=False)

        top1 = reranked[0] if reranked else None
        rows.append(
            {
                "query_id": q.query_id,
                "query": q.query,
                "retrieve_recall@10": metrics_retrieve["recall@10"],
                "rerank_recall@10": metrics_rerank["recall@10"],
                "retrieve_source_recall@10": retrieve_source_recall10,
                "rerank_source_recall@10": rerank_source_recall10,
                "retrieve_mrr": metrics_retrieve["mrr"],
                "rerank_mrr": metrics_rerank["mrr"],
                "answer_status": answer_status,
                "answer": answer,
                "citations": citations_json,
                "has_citation": int(citations_json != "[]"),
                "top1_source_path": top1.source_path if top1 else "",
                "top1_chunk_index": top1.chunk_index if top1 else "",
                "cost_usd": cost_usd,
            }
        )

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "query_id",
                "query",
                "retrieve_recall@10",
                "rerank_recall@10",
                "retrieve_source_recall@10",
                "rerank_source_recall@10",
                "retrieve_mrr",
                "rerank_mrr",
                "answer_status",
                "answer",
                "citations",
                "has_citation",
                "top1_source_path",
                "top1_chunk_index",
                "cost_usd",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    n = max(len(rows), 1)
    avg_ret = sum(float(r["retrieve_recall@10"]) for r in rows) / n
    avg_rer = sum(float(r["rerank_recall@10"]) for r in rows) / n
    avg_ret_src = sum(float(r["retrieve_source_recall@10"]) for r in rows) / n
    avg_rer_src = sum(float(r["rerank_source_recall@10"]) for r in rows) / n
    avg_ret_mrr = sum(float(r["retrieve_mrr"]) for r in rows) / n
    avg_rer_mrr = sum(float(r["rerank_mrr"]) for r in rows) / n
    not_found = sum(1 for r in rows if r["answer_status"] == "not_found") if generate else 0

    print(f"NODE SUMMARY | queries={len(rows)}")
    print(f"retrieve_recall@10={avg_ret:.6f}")
    print(f"rerank_recall@10={avg_rer:.6f}")
    print(f"retrieve_source_recall@10={avg_ret_src:.6f}")
    print(f"rerank_source_recall@10={avg_rer_src:.6f}")
    print(f"retrieve_mrr={avg_ret_mrr:.6f}")
    print(f"rerank_mrr={avg_rer_mrr:.6f}")
    if generate:
        print(f"answer_not_found={not_found} / {len(rows)}")
    print(f"output={output_csv}")
    return 0


def _expand_contexts_with_neighbors(
    ranked: Sequence[ChunkRecord],
    all_chunks: Sequence[ChunkRecord],
    *,
    context_k: int,
    neighbor_window: int = 1,
) -> List[ChunkRecord]:
    base = list(ranked[:context_k])
    if not base or context_k <= 0 or neighbor_window <= 0:
        return base

    by_key: Dict[Tuple[str, int], ChunkRecord] = {
        (c.source_path, c.chunk_index): c for c in all_chunks
    }
    out: List[ChunkRecord] = []
    seen: set[Tuple[str, int]] = set()

    for c in base:
        key = (c.source_path, c.chunk_index)
        if key not in seen:
            out.append(c)
            seen.add(key)
        if len(out) >= context_k:
            break

        for delta in range(1, neighbor_window + 1):
            for neighbor_idx in (c.chunk_index - delta, c.chunk_index + delta):
                nkey = (c.source_path, neighbor_idx)
                n = by_key.get(nkey)
                if not n or nkey in seen:
                    continue
                out.append(n)
                seen.add(nkey)
                if len(out) >= context_k:
                    break
            if len(out) >= context_k:
                break

    return out[:context_k]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--query-file", default="")
    parser.add_argument("--retriever", choices=["tfidf", "dense", "hybrid", "chroma"], default="hybrid")
    parser.add_argument("--rerank", choices=["none", "rule", "llm"], default="none")
    parser.add_argument("--llm-model", default="gpt-5-nano")
    parser.add_argument("--answer-model", default="gpt-5-nano")
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--context-k", type=int, default=20)
    parser.add_argument("--hybrid-alpha", type=float, default=1.0)
    parser.add_argument("--table-multiplier", type=float, default=1.0)
    parser.add_argument("--dense-index-b", default=str(Path("data_index") / "dense_B"))
    parser.add_argument("--chroma-persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--chroma-collection", default="rfp_b_oai")
    parser.add_argument("--chroma-model", default="text-embedding-3-small")
    parser.add_argument("--chroma-org-filter", action="store_true")
    parser.add_argument("--chroma-org-filter-mode", choices=["hard", "soft", "adaptive"], default="hard")
    parser.add_argument("--chroma-score-weight", type=float, default=0.7)
    parser.add_argument("--lexical-score-weight", type=float, default=0.3)
    parser.add_argument("--chroma-noise-mode", choices=["off", "soft", "hard"], default="soft")
    parser.add_argument("--chroma-mmr", action="store_true")
    parser.add_argument("--chroma-mmr-lambda", type=float, default=0.85)
    parser.add_argument("--chroma-query-rewrite", action="store_true")
    parser.add_argument(
        "--joined-chunks",
        default=str(Path("notebooks") / "data_chunks_rich_joined.jsonl"),
    )
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output-csv", default="")
    args = parser.parse_args()

    if not args.query and not args.query_file:
        raise RuntimeError("--query 또는 --query-file 중 하나는 필요합니다.")

    chunks_b = _load_chunks_b(Path(args.joined_chunks))
    retriever = _build_retriever(
        retriever_kind=args.retriever,
        chunks_b=chunks_b,
        dense_index_b=Path(args.dense_index_b),
        hybrid_alpha=args.hybrid_alpha,
        table_multiplier=args.table_multiplier,
        chroma_persist_dir=Path(args.chroma_persist_dir),
        chroma_collection=args.chroma_collection,
        chroma_model=args.chroma_model,
        chroma_org_filter=bool(args.chroma_org_filter),
        chroma_org_filter_mode=str(args.chroma_org_filter_mode),
        chroma_score_weight=float(args.chroma_score_weight),
        lexical_score_weight=float(args.lexical_score_weight),
        chroma_noise_mode=str(args.chroma_noise_mode),
        chroma_mmr=bool(args.chroma_mmr),
        chroma_mmr_lambda=float(args.chroma_mmr_lambda),
        chroma_query_rewrite=bool(args.chroma_query_rewrite),
    )

    if args.query:
        return _run_single_query(
            args.query,
            retriever=retriever,
            chunks_b=chunks_b,
            top_k=args.topk,
            context_k=args.context_k,
            rerank_mode=args.rerank,
            llm_model=args.llm_model,
            answer_model=args.answer_model,
            generate=bool(args.generate),
        )

    output_csv = (
        Path(args.output_csv)
        if args.output_csv
        else Path("results") / f"node_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    return _run_batch(
        Path(args.query_file),
        retriever=retriever,
        chunks_b=chunks_b,
        top_k=args.topk,
        context_k=args.context_k,
        rerank_mode=args.rerank,
        llm_model=args.llm_model,
        answer_model=args.answer_model,
        generate=bool(args.generate),
        output_csv=output_csv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
