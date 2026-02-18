#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB (Korean-optimized) — v2.2

v2.2 확장:
- chunks metadata: type, chunk_order, section_uid 추가 + document_title 정규화
- hierarchy 테이블: L1/L2 Section Scope (start_order/end_order = chunk_order 범위)
- Sparse 검색: chunks JOIN 기반 metadata 필터
- JSON-expression 인덱스 3종

Unchanged:
- Korean embedding model: jhgan/ko-sroberta-multitask (768d)
- FTS5 tokenization: kiwipiepy morphological noun extraction
- Upsert pattern: doc_id-level DELETE→INSERT (deterministic SHA-256 hash)
- UID format: {doc_id}_{local_chunk_index}
"""
import os
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, cast

# 필수 라이브러리 로드
try:
    from langchain_community.vectorstores import SQLiteVec
    from langchain_community.embeddings import SentenceTransformerEmbeddings
    from kiwipiepy import Kiwi
except ImportError:
    print("❌ Error: Libraries not found. Run: pip install langchain-community sentence-transformers sqlite-vec kiwipiepy")
    exit(1)

DB_PATH = "DB/document.db"
CHUNK_DIR = "output/chunks"
EMBEDDING_MODEL = 'jhgan/ko-sroberta-multitask'  # 768d Korean model

os.makedirs('DB', exist_ok=True)

# Module-level Kiwi singleton
_kiwi = Kiwi()


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def extract_nouns(text: str) -> str:
    """
    kiwipiepy를 사용하여 텍스트에서 명사만 추출합니다.
    예: "벤처확인종합관리시스템 기능 고도화" -> "벤처 확인 종합 관리 시스템 기능 고도"
    """
    if not text:
        return ""
    tokens: List[Any] = cast(List[Any], _kiwi.tokenize(text))
    nouns = [t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')]
    return " ".join(nouns)


def _generate_section_summary(title: str, level: int, relevant_chunks: List[Dict]) -> str:
    """
    [Option C] 계층 검색 정확도를 위해 제목 + 초반 청크 요약을 결합한다.
    규칙:
      1. chunk_order 순으로 정렬된 청크 중 앞 3개만 대상.
      2. 각 청크에서 kiwipiepy로 문장을 분리해 앞 2문장씩 추출.
      3. 최대 400자 정도로 제한하여 결합.
    """
    # chunk_order 기준 정렬 및 상위 3개 선택
    targets = sorted(relevant_chunks, key=lambda c: c['metadata']['chunk_order'])[:3]

    summary_parts = []
    for chunk in targets:
        text = chunk.get('content', '').strip()
        if not text:
            continue
        # 문장 분리 (모듈 전역 _kiwi 사용)
        try:
            sentences = [s.text for s in _kiwi.split_into_sents(text)]
        except Exception:
            sentences = [text] # fallback

        # 앞 2문장 추출
        snippet = " ".join(sentences[:2])
        if snippet:
            summary_parts.append(snippet)

    summary_text = " ".join(summary_parts)
    
    # 길이 제한 (토큰 고려하여 400자)
    if len(summary_text) > 400:
        summary_text = summary_text[:400] + "..."

    return f"[Level {level}] {title}\n{summary_text}"


def _normalize_title(title: str) -> str:
    """document_title 정규화: lower + strip (v2.2 계약)."""
    return title.lower().strip() if title else ""


# ---------------------------------------------------------------------------
# Sparse
# ---------------------------------------------------------------------------

def initialize_sparse_db(db_path: str, chunks: List[Dict]) -> int:
    """doc_id 단위 DELETE→INSERT upsert. Returns number of inserted rows."""
    print(f"🔹 Sparse indexing at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)
    inserted = 0

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS sparse USING fts5(
                uid,
                doc_id UNINDEXED,
                nouns,
                text UNINDEXED,
                tokenize='unicode61'
            )
        ''')

        doc_ids = {c['doc_id'] for c in chunks}
        for doc_id in doc_ids:
            cursor.execute("DELETE FROM sparse WHERE doc_id = ?", (doc_id,))

        print(f"   Extracting nouns for {len(chunks)} chunks...")
        data = []
        for chunk in chunks:
            uid = chunk['uid']
            doc_id = chunk['doc_id']
            noun_text = extract_nouns(chunk['content'])
            data.append((uid, doc_id, noun_text, chunk['content']))

        if data:
            cursor.executemany(
                "INSERT INTO sparse(uid, doc_id, nouns, text) VALUES (?, ?, ?, ?)",
                data,
            )
            conn.commit()
            inserted = len(data)
            print(f"   ✓ Inserted {inserted} chunks into sparse index.")

    return inserted


# ---------------------------------------------------------------------------
# Dense
# ---------------------------------------------------------------------------

def upsert_dense_vectors(db_path: str, chunks: List[Dict], model_name: str) -> int:
    """
    Doc_ID 기반 Dense Upsert 수행.
    - 기존 동일 doc_id 벡터 삭제
    - 새 벡터 삽입
    Returns: inserted vector count
    """
    if not chunks:
        return 0

    print(f"🔼 Dense upsert at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)

    embeddings = SentenceTransformerEmbeddings(model_name=model_name)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
        table_exists = cursor.fetchone() is not None

    if not table_exists:
        # 테이블이 없으면 신규 생성
        print("   Creating new chunks table...")
        SQLiteVec.from_texts(
            texts=[c['content'] for c in chunks],
            embedding=embeddings,
            table="chunks",
            db_file=db_path,
            metadatas=[c['metadata'] for c in chunks],
        )
        print(f"   ✓ Created chunks table with {len(chunks)} vectors.")
        return len(chunks)

    # 테이블 존재 → doc_id 기반 DELETE → INSERT
    doc_ids = {c['doc_id'] for c in chunks}
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for did in doc_ids:
            cursor.execute(
                "DELETE FROM chunks WHERE json_extract(metadata, '$.doc_id') = ?",
                (did,),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"   Deleted {deleted} existing vectors for doc_id={did}")
        conn.commit()

    # 새 벡터 삽입
    SQLiteVec.from_texts(
        texts=[c['content'] for c in chunks],
        embedding=embeddings,
        table="chunks",
        db_file=db_path,
        metadatas=[c['metadata'] for c in chunks],
    )
    print(f"   ✓ Inserted {len(chunks)} vectors.")
    return len(chunks)


# ---------------------------------------------------------------------------
# Hierarchy (v2.2 — L1+L2 Section Scope)
# ---------------------------------------------------------------------------

def build_hierarchy(chunks: List[Dict]) -> Tuple[List[Tuple[str, Dict]], Dict[str, Dict[int, Optional[str]]]]:
    """
    chunk 리스트로부터 hierarchy 엔트리(L1+L2)를 생성하고,
    각 chunk의 chunk_order → section_uid 매핑을 반환한다.

    Returns:
        (hierarchy_entries, section_uid_map)
        - hierarchy_entries: [(text_for_embedding, metadata_dict), ...]
        - section_uid_map: {chunk_order: section_uid} — 가장 구체적인(L2>L1) uid
    """
    doc_groups: Dict[str, List[Dict]] = {}
    for chunk in chunks:
        did = chunk['doc_id']
        doc_groups.setdefault(did, []).append(chunk)

    all_entries: List[Tuple[str, Dict]] = []
    section_uid_map: Dict[str, Dict[int, Optional[str]]] = {}

    for doc_id, doc_chunks in doc_groups.items():
        doc_chunks_sorted = sorted(doc_chunks, key=lambda c: c['metadata']['chunk_order'])
        doc_title = doc_chunks_sorted[0]['metadata'].get('document_title', '')

        # L1: section_level1 → [chunk_order, ...]
        l1_sections: Dict[str, List[int]] = {}
        for c in doc_chunks_sorted:
            l1 = c['metadata'].get('section_level1', 'N/A')
            if l1 and l1 != 'N/A':
                l1_sections.setdefault(l1, []).append(c['metadata']['chunk_order'])

        # L2: (section_level1, section_level2) → [chunk_order, ...]
        l2_sections: Dict[Tuple[str, str], List[int]] = {}
        for c in doc_chunks_sorted:
            l1 = c['metadata'].get('section_level1', 'N/A')
            l2 = c['metadata'].get('section_level2', 'N/A')
            if l1 and l1 != 'N/A' and l2 and l2 != 'N/A':
                l2_sections.setdefault((l1, l2), []).append(c['metadata']['chunk_order'])

        h_counter = 1
        l1_uid_map: Dict[str, str] = {}

        for l1_title, orders in l1_sections.items():
            h_uid = f"{doc_id}_h_{h_counter}"
            h_counter += 1
            l1_uid_map[l1_title] = h_uid

            # 해당 섹션에 속하는 청크들 필터링 (Option C 요약용)
            section_chunks = [
                c for c in doc_chunks_sorted
                if c['metadata'].get('section_level1') == l1_title
            ]

            # [Option C 적용] 제목 + 요약 생성
            text_content = _generate_section_summary(l1_title, 1, section_chunks)

            entry_meta = {
                "type": "hierarchy",
                "doc_id": doc_id,
                "document_title": doc_title,
                "uid": h_uid,
                "level": 1,
                "title": l1_title,
                "parent_uid": None,
                "start_order": min(orders),
                "end_order": max(orders),
            }
            all_entries.append((text_content, entry_meta))

        l2_uid_map: Dict[Tuple[str, str], str] = {}
        for (l1_title, l2_title), orders in l2_sections.items():
            h_uid = f"{doc_id}_h_{h_counter}"
            h_counter += 1
            l2_uid_map[(l1_title, l2_title)] = h_uid

            # 해당 섹션 청크 필터링
            section_chunks = [
                c for c in doc_chunks_sorted
                if c['metadata'].get('section_level1') == l1_title
                and c['metadata'].get('section_level2') == l2_title
            ]

            # [Option C 적용] 경로 포함 제목 + 요약 생성
            full_title = f"{doc_title} {l1_title} > {l2_title}"
            text_content = _generate_section_summary(full_title, 2, section_chunks)

            parent_uid = l1_uid_map.get(l1_title)
            entry_meta = {
                "type": "hierarchy",
                "doc_id": doc_id,
                "document_title": doc_title,
                "uid": h_uid,
                "level": 2,
                "title": l2_title,
                "parent_uid": parent_uid,
                "start_order": min(orders),
                "end_order": max(orders),
            }
            all_entries.append((text_content, entry_meta))

        # section_uid: 가장 구체적인 hierarchy uid (L2 우선, L1 fallback)
        uid_map_for_doc: Dict[int, Optional[str]] = {}
        for c in doc_chunks_sorted:
            order = c['metadata']['chunk_order']
            l1 = c['metadata'].get('section_level1', 'N/A')
            l2 = c['metadata'].get('section_level2', 'N/A')

            s_uid: Optional[str] = None
            if l1 and l1 != 'N/A' and l2 and l2 != 'N/A':
                s_uid = l2_uid_map.get((l1, l2))
            if s_uid is None and l1 and l1 != 'N/A':
                s_uid = l1_uid_map.get(l1)

            uid_map_for_doc[order] = s_uid

        section_uid_map[doc_id] = uid_map_for_doc

    return all_entries, section_uid_map


def upsert_hierarchy(db_path: str, hierarchy_entries: List[Tuple[str, Dict]], model_name: str) -> int:
    """
    doc_id 기반 DELETE→INSERT hierarchy upsert.
    Returns: inserted hierarchy entry count.
    """
    if not hierarchy_entries:
        return 0

    print(f"🌳 Hierarchy upsert at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)

    embeddings = SentenceTransformerEmbeddings(model_name=model_name)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hierarchy'")
        table_exists = cursor.fetchone() is not None

    if not table_exists:
        print(f"   Creating new hierarchy table with {len(hierarchy_entries)} entries...")
        SQLiteVec.from_texts(
            texts=[e[0] for e in hierarchy_entries],
            embedding=embeddings,
            table="hierarchy",
            db_file=db_path,
            metadatas=[e[1] for e in hierarchy_entries],
        )
        print(f"   ✓ Created hierarchy table with {len(hierarchy_entries)} entries.")
        return len(hierarchy_entries)

    # 테이블 존재 → doc_id 기반 DELETE → INSERT
    doc_ids = {e[1]['doc_id'] for e in hierarchy_entries}
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for did in doc_ids:
            cursor.execute(
                "DELETE FROM hierarchy WHERE json_extract(metadata, '$.doc_id') = ?",
                (did,),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"   Deleted {deleted} existing hierarchy entries for doc_id={did}")
        conn.commit()

    SQLiteVec.from_texts(
        texts=[e[0] for e in hierarchy_entries],
        embedding=embeddings,
        table="hierarchy",
        db_file=db_path,
        metadatas=[e[1] for e in hierarchy_entries],
    )
    print(f"   ✓ Inserted {len(hierarchy_entries)} hierarchy entries.")
    return len(hierarchy_entries)


# ---------------------------------------------------------------------------
# 인덱스 (v2.2)
# ---------------------------------------------------------------------------

def ensure_indexes(db_path: str) -> None:
    """v2.2 JSON-expression 인덱스 5종 생성 (IF NOT EXISTS)."""
    print("📇 Ensuring JSON indexes...")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_title
            ON chunks(json_extract(metadata, '$.document_title'))
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_order
            ON chunks(json_extract(metadata, '$.chunk_order'))
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_order
            ON chunks(
                json_extract(metadata, '$.document_title'),
                json_extract(metadata, '$.chunk_order')
            )
        """)

        # Sparse→Chunks JOIN 가속 (FTS5 2단계 쿼리의 Step2에서 사용)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_uid
            ON chunks(json_extract(metadata, '$.uid'))
        """)

        # doc_id 기반 조회/upsert 가속
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_id
            ON chunks(json_extract(metadata, '$.doc_id'))
        """)

        conn.commit()
    print("   ✓ 5 JSON indexes ensured.")


