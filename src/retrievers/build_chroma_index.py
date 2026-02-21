from __future__ import annotations

import argparse
import os
from pathlib import Path

from .chroma_store import build_chroma_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(Path("notebooks") / "data_chunks_rich"))
    parser.add_argument("--persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--collection", default="rfp_b")
    parser.add_argument("--model", default="auto")
    parser.add_argument(
        "--model-provider",
        choices=["auto", "openai", "kosimcse"],
        default="auto",
        help="auto(OPENAI_API_KEY 기준), openai, kosimcse 선택",
    )
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    model = args.model
    if args.model_provider == "openai":
        model = "text-embedding-3-small" if model == "auto" else model
    elif args.model_provider == "kosimcse":
        model = "kosimcse"
    else:
        if model == "auto":
            # OPENAI_API_KEY 유무로 provider 자동 선택
            try:
                from dotenv import load_dotenv  # type: ignore

                load_dotenv()
            except Exception:
                pass
            model = "text-embedding-3-small" if os.getenv("OPENAI_API_KEY", "").strip() else "kosimcse"

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
