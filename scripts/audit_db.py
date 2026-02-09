"""ChromaDB 품질 감사 스크립트.

Before/After 비교를 위한 DB 통계를 수집한다.

실행:
    uv run python scripts/audit_db.py
    uv run python scripts/audit_db.py --label before
    uv run python scripts/audit_db.py --label after
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.utils.config import load_config

# 감사 패턴
_BULLET_CHARS_RE = re.compile(r"[○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ]")
# 라인 시작 불릿 (클리닝 대상)
_LINE_BULLET_RE = re.compile(
    r"^(\s*)[○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ]\s*", re.MULTILINE
)
_BACKTICK_BULLET_RE = re.compile(
    r"^(\s*)`[○□❍❏◎◇▶▷►●■★☆◆▪▸ｏ]`\s*", re.MULTILINE
)
_BOLD_MD_RE = re.compile(r"\*\*.+?\*\*")
_HEADING_MD_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def audit(persist_dir: str, collection_name: str, label: str = "") -> dict:
    """ChromaDB 컬렉션을 감사하여 통계를 반환한다."""
    from langchain_chroma import Chroma
    from src.retrievers.embeddings import get_embeddings

    embeddings = get_embeddings()
    vectorstore = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )

    collection = vectorstore._collection
    total = collection.count()

    if total == 0:
        print(f"[{label}] DB가 비어 있습니다.")
        return {}

    # 전체 문서 가져오기
    result = collection.get(include=["documents", "metadatas"])
    documents = result["documents"]
    metadatas = result["metadatas"]

    # 통계 수집
    lengths = [len(doc) for doc in documents]
    avg_len = sum(lengths) / len(lengths) if lengths else 0
    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0

    # 짧은 청크 수
    short_chunks_lt80 = sum(1 for l in lengths if l < 80)
    short_chunks_lt120 = sum(1 for l in lengths if l < 120)
    short_chunks_lt200 = sum(1 for l in lengths if l < 200)

    # 불릿 기호 포함 청크 수 (전체 — 인라인 포함)
    bullet_chunks = sum(1 for doc in documents if _BULLET_CHARS_RE.search(doc))
    # 라인 시작 불릿 (클리닝 대상)
    line_bullet_chunks = sum(
        1 for doc in documents
        if _LINE_BULLET_RE.search(doc) or _BACKTICK_BULLET_RE.search(doc)
    )

    # Bold markdown 포함 청크 수
    bold_chunks = sum(1 for doc in documents if _BOLD_MD_RE.search(doc))

    # Heading markdown 포함 청크 수
    heading_chunks = sum(1 for doc in documents if _HEADING_MD_RE.search(doc))

    # 소스 파일 수
    sources = set()
    for meta in metadatas:
        src = meta.get("source", "")
        if src:
            sources.add(src)

    # section 메타데이터 비어있는 비율
    empty_section = sum(1 for meta in metadatas if not meta.get("section"))
    empty_section_pct = (empty_section / total * 100) if total > 0 else 0

    # 테이블 구문 포함 청크 수
    table_chunks = sum(1 for doc in documents if "|" in doc and "---" in doc)

    # ── PDF 전용 통계 ──
    pdf_docs = [(doc, meta) for doc, meta in zip(documents, metadatas)
                if meta.get("file_type") == "pdf"]
    hwp_docs = [(doc, meta) for doc, meta in zip(documents, metadatas)
                if meta.get("file_type") == "hwp"]

    pdf_total = len(pdf_docs)
    hwp_total = len(hwp_docs)

    pdf_lengths = [len(d) for d, _ in pdf_docs]
    pdf_avg_len = sum(pdf_lengths) / len(pdf_lengths) if pdf_lengths else 0
    pdf_table_chunks = sum(1 for d, _ in pdf_docs if "|" in d and "---" in d)
    pdf_table_pct = (pdf_table_chunks / pdf_total * 100) if pdf_total else 0
    pdf_short_lt200 = sum(1 for l in pdf_lengths if l < 200)
    pdf_short_lt200_pct = (pdf_short_lt200 / pdf_total * 100) if pdf_total else 0

    # is_form 태그된 청크 수
    form_chunks = sum(1 for meta in metadatas if meta.get("is_form"))
    is_toc_chunks = sum(1 for meta in metadatas if meta.get("is_toc"))

    # 중복 탐지: source별 첫 200자 해시 중복 수
    from collections import Counter
    import hashlib as _hl
    source_prefix_counts: dict[str, Counter] = {}
    for doc, meta in zip(documents, metadatas):
        src = meta.get("source", "")
        prefix = doc.strip()[:200]
        h = _hl.md5(prefix.encode()).hexdigest()
        if src not in source_prefix_counts:
            source_prefix_counts[src] = Counter()
        source_prefix_counts[src][h] += 1
    total_duplicates = sum(
        count - 1
        for counter in source_prefix_counts.values()
        for count in counter.values()
        if count > 1
    )

    stats = {
        "label": label,
        "total_chunks": total,
        "source_files": len(sources),
        "avg_length": round(avg_len, 1),
        "min_length": min_len,
        "max_length": max_len,
        "short_chunks_lt80": short_chunks_lt80,
        "short_chunks_lt120": short_chunks_lt120,
        "short_chunks_lt200": short_chunks_lt200,
        "bullet_chunks": bullet_chunks,
        "bullet_pct": round(bullet_chunks / total * 100, 1) if total > 0 else 0,
        "line_bullet_chunks": line_bullet_chunks,
        "bold_chunks": bold_chunks,
        "bold_pct": round(bold_chunks / total * 100, 1) if total > 0 else 0,
        "heading_chunks": heading_chunks,
        "empty_section": empty_section,
        "empty_section_pct": round(empty_section_pct, 1),
        "table_chunks": table_chunks,
        # PDF 전용
        "pdf_total": pdf_total,
        "hwp_total": hwp_total,
        "pdf_avg_length": round(pdf_avg_len, 1),
        "pdf_table_chunks": pdf_table_chunks,
        "pdf_table_pct": round(pdf_table_pct, 1),
        "pdf_short_lt200": pdf_short_lt200,
        "pdf_short_lt200_pct": round(pdf_short_lt200_pct, 1),
        "form_chunks": form_chunks,
        "toc_chunks": is_toc_chunks,
        "duplicate_chunks": total_duplicates,
    }

    # 출력
    tag = f"[{label}] " if label else ""
    print(f"\n{'='*60}")
    print(f"{tag}ChromaDB 품질 감사 결과")
    print(f"{'='*60}")
    print(f"  총 청크 수:           {total:,}")
    print(f"  소스 파일 수:         {len(sources)}")
    print(f"  평균 청크 길이:       {avg_len:.1f}자")
    print(f"  최소/최대 길이:       {min_len} / {max_len}")
    print(f"  짧은 청크 (<80):      {short_chunks_lt80}")
    print(f"  짧은 청크 (<120):     {short_chunks_lt120}")
    print(f"  짧은 청크 (<200):     {short_chunks_lt200}")
    print(f"  불릿 기호 포함(전체): {stats['bullet_chunks']} ({stats['bullet_pct']}%)")
    print(f"  라인시작 불릿(노이즈):{line_bullet_chunks}")
    print(f"  Bold markdown:        {stats['bold_chunks']} ({stats['bold_pct']}%)")
    print(f"  Heading markdown:     {stats['heading_chunks']}")
    print(f"  section 비어있음:     {empty_section} ({empty_section_pct:.1f}%)")
    print(f"  테이블 구문 포함:     {table_chunks}")
    print(f"  is_toc 태그:          {is_toc_chunks}")
    print(f"  is_form 태그:         {form_chunks}")
    print(f"  중복 청크(source별):  {total_duplicates}")
    print()
    print(f"  ── PDF 전용 ──")
    print(f"  PDF 청크 수:          {pdf_total}")
    print(f"  PDF 평균 길이:        {pdf_avg_len:.1f}자")
    print(f"  PDF 테이블 청크:      {pdf_table_chunks} ({pdf_table_pct:.1f}%)")
    print(f"  PDF 200자 미만:       {pdf_short_lt200} ({pdf_short_lt200_pct:.1f}%)")
    print(f"  HWP 청크 수:          {hwp_total}")
    print(f"{'='*60}")

    # 샘플 청크 10개 출력
    print(f"\n{tag}샘플 청크 (처음 10개):")
    print("-" * 60)
    for i, doc in enumerate(documents[:10]):
        preview = doc[:120].replace("\n", "\\n")
        src = metadatas[i].get("source", "?")
        section = metadatas[i].get("section", "")
        ft = metadatas[i].get("file_type", "?")
        flags = []
        if metadatas[i].get("is_toc"):
            flags.append("TOC")
        if metadatas[i].get("is_form"):
            flags.append("FORM")
        flag_str = f" [{','.join(flags)}]" if flags else ""
        print(f"  [{i+1}] len={len(doc)} type={ft} src={src}{flag_str}")
        if section:
            print(f"       section: {section}")
        print(f"       {preview}...")
        print()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="ChromaDB 품질 감사")
    parser.add_argument(
        "--label", default="", help="감사 라벨 (예: before, after)"
    )
    args = parser.parse_args()

    config = load_config()
    vs_cfg = config.get("vectorstore", {})
    collection_name = vs_cfg.get("collection_name", "rfp_docs")
    persist_dir = str(
        Path(project_root / vs_cfg.get("persist_directory", "./chroma_db")).resolve()
    )

    audit(persist_dir, collection_name, label=args.label)


if __name__ == "__main__":
    main()
