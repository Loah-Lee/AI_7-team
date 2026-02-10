import json
from pathlib import Path

import pandas as pd
import streamlit as st


RUNS_DIR = Path("/Users/apple/AI_7-team/notebooks/runs")
RICH_CHUNKS_DIR = Path("/Users/apple/AI_7-team/notebooks/data_chunks_rich")
RICH_MD_DIR = Path("/Users/apple/AI_7-team/notebooks/data_rich")


@st.cache_data(show_spinner=False)
def _list_runs() -> list[Path]:
    return sorted(RUNS_DIR.glob("*"))


def _load_latest_results() -> Path | None:
    runs = _list_runs()
    if not runs:
        return None
    latest = runs[-1]
    path = latest / "results.csv"
    return path if path.exists() else None


@st.cache_data(show_spinner=False)
def _list_md_files() -> list[Path]:
    return sorted(RICH_MD_DIR.glob("*.md"))


@st.cache_data(show_spinner=False)
def _load_doc_chunks(md_name: str) -> list[dict]:
    chunk_path = RICH_CHUNKS_DIR / f"{md_name}.jsonl"
    if not chunk_path.exists():
        return []
    items = []
    with chunk_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            items.append(json.loads(line))
    return items


@st.cache_data(show_spinner=False)
def _load_chunk_counts() -> pd.DataFrame:
    rows = []
    for path in sorted(RICH_CHUNKS_DIR.rglob("*.jsonl")):
        try:
            count = sum(1 for _ in path.open("r", encoding="utf-8"))
        except Exception:
            count = 0
        rows.append({"doc": path.stem.replace(".md", ""), "chunks": count})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_chunks() -> dict:
    chunks = {}
    for path in RICH_CHUNKS_DIR.rglob("*.jsonl"):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                cid = row.get("chunk_id")
                if cid and cid not in chunks:
                    chunks[cid] = row
    return chunks


@st.cache_data(show_spinner=False)
def _load_md_assets() -> dict:
    assets = {}
    for path in RICH_MD_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        imgs = []
        for line in text.splitlines():
            if "data_assets" in line and "](" in line and ")" in line:
                start = line.find("](") + 2
                end = line.rfind(")")
                if start > 1 and end > start:
                    ref = line[start:end]
                    if ref:
                        imgs.append(ref)
        assets[path.name] = imgs
    return assets


def _extract_table_snippet(md_path: Path) -> str | None:
    if not md_path.exists():
        return None
    lines = md_path.read_text(encoding="utf-8").splitlines()
    block = []
    for line in lines:
        if "|" in line:
            block.append(line)
        elif block:
            break
    if not block:
        return None
    return "\n".join(block[:10])


@st.cache_data(show_spinner=False)
def _load_gold_map() -> dict:
    gold_path = Path("/Users/apple/AI_7-team/configs/eval_queries_v2_rich.jsonl")
    gold_map = {}
    if not gold_path.exists():
        return gold_map
    with gold_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            gold_map[item.get("query_id")] = item.get("gold", [])
    return gold_map


def _resolve_image(md_path: Path, ref: str) -> Path:
    candidate = (md_path.parent / ref).resolve()
    if candidate.exists():
        return candidate

    # fallback: try to resolve by matching data_assets dir name (handles trailing spaces)
    try:
        ref_path = Path(ref)
        parts = ref_path.parts
        if "data_assets" in parts:
            idx = parts.index("data_assets")
            rel_parts = parts[idx + 1 :]
            if len(rel_parts) >= 2:
                doc_id = rel_parts[0]
                rest = rel_parts[1:]
                assets_root = (RICH_MD_DIR.parent / "data_assets").resolve()
                target_dir = None
                for d in assets_root.iterdir():
                    if not d.is_dir():
                        continue
                    if d.name == doc_id or d.name.strip() == doc_id.strip():
                        target_dir = d
                        break
                if target_dir:
                    alt = target_dir.joinpath(*rest)
                    if alt.exists():
                        return alt
    except Exception:
        pass

    return candidate


