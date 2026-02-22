from __future__ import annotations

import argparse
from pathlib import Path

from .chroma_store import build_chroma_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(Path("notebooks") / "data_chunks_rich"))
    parser.add_argument("--persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--collection", default="rfp_b_oai")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument(
        "--model-provider",
        choices=["auto", "openai"],
        default="auto",
        help="시나리오 B 기준: auto/openai 모두 OpenAI 임베딩 사용",
    )
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    model = args.model
    if model == "auto":
        model = "text-embedding-3-small"

    print(f"CHROMA PROVIDER | model={model}")

    build_chroma_index(
        input_dir=Path(args.input_dir),
        persist_dir=Path(args.persist_dir),
        collection_name=args.collection,
        model=model,
        batch_size=args.batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