# ---------------------------------------------------------------------------
# UID / Metadata 할당 (v2.2 확장)
# ---------------------------------------------------------------------------

def compute_doc_id(parser_raw_path: Path) -> str:
    """SHA-256 of parser raw output (before auditor) → deterministic doc_id."""
    h = hashlib.sha256(parser_raw_path.read_bytes()).hexdigest()[:16]
    return h


def assign_uids(chunks: List[Dict]) -> None:
    """
    Assign UIDs, chunk_order, type, normalize document_title.
    Enforce Upsert contract (Fail-Fast architecture).

    v2.2 확장:
    - metadata['type'] = 'chunk'
    - metadata['chunk_order'] = doc_id 단위 0-based sequential
    - metadata['document_title'] = lower + trim 정규화
    - section_uid는 이후 build_hierarchy 결과로 채움
    """

    if not chunks:
        raise RuntimeError(
            "Critical: empty chunk list detected before UID assignment"
        )

    doc_counters: Dict[str, int] = {}

    for i, chunk in enumerate(chunks):

        if 'doc_id' not in chunk:
            raise RuntimeError(
                f"Critical: chunk index {i} missing 'doc_id' before UID assignment"
            )

        doc_id = chunk['doc_id']

        if not isinstance(doc_id, str) or not doc_id.strip():
            raise RuntimeError(
                f"Critical: invalid doc_id detected at chunk index {i}"
            )

        if doc_id == "unknown":
            raise RuntimeError(
                f"Critical: forbidden fallback doc_id 'unknown' "
                f"at chunk index {i}"
            )

        idx = doc_counters.get(doc_id, 0)
        uid = f"{doc_id}_{idx}"
        chunk['uid'] = uid

        if 'metadata' not in chunk or chunk['metadata'] is None:
            chunk['metadata'] = {}

        if not isinstance(chunk['metadata'], dict):
            raise RuntimeError(
                f"Critical: metadata must be dict (chunk index {i})"
            )

        chunk['metadata']['uid'] = uid
        chunk['metadata']['doc_id'] = doc_id
        chunk['metadata']['type'] = 'chunk'
        chunk['metadata']['chunk_order'] = idx

        raw_title = chunk['metadata'].get('document_title', '')
        chunk['metadata']['document_title'] = _normalize_title(raw_title)

        chunk['metadata']['section_uid'] = None

        doc_counters[doc_id] = idx + 1


