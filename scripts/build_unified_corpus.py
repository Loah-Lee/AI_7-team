#!/usr/bin/env python3
"""CSV + 원본 파일 통합 코퍼스 구축 스크립트."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.parsers.preprocessor import UnifiedCorpusPreprocessor


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV + 원본 문서를 통합 전처리합니다.")
    parser.add_argument("--input-dir", default="data/files", help="CSV/HWP/PDF 원본 디렉토리")
    parser.add_argument("--output-dir", default="data/processed", help="전처리 결과 저장 디렉토리")
    parser.add_argument("--overwrite", action="store_true", help="기존 PDF/Markdown 결과를 덮어씁니다.")
    parser.add_argument("--max-rows", type=int, default=None, help="샘플링 처리할 최대 행 수")
    args = parser.parse_args()

    preprocessor = UnifiedCorpusPreprocessor(args.input_dir, args.output_dir)
    summary = preprocessor.build(overwrite=args.overwrite, max_rows=args.max_rows)

    print("=" * 60)
    print("통합 코퍼스 전처리 완료")
    print(f"- CSV rows: {summary.get('total_rows')}")
    print(f"- source 매칭 성공: {summary.get('matched_source_files')}")
    print(f"- manifest: {Path(args.output_dir).resolve() / 'manifest.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
