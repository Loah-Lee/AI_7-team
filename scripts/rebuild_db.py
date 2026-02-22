from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.rich_chunk import chunk_rich
from src.retrievers.build_dense_index import main as build_dense_main
from src.retrievers.chroma_store import build_chroma_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-rich", action="store_true")
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--chroma", action="store_true")
    parser.add_argument("--chunk-input-dir", default=str(Path("notebooks") / "data_rich"))
    parser.add_argument("--chunk-output-dir", default=str(Path("notebooks") / "data_chunks_rich"))
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=100)
    parser.add_argument("--chroma-input-dir", "--input-dir", dest="chroma_input_dir", default=None)
    parser.add_argument("--chroma-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--collection", default="rfp_b_oai")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if args.overlap < 0:
        raise ValueError("--overlap must be non-negative")
    if args.overlap >= args.chunk_size:
        raise ValueError("--overlap must be smaller than --chunk-size")

    if args.chunk_rich:
        chunk_rich(
            input_dir=Path(args.chunk_input_dir),
            output_dir=Path(args.chunk_output_dir),
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )

    if args.dense:
        build_dense_main()

    if args.chroma:
        default_chunked_dir = Path("notebooks") / "data_chunks_rich"
        chroma_input_dir = (
            Path(args.chroma_input_dir)
            if args.chroma_input_dir
            else (Path(args.chunk_output_dir) if args.chunk_rich else default_chunked_dir)
        )
        build_chroma_index(
            input_dir=chroma_input_dir,
            persist_dir=Path(args.chroma_dir),
            collection_name=args.collection,
            model=args.model,
            batch_size=args.batch_size,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