def apply_section_uids(chunks: List[Dict], section_uid_map: Dict[str, Dict[int, Optional[str]]]) -> None:
    """
    build_hierarchy가 반환한 section_uid_map을 chunks에 적용한다.
    """
    for chunk in chunks:
        doc_id = chunk['doc_id']
        order = chunk['metadata']['chunk_order']
        doc_map = section_uid_map.get(doc_id, {})
        s_uid = doc_map.get(order)
        chunk['metadata']['section_uid'] = s_uid


# ---------------------------------------------------------------------------
# 디스크 로드 (standalone main용)
# ---------------------------------------------------------------------------

def load_chunks_from_disk(chunk_dir: str) -> List[Dict]:
    chunks = []
    chunk_path = Path(chunk_dir)
    if not chunk_path.exists():
        return []
    for chunk_file in sorted(chunk_path.glob('chunk_*.json')):
        with open(chunk_file, 'r', encoding='utf-8') as f:
            c = json.load(f)
            c['metadata']['chunk_id'] = c['chunk_id']
            chunks.append(c)
    return chunks


# ---------------------------------------------------------------------------
# 무결성 검증 (v2.2)
# ---------------------------------------------------------------------------

def verify_integrity(db_path: str, chunks: List[Dict], hierarchy_entries: List[Tuple[str, Dict]]) -> bool:
    """
    v2.2 데이터 무결성 계약 전체 검증.
    1. sparse.uid == metadata.uid 일치
    2. Dense 행 수 == Sparse 행 수
    3. chunk_order 결정론적 재현 (doc_id 단위 0-based, 연속, 유일)
    4. hierarchy start_order/end_order vs 실제 chunk_order 범위 완전 일치
    Returns True if all pass.
    """
    print("\n🔍 INTEGRITY VERIFICATION (v2.2)")
    all_pass = True

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # --- 1. sparse.uid == metadata.uid ---
        print("\n   [1] sparse.uid ↔ chunks.metadata.uid 정합성...")
        doc_ids = {c['doc_id'] for c in chunks}
        for did in doc_ids:
            cursor.execute("""
                SELECT s.uid, json_extract(c.metadata, '$.uid')
                FROM sparse s
                JOIN chunks c ON s.uid = json_extract(c.metadata, '$.uid')
                WHERE s.doc_id = ?
            """, (did,))
            joined = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM sparse WHERE doc_id = ?", (did,))
            sparse_n = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM chunks WHERE json_extract(metadata, '$.doc_id') = ?",
                (did,),
            )
            dense_n = cursor.fetchone()[0]

            if len(joined) != sparse_n or len(joined) != dense_n:
                print(f"      ❌ doc_id={did}: joined={len(joined)}, sparse={sparse_n}, dense={dense_n}")
                all_pass = False
            else:
                print(f"      ✅ doc_id={did}: {len(joined)} rows all matched")

        # --- 2. Dense 행 수 == Sparse 행 수 (전체) ---
        print("\n   [2] Dense == Sparse 전체 행 수...")
        cursor.execute("SELECT COUNT(*) FROM chunks")
        total_dense = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sparse")
        total_sparse = cursor.fetchone()[0]
        if total_dense == total_sparse:
            print(f"      ✅ Dense={total_dense}, Sparse={total_sparse}")
        else:
            print(f"      ❌ Dense={total_dense}, Sparse={total_sparse} — MISMATCH")
            all_pass = False

        # --- 3. chunk_order 결정론적 재현 ---
        print("\n   [3] chunk_order deterministic (0-based sequential per doc_id)...")
        for did in doc_ids:
            cursor.execute("""
                SELECT json_extract(metadata, '$.chunk_order')
                FROM chunks
                WHERE json_extract(metadata, '$.doc_id') = ?
                ORDER BY json_extract(metadata, '$.chunk_order')
            """, (did,))
            orders = [row[0] for row in cursor.fetchall()]
            expected = list(range(len(orders)))
            if orders == expected:
                print(f"      ✅ doc_id={did}: {len(orders)} chunks, 0..{len(orders)-1}")
            else:
                print(f"      ❌ doc_id={did}: expected {expected[:5]}..., got {orders[:5]}...")
                all_pass = False

        # --- 4. hierarchy start_order/end_order vs 실제 chunk_order ---
        print("\n   [4] hierarchy start/end_order ↔ actual chunk_order ranges...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hierarchy'")
        if cursor.fetchone():
            for entry_text, entry_meta in hierarchy_entries:
                h_doc_id = entry_meta['doc_id']
                h_start = entry_meta['start_order']
                h_end = entry_meta['end_order']
                h_level = entry_meta['level']
                h_title = entry_meta['title']

                # 실제 DB에서 해당 범위의 chunk 수 확인
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM chunks
                    WHERE json_extract(metadata, '$.doc_id') = ?
                      AND json_extract(metadata, '$.chunk_order') >= ?
                      AND json_extract(metadata, '$.chunk_order') <= ?
                """, (h_doc_id, h_start, h_end))
                actual_count = cursor.fetchone()[0]

                if actual_count > 0:
                    print(f"      ✅ L{h_level} '{h_title}': order [{h_start}..{h_end}] → {actual_count} chunks")
                else:
                    print(f"      ❌ L{h_level} '{h_title}': order [{h_start}..{h_end}] → 0 chunks (empty range!)")
                    all_pass = False
        else:
            print("      ⚠️ hierarchy table not found — skipping")

    # --- 5. FTS keyword smoke test ---
    print("\n   [5] FTS keyword smoke test ('제안')...")
    query_nouns = extract_nouns("제안")
    if query_nouns.strip():
        noun_tokens = query_nouns.split()
        fts_query = ' AND '.join([f'"{t}"' for t in noun_tokens])
    else:
        fts_query = "제안"
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT rowid, snippet(sparse, 1, '[', ']', '...', 20), bm25(sparse) as score
                FROM sparse WHERE nouns MATCH ? ORDER BY score LIMIT 3
            """, (fts_query,))
            results = cursor.fetchall()
            if results:
                for row in results:
                    print(f"      ✅ Score={row[2]:.2f}, Text: {row[1][:80]}")
            else:
                print(f"      ⚠️ No FTS results for '{fts_query}'")
    except Exception as e:
        print(f"      ❌ FTS search failed: {e}")
        all_pass = False

    status = "ALL PASS ✅" if all_pass else "SOME FAILURES ❌"
    print(f"\n   === Integrity result: {status} ===")
    return all_pass


