from __future__ import annotations

# 자체 생성 코드(프로젝트 기존 라이선스에 종속)

import argparse
from pathlib import Path

from .retrievers.dense_openai import build_dense_index


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B"], required=True)
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--sleep-s", type=float, default=0.0)
    args = parser.parse_args()

    variant = args.variant.upper()
    if args.input_dir:
        input_dir = Path(args.input_dir)
    else:
        input_dir = Path("data_chunks") if variant == "A" else Path("notebooks") / "data_chunks_rich"

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data_index") / f"dense_{variant}"

    _log_start(input_dir, output_dir)
    try:
        build_dense_index(
            input_dir=input_dir,
            output_dir=output_dir,
            model=args.model,
            batch_size=args.batch_size,
            sleep_s=args.sleep_s,
        )
        _log_ok("dense_index", input_dir, output_dir)
        return 0
    except Exception as exc:
        _log_fail("dense_index", input_dir, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
