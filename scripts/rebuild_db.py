from __future__ import annotations

import argparse
from pathlib import Path

from src.retrievers.build_dense_index import main as build_dense_main
from src.retrievers.chroma_store import build_chroma_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--chroma", action="store_true")
    parser.add_argument("--input-dir", default=str(Path("notebooks") / "data_chunks_rich"))
    parser.add_argument("--chroma-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--collection", default="rfp_b")
    args = parser.parse_args()

    if args.dense:
        build_dense_main()

    if args.chroma:
        build_chroma_index(
            input_dir=Path(args.input_dir),
            persist_dir=Path(args.chroma_dir),
            collection_name=args.collection,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