# ---------------------------------------------------------------------------
# main (standalone 실행용)
# ---------------------------------------------------------------------------

def main():
    print("\n" + "="*60)
    print("💾 STORAGE & INDEXING STAGE v2.2 (Korean-optimized)")
    print("="*60 + "\n")

    all_chunks = load_chunks_from_disk(CHUNK_DIR)
    if not all_chunks:
        print("❌ No chunks found.")
        return
    print(f"   ✓ Loaded {len(all_chunks)} chunks.")

    # 1. doc_id 할당
    parser_dir = Path('output')
    for chunk in all_chunks:
        src = chunk.get('metadata', {}).get('source_file', '')
        stem = Path(src).stem if src else 'unknown'
        raw_path = parser_dir / f'step1_parsed_{stem}.md'
        if raw_path.exists():
            chunk['doc_id'] = compute_doc_id(raw_path)
        else:
            chunk['doc_id'] = hashlib.sha256(src.encode()).hexdigest()[:16]

    # 2. UID + chunk_order + type + document_title 정규화
    assign_uids(all_chunks)

    # 3. Hierarchy 생성 + section_uid 매핑
    hierarchy_entries, section_uid_map = build_hierarchy(all_chunks)
    apply_section_uids(all_chunks, section_uid_map)

    # 4. Dense upsert
    dense_count = upsert_dense_vectors(DB_PATH, all_chunks, EMBEDDING_MODEL)

    # 5. Sparse upsert
    sparse_count = initialize_sparse_db(DB_PATH, all_chunks)

    print(f"\n   Dense={dense_count}, Sparse={sparse_count}, Chunks={len(all_chunks)}")
    if dense_count != sparse_count:
        print(f"   ⚠️ Dense/Sparse mismatch!")

    # 6. Hierarchy upsert
    hierarchy_count = upsert_hierarchy(DB_PATH, hierarchy_entries, EMBEDDING_MODEL)
    print(f"   Hierarchy={hierarchy_count}")

    # 7. JSON indexes
    ensure_indexes(DB_PATH)

    # 8. Integrity verification
    verify_integrity(DB_PATH, all_chunks, hierarchy_entries)

    print("\n\n✨ Storage & Indexing v2.2 complete!")


if __name__ == '__main__':
    main()