#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB — v3.0 (Chroma Hybrid Local)

특징:
- Cloud API 없이 로컬에서 ChromaBm25EmbeddingFunction으로 Sparse Vector 생성
- ChromaDB .upsert() 시 dense/sparse 벡터를 동시에 저장 (Single Storage)
- v2.2의 핵심 로직(deterministic doc_id, hierarchy, uid assignment) 100% 보존
"""
import os
import hashlib
import json
import chromadb
from pathlib import Path
from chromadb.utils import embedding_functions
from chromadb.utils.embedding_functions import ChromaBm25EmbeddingFunction
from typing import Any, List, Dict, Tuple, Optional, cast
from src.utils.config import PROJECT_ROOT, CHROMA_PATH, CHUNK_DIR, EMBEDDING_MODEL
# 필수 라이브러리 체크
try:
    from kiwipiepy import Kiwi
except ImportError:
    print("❌ Error: kiwipiepy not found. Run: pip install kiwipiepy")
    exit(1)
# ---------------------------------------------------------------------------
# 1. 환경 설정 및 초기화
# ---------------------------------------------------------------------------
os.makedirs(CHROMA_PATH, exist_ok=True)
_kiwi = Kiwi()
client = chromadb.PersistentClient(path=str(CHROMA_PATH))

# [Dense] SRoBERTa 임베딩
dense_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)

# [Sparse] 로컬 BM25 임베딩 (Cloud API 키 불필요)
bm25_ef = ChromaBm25EmbeddingFunction(
    k=1.2, b=0.75, avg_doc_length=256.0, token_max_length=40
)

# ---------------------------------------------------------------------------
# 2. 핵심 유틸리티 (v2.2 로직 보존)
# ---------------------------------------------------------------------------

def compute_doc_id(parser_raw_path: Path) -> str:
    """[필수] 파일 내용 기반 해시 생성 → 멱등성 및 Upsert 보장."""
    h = hashlib.sha256(parser_raw_path.read_bytes()).hexdigest()[:16]
    return h

def extract_nouns(text: str) -> str:
    """BM25용 명사 추출 (한국어 검색 품질 최적화)."""
    if not text: return ""
    tokens = _kiwi.tokenize(text)
    return " ".join([t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')])

def _normalize_metadata(metadata: Dict) -> Dict:
    """ChromaDB 로컬 버전의 타입 제약 해결."""
    normalized = {}
    for k, v in metadata.items():
        if v is None: continue
        elif isinstance(v, (list, dict)): normalized[k] = json.dumps(v, ensure_ascii=False)
        else: normalized[k] = v

    source_raw = str(metadata.get("source", "") or "").strip()
    if source_raw:
        source_name = Path(source_raw).name or source_raw
        source_suffix = Path(source_name).suffix.lower().lstrip(".")
        if source_suffix in {"pdf", "hwp", "hwpx", "csv"}:
            normalized["source"] = Path(source_name).stem
            if not normalized.get("source_ext"):
                normalized["source_ext"] = source_suffix
        else:
            normalized["source"] = source_name
    return normalized

def _generate_section_summary(title: str, level: int, relevant_chunks: List[Dict]) -> str:
    """[v2.2 로직] 계층 검색용 요약 생성."""
    targets = sorted(relevant_chunks, key=lambda c: c['metadata']['chunk_order'])[:3]
    summary_parts = []
    for chunk in targets:
        text = chunk.get('page_content', '').strip()
        if not text: continue
        try: sentences = [s.text for s in _kiwi.split_into_sents(text)]
        except: sentences = [text]
        snippet = " ".join(sentences[:2])
        if snippet: summary_parts.append(snippet)
    summary_text = " ".join(summary_parts)
    if len(summary_text) > 400: summary_text = summary_text[:400] + "..."
    return f"[Level {level}] {title}\n{summary_text}"

def _sparse_to_dict(sparse_vec) -> Dict:
    """SparseVector를 JSON-serializable dict로 변환."""
    return {str(idx): float(val) for idx, val in zip(sparse_vec.indices, sparse_vec.values)}

# ---------------------------------------------------------------------------
# 3. UID 및 Hierarchy 관리 (v2.2 로직 보존)
# ---------------------------------------------------------------------------

def assign_uids(chunks: List[Dict]) -> None:
    """[필수] 순차적 UID 부여 및 무결성 체크."""
    doc_counters = {}
    for i, chunk in enumerate(chunks):
        doc_id = chunk.get('doc_id')
        idx = doc_counters.get(doc_id, 0)
        uid = f"{doc_id}_{idx}"
        chunk['uid'] = uid
        chunk['metadata'].update({'uid': uid, 'doc_id': doc_id, 'type': 'chunk', 'chunk_order': idx})
        doc_counters[doc_id] = idx + 1

def build_hierarchy(chunks: List[Dict]) -> Tuple[List[Tuple[str, Dict]], Dict]:
    """[복원] _generate_section_summary를 사용하여 계층 엔트리를 생성합니다."""
    doc_groups = {}
    for chunk in chunks: doc_groups.setdefault(chunk['doc_id'], []).append(chunk)

    all_entries = []
    section_uid_map = {}

    for doc_id, doc_chunks in doc_groups.items():
        doc_chunks_sorted = sorted(doc_chunks, key=lambda c: c['metadata']['chunk_order'])
        doc_title = doc_chunks_sorted[0]['metadata'].get('document_title', 'Unknown')

        l1_sections = {}
        l2_sections = {}
        for c in doc_chunks_sorted:
            l1, l2 = c['metadata'].get('section_level1', 'N/A'), c['metadata'].get('section_level2', 'N/A')
            if l1 and l1 != 'N/A':
                l1_sections.setdefault(l1, []).append(c['metadata']['chunk_order'])
                if l2 and l2 != 'N/A':
                    l2_sections.setdefault((l1, l2), []).append(c['metadata']['chunk_order'])

        h_counter = 1
        l1_uid_map = {}
        # L1 계층 생성
        for l1_title, orders in l1_sections.items():
            h_uid = f"{doc_id}_h_{h_counter}"; h_counter += 1
            l1_uid_map[l1_title] = h_uid
            section_chunks = [c for c in doc_chunks_sorted if c['metadata'].get('section_level1') == l1_title]
            
            # 🚨 여기서 요약 함수 호출!
            text_with_summary = _generate_section_summary(l1_title, 1, section_chunks)
            
            all_entries.append((text_with_summary, {
                "type": "hierarchy", "doc_id": doc_id, "document_title": doc_title, "uid": h_uid, 
                "level": 1, "title": l1_title, "start_order": min(orders), "end_order": max(orders)
            }))

        # L2 계층 생성
        l2_uid_map = {}
        for (l1_title, l2_title), orders in l2_sections.items():
            h_uid = f"{doc_id}_h_{h_counter}"; h_counter += 1
            l2_uid_map[(l1_title, l2_title)] = h_uid
            section_chunks = [c for c in doc_chunks_sorted if c['metadata'].get('section_level1') == l1_title and c['metadata'].get('section_level2') == l2_title]
            
            # 🚨 L2 경로 요약 생성
            full_title_path = f"{l1_title} > {l2_title}"
            text_with_summary = _generate_section_summary(full_title_path, 2, section_chunks)
            
            all_entries.append((text_with_summary, {
                "type": "hierarchy", "doc_id": doc_id, "document_title": doc_title, "uid": h_uid, 
                "level": 2, "title": l2_title, "parent_uid": l1_uid_map.get(l1_title), "start_order": min(orders), "end_order": max(orders)
            }))

        # Mapping: 청크가 가장 구체적인 섹션 ID를 가리키도록 설정
        uid_map_for_doc = {}
        for c in doc_chunks_sorted:
            order = c['metadata']['chunk_order']
            l1, l2 = c['metadata'].get('section_level1'), c['metadata'].get('section_level2')
            s_uid = l2_uid_map.get((l1, l2)) or l1_uid_map.get(l1)
            uid_map_for_doc[order] = s_uid
        section_uid_map[doc_id] = uid_map_for_doc

    return all_entries, section_uid_map

def apply_section_uids(chunks: List[Dict], section_uid_map: Dict) -> None:
    """[필수] 청크-섹션 연결 고리(section_uid) 주입."""
    for chunk in chunks:
        doc_id = chunk['doc_id']
        order = chunk['metadata']['chunk_order']
        s_uid = section_uid_map.get(doc_id, {}).get(order)
        chunk['metadata']['section_uid'] = s_uid if s_uid else "None"

# ---------------------------------------------------------------------------
# 4. 하이브리드 저장 (Chroma Local Native)
# ---------------------------------------------------------------------------

def upsert_hybrid_chunks(chunks: List[Dict]) -> int:
    if not chunks: return 0
    print(f"🔼 ChromaDB Local Hybrid Upserting...")

    collection = client.get_or_create_collection(
        name="chunks", 
        embedding_function=dense_ef,
        metadata={"hnsw:space": "cosine"}
    )
    
    doc_ids = list({c['doc_id'] for c in chunks})
    for did in doc_ids:
        collection.delete(where={"doc_id": did})

    # BM25 Sparse Vector 생성
    noun_corpus = [extract_nouns(c['page_content']) for c in chunks]
    sparse_embeddings = bm25_ef(noun_corpus)

    # ✅ sparse vector를 metadata에 JSON으로 저장
    metadatas = []
    for c, se in zip(chunks, sparse_embeddings):
        meta = _normalize_metadata(c['metadata'])
        meta["sparse_embedding"] = json.dumps(_sparse_to_dict(se))
        metadatas.append(meta)

    collection.upsert(
        ids=[c['uid'] for c in chunks],
        documents=[c['page_content'] for c in chunks],
        metadatas=metadatas,
    )
    
    print(f"   ✓ Chunks: {len(chunks)} items upserted with hybrid vectors.")
    return len(chunks)

def upsert_hierarchy_chroma(hierarchy_entries: List[Tuple[str, Dict]]) -> int:
    """계층 정보를 ChromaDB에 저장 (Dense 전용 검색용)."""
    if not hierarchy_entries: return 0
    coll = client.get_or_create_collection(name="hierarchy", embedding_function=dense_ef)
    
    doc_ids = list({e[1]['doc_id'] for e in hierarchy_entries})
    for did in doc_ids: coll.delete(where={"doc_id": did})

    coll.upsert(
        ids=[e[1]['uid'] for e in hierarchy_entries],
        documents=[e[0] for e in hierarchy_entries],
        metadatas=[_normalize_metadata(e[1]) for e in hierarchy_entries]
    )
    return len(hierarchy_entries)

# ---------------------------------------------------------------------------
# 5. 무결성 검증
# ---------------------------------------------------------------------------

def verify_integrity(expected_count: int) -> bool:
    print("\n🔍 INTEGRITY VERIFICATION (v3.0 Chroma Hybrid)")
    coll = client.get_collection(name="chunks")
    actual_count = coll.count()
    
    check = actual_count == expected_count
    print(f"   ✓ Chroma Count: {actual_count} {'✅' if check else '❌'}")
    return check