st.set_page_config(page_title="RAG Eval Inspector", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    h1, h2, h3 { font-family: 'IBM Plex Sans', sans-serif; }
    .pill { display: inline-block; padding: 2px 10px; border-radius: 999px; background: #e8eef8; margin-left: 8px; font-size: 12px; }
    .card { border: 1px solid #e6e6e6; border-radius: 10px; padding: 14px; background: #fafafa; }
    .muted { color: #6b7280; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("RAG 평가 점검 대시보드")

results_path = _load_latest_results()
if not results_path:
    st.warning("results.csv를 찾을 수 없습니다. 데이터 탐색 모드로 전환합니다.")
    st.subheader("데이터 탐색")
    md_files = _list_md_files()
    if not md_files:
        st.error("data_rich에 md 파일이 없습니다.")
        st.stop()

    st.markdown("**문서별 청크 수**")
    counts = _load_chunk_counts()
    page_size = 20
    max_page = max((len(counts) - 1) // page_size, 0)
    page = st.number_input("페이지", min_value=0, max_value=max_page, value=0, step=1)
    start = page * page_size
    end = start + page_size
    st.dataframe(counts.iloc[start:end], use_container_width=True, height=460)

    md_names = [p.name for p in md_files]
    selected_md = st.selectbox("문서 선택", md_names, index=0)
    md_path = RICH_MD_DIR / selected_md

    st.markdown("**본문 미리보기**")
    try:
        md_text = md_path.read_text(encoding="utf-8")
        st.text_area(
            "본문",
            md_text[:1500] or "(본문 없음)",
            height=200,
            label_visibility="collapsed",
        )
    except Exception as exc:
        st.error(f"md 읽기 실패: {exc}")

    table_snippet = _extract_table_snippet(md_path)
    if table_snippet:
        st.markdown("**표 샘플**")
        st.code(table_snippet)

    st.markdown("**이미지 썸네일**")
    assets = _load_md_assets()
    imgs = assets.get(selected_md, [])
    if imgs:
        cols = st.columns(3)
        for i, img in enumerate(imgs[:6]):
            img_path = _resolve_image(md_path, img)
            cols[i % 3].image(str(img_path), width=220)
    else:
        st.caption("이미지 없음")

    st.markdown("**청크 미리보기**")
    chunks = _load_doc_chunks(selected_md)
    st.caption(f"총 청크 수: {len(chunks)}")
    if chunks:
        idx = st.number_input("청크 인덱스", min_value=0, max_value=len(chunks) - 1, value=0)
        st.text_area(
            "청크",
            chunks[idx].get("text", "")[:1500] or "(청크 텍스트 없음)",
            height=220,
            label_visibility="collapsed",
        )
        meta = chunks[idx].get("metadata", {})
        if meta:
            st.json(meta)
    st.stop()

with st.sidebar:
    st.header("설정")
    runs = _list_runs()
    run_labels = [p.name for p in runs]
    selected = st.selectbox("결과 폴더", run_labels, index=len(run_labels) - 1)
    results_path = Path("/Users/apple/AI_7-team/notebooks/runs") / selected / "results.csv"
    st.caption(f"파일: {results_path}")
    min_qual = st.slider("최소 qual_score_top1", 0.0, 2.0, 0.0, 0.1)
    query_filter = st.text_input("쿼리 검색")

df = pd.read_csv(results_path)
if "qual_score_top1" in df.columns:
    df["qual_score_top1"] = pd.to_numeric(df["qual_score_top1"], errors="coerce").fillna(0.0)

if min_qual > 0:
    df = df[df["qual_score_top1"] >= min_qual]
if query_filter:
    df = df[df["query"].str.contains(query_filter, na=False)]

st.subheader("평가 요약")
metric_cols = ["hit@5", "hit@10", "mrr", "latency_ms", "cost_usd"]
summary = {c: df[c].astype(float).mean() for c in metric_cols if c in df.columns}
summary["qual_score_top1_avg"] = df["qual_score_top1"].astype(float).mean()
cols = st.columns(3)
cols[0].metric("QUAL 평균", f"{summary['qual_score_top1_avg']:.3f}")
cols[1].metric("MRR 평균", f"{summary.get('mrr', 0.0):.3f}")
cols[2].metric("Hit@10 평균", f"{summary.get('hit@10', 0.0):.3f}")
with st.expander("요약 상세"):
    st.json(summary)

st.dataframe(
    df[["query_id", "query", "qual_score_top1", "qual_reason_top1", "top1_source_path"]],
    use_container_width=True,
)

chunks = _load_chunks()
assets = _load_md_assets()
gold_map = _load_gold_map()

st.subheader("쿼리별 상세")
for _, row in df.iterrows():
    qid = row.get("query_id")
    query = row.get("query")
    qual = row.get("qual_score_top1")
    reason = row.get("qual_reason_top1")
    header = f"{qid} | {query}"
    with st.expander(header, expanded=False):
        st.markdown(f"<span class='pill'>qual={qual} / {reason}</span>", unsafe_allow_html=True)

        top1_id = row.get("top1_chunk_id")
        top1 = chunks.get(top1_id)
        top1_text = (top1.get("text") if top1 else "")[:800]
        top1_source = row.get("top1_source_path")
        top1_idx = row.get("top1_chunk_index")

        left, right = st.columns([2, 1])
        with left:
            st.markdown("**Top1**")
            st.write(f"source: {top1_source} (chunk {top1_idx})")
            st.text_area(
                "Top1",
                top1_text or "(top1 텍스트 없음)",
                height=220,
                label_visibility="collapsed",
            )

            gold_list = gold_map.get(qid, [])
            if gold_list:
                g = gold_list[0]
                gold_source = g.get("source_path")
                gold_id = g.get("chunk_id")
                gold_row = chunks.get(gold_id, {})
                gold_text = (gold_row.get("text") or "")[:800]
                st.markdown("**Top2 (gold 기반 대체)**")
                st.write(f"source: {gold_source} (chunk {g.get('chunk_index')})")
                st.text_area(
                    "Top2 (gold)",
                    gold_text or "(gold 텍스트 없음)",
                    height=220,
                    label_visibility="collapsed",
                )
            else:
                st.markdown("**Top2 (gold 기반 대체)**")
                st.caption("gold 없음")

            st.markdown("**Gold 매칭 목록**")
            if gold_list:
                gold_df = pd.DataFrame(gold_list)
                st.dataframe(gold_df, use_container_width=True)
            else:
                st.caption("gold 없음")

        with right:
            st.markdown("**원본 경로**")
            st.code(top1_source or "")
            if top1_source:
                md_path = RICH_MD_DIR / top1_source
                table_snippet = _extract_table_snippet(md_path)
                if table_snippet:
                    st.markdown("**표 샘플**")
                    st.code(table_snippet)
            st.markdown("**이미지 썸네일**")
            if top1_source and top1_source in assets:
                cols = st.columns(3)
                for i, img in enumerate(assets[top1_source][:6]):
                    img_path = _resolve_image(RICH_MD_DIR / top1_source, img)
                    cols[i % 3].image(str(img_path), width=220)
            else:
                st.caption("이미지 없음")
