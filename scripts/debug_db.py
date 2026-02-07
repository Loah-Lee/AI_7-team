"""ChromaDB 인덱싱 상태 확인 스크립트.

무작위 5개 청크를 가져와 텍스트와 메타데이터를 출력한다.

실행: uv run python scripts/debug_db.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.utils.config import load_config


def main() -> None:
    config = load_config()
    vs_cfg = config.get("vectorstore", {})
    collection_name = vs_cfg.get("collection_name", "rfp_docs")
    persist_dir = str(Path(project_root / vs_cfg.get("persist_directory", "./chroma_db")).resolve())

    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)

    try:
        collection = client.get_collection(collection_name)
    except Exception:
        print(f"[ERROR] 컬렉션 '{collection_name}'을 찾을 수 없습니다.")
        print(f"        경로: {persist_dir}")
        return

    total = collection.count()
    print(f"=== ChromaDB 상태 확인 ===")
    print(f"컬렉션: {collection_name}")
    print(f"총 문서 수: {total}")
    print()

    if total == 0:
        print("[INFO] 저장된 문서가 없습니다.")
        return

    # 전체 ID 가져오기 → 무작위 5개 선택
    all_ids = collection.get(limit=total, include=[])["ids"]
    sample_size = min(5, total)
    sample_ids = random.sample(all_ids, sample_size)

    result = collection.get(ids=sample_ids, include=["documents", "metadatas"])

    for i, (doc_id, text, meta) in enumerate(
        zip(result["ids"], result["documents"], result["metadatas"]), start=1
    ):
        print(f"--- [{i}/{sample_size}] ID: {doc_id} ---")
        print(f"[메타데이터]")
        for key, value in sorted(meta.items()):
            print(f"  {key}: {value}")
        print(f"[텍스트] (처음 500자)")
        print(text[:500] if text else "(비어 있음)")
        print()


if __name__ == "__main__":
    main()
