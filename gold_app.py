from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st


ROOT = Path("/Users/apple/AI_7-team")
EVAL_PATH = ROOT / "configs" / "eval_queries_v2_rich.jsonl"
CHUNKS_DIR = ROOT / "notebooks" / "data_chunks_rich"


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", text.lower())


def _overlap_score(query: str, text: str) -> Tuple[int, float]:
    q = set(_tokenize(query))
    t = set(_tokenize(text))
    if not q:
        return 0, 0.0
    hit = len(q & t)
    return hit, hit / len(q)


def _preview(text: str, max_len: int = 1000) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _infer_query_type(query: str) -> str:
    q = query.strip()
    if re.search(r"비율|퍼센트|%", q):
        return "percent"
    if re.search(r"예산|금액|비용|얼마", q):
        return "money"
    if re.search(r"마감|일자|언제|날짜", q):
        return "date"
    if re.search(r"기간|몇\s*개월|며칠", q):
        return "period"
    if re.search(r"문의처|연락처|전화", q):
        return "contact"
    return "generic"


def _answer_signals(text: str) -> Dict[str, bool]:
    return {
        "percent": bool(re.search(r"\d+\s*%|\d+\s*분의\s*\d+", text)),
        "money": bool(re.search(r"\d[\d,]*(?:\.\d+)?\s*(원|만원|천원|억원)", text)),
        "date": bool(re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일", text)),
        "period": bool(re.search(r"\d+\s*(개월|일|년)", text)),
        "contact": bool(re.search(r"전화|문의|연락|메일|이메일|@|전화번호|번호", text)),
    }


@st.cache_data(show_spinner=False)
def load_queries(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    return list(_iter_jsonl(path))


@st.cache_data(show_spinner=False)
def load_chunk_maps(chunks_dir: Path) -> Tuple[Dict[Tuple[str, int], Dict[str, object]], Dict[str, Dict[str, object]]]:
    by_pair: Dict[Tuple[str, int], Dict[str, object]] = {}
    by_chunk_id: Dict[str, Dict[str, object]] = {}
    if not chunks_dir.exists():
        return by_pair, by_chunk_id

    for path in sorted(chunks_dir.rglob("*.jsonl")):
        for row in _iter_jsonl(path):
            source_path = str(row.get("source_path", ""))
            try:
                chunk_index = int(row.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            chunk_id = str(row.get("chunk_id", "")).strip()
            if source_path and chunk_index >= 0:
                by_pair[(source_path, chunk_index)] = row
            if chunk_id:
                by_chunk_id[chunk_id] = row
    return by_pair, by_chunk_id


def build_summary(
    queries: List[Dict[str, object]],
    by_pair: Dict[Tuple[str, int], Dict[str, object]],
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for q in queries:
        query_id = str(q.get("query_id", ""))
        query = str(q.get("query", ""))
        gold = q.get("gold", [])
        gold_items = gold if isinstance(gold, list) else []
        missing = 0
        for g in gold_items:
            if not isinstance(g, dict):
                missing += 1
                continue
            source_path = str(g.get("source_path", ""))
            try:
                chunk_index = int(g.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            if (source_path, chunk_index) not in by_pair:
                missing += 1
        rows.append(
            {
                "query_id": query_id,
                "query": query,
                "gold_count": len(gold_items),
                "missing_gold_chunks": missing,
                "status": "OK" if missing == 0 else "MISSING",
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(page_title="Gold Inspector", layout="wide")
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.6rem; padding-bottom: 2rem; }
      .card {
        border: 1px solid #d7dde7;
        border-radius: 12px;
        padding: 12px 14px;
        background: linear-gradient(180deg, #f9fbff 0%, #f4f7fb 100%);
        margin-bottom: 10px;
      }
      .ok { color: #0f7b6c; font-weight: 700; }
      .bad { color: #b42318; font-weight: 700; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Gold Inspector (gold_app)")
st.caption("eval 쿼리와 gold 정답 청크 매칭(존재/정합/텍스트 근거) 점검 도구")

queries = load_queries(EVAL_PATH)
by_pair, by_chunk_id = load_chunk_maps(CHUNKS_DIR)
summary = build_summary(queries, by_pair)

if not queries:
    st.error(f"평가 파일이 없거나 비어 있습니다: {EVAL_PATH}")
    st.stop()

with st.sidebar:
    st.header("필터")
    only_missing = st.checkbox("MISSING만 보기", value=False)
    q_filter = st.text_input("query_id / query 검색")
    qids = summary["query_id"].tolist()
    selected_qid = st.selectbox("쿼리 선택", qids, index=0 if qids else None)
    st.caption(f"eval: {EVAL_PATH}")
    st.caption(f"chunks: {CHUNKS_DIR}")

total_queries = len(summary)
total_gold = int(summary["gold_count"].sum())
total_missing = int(summary["missing_gold_chunks"].sum())
col1, col2, col3 = st.columns(3)
col1.metric("총 쿼리", total_queries)
col2.metric("총 gold 항목", total_gold)
col3.metric("누락 gold 청크", total_missing)

view = summary.copy()
if only_missing:
    view = view[view["missing_gold_chunks"] > 0]
if q_filter:
    view = view[
        view["query_id"].str.contains(q_filter, na=False)
        | view["query"].str.contains(q_filter, na=False)
    ]

st.subheader("쿼리 요약")
st.dataframe(view, use_container_width=True, height=260)

selected = next((q for q in queries if str(q.get("query_id", "")) == selected_qid), None)
if not selected:
    st.warning("선택한 쿼리를 찾을 수 없습니다.")
    st.stop()

query_text = str(selected.get("query", ""))
query_type = _infer_query_type(query_text)
gold_list = selected.get("gold", [])
gold_items = gold_list if isinstance(gold_list, list) else []

st.subheader("선택 쿼리")
st.markdown(f"**query_id**: `{selected_qid}`")
st.markdown(f"**query**: {query_text}")
st.markdown(f"**query_type 추정**: `{query_type}`")

st.subheader("Gold 상세")
if not gold_items:
    st.error("이 쿼리의 gold가 비어 있습니다.")
    st.stop()

for i, g in enumerate(gold_items, start=1):
    if not isinstance(g, dict):
        st.error(f"[{i}] gold 형식 오류: dict 아님")
        continue

    source_path = str(g.get("source_path", ""))
    try:
        chunk_index = int(g.get("chunk_index", -1))
    except Exception:
        chunk_index = -1
    expected_chunk_id = str(g.get("chunk_id", "")).strip()
    reason = str(g.get("reason", ""))

    found = by_pair.get((source_path, chunk_index))
    status = "OK" if found else "MISSING"
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown(f"**[{i}] status**: <span class='{'ok' if found else 'bad'}'>{status}</span>", unsafe_allow_html=True)
    st.markdown(f"**source_path**: `{source_path}`")
    st.markdown(f"**chunk_index**: `{chunk_index}`")
    st.markdown(f"**reason**: `{reason}`")

    if not found:
        if expected_chunk_id:
            fallback = by_chunk_id.get(expected_chunk_id)
            if fallback:
                st.warning("pair로는 못 찾았지만 chunk_id로는 찾았습니다. source/index 불일치 가능성 있음.")
                st.markdown(f"fallback source: `{fallback.get('source_path', '')}`")
                st.markdown(f"fallback chunk_index: `{fallback.get('chunk_index', '')}`")
            else:
                st.error("해당 gold 청크를 chunks에서 찾지 못했습니다.")
        else:
            st.error("해당 gold 청크를 chunks에서 찾지 못했습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        continue

    actual_chunk_id = str(found.get("chunk_id", "")).strip()
    chunk_id_ok = expected_chunk_id == actual_chunk_id if expected_chunk_id else True
    st.markdown(
        f"**chunk_id 일치**: <span class='{'ok' if chunk_id_ok else 'bad'}'>{chunk_id_ok}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"expected: `{expected_chunk_id}`")
    st.markdown(f"actual: `{actual_chunk_id}`")

    text = str(found.get("text", ""))
    hit, ratio = _overlap_score(query_text, text)
    signals = _answer_signals(text)
    expected_hit = signals.get(query_type, False) if query_type in signals else False
    st.markdown(f"**query-token overlap**: `{hit}` (`{ratio:.2f}`)")
    st.markdown(
        f"**expected signal({query_type})**: "
        f"<span class='{'ok' if expected_hit else 'bad'}'>{expected_hit}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "**signal map**: "
        + ", ".join([f"`{k}={v}`" for k, v in signals.items()])
    )
    st.text_area(f"gold text preview #{i}", _preview(text), height=170, key=f"gold-{selected_qid}-{i}")

    st.markdown("</div>", unsafe_allow_html=True)
