from __future__ import annotations

import argparse
import re
from pathlib import Path

from .chroma_store import search_chroma


def _preview(text: str, max_len: int = 180) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= max_len else t[:max_len] + "..."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--collection", default="rfp_b")
    parser.add_argument("--model", default="auto")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--org", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--source", default="")
    args = parser.parse_args()

    results = search_chroma(
        query=args.query,
        persist_dir=Path(args.persist_dir),
        collection_name=args.collection,
        model=args.model,
        top_k=args.topk,
        org=args.org or None,
        doc_type=args.type or None,
        source=args.source or None,
    )
    for r in results:
        print(
            f"- score={r['score']:.4f} | source_path={r['source_path']} | chunk_index={r['chunk_index']}"
        )
        print(f"  text={_preview(str(r['text']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
