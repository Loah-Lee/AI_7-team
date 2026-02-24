#!/usr/bin/env python3
"""HWP/HWPX 전처리: PDF 변환 + 페이지/표 메타데이터 추출."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.parsers.hwp_loader import HWPMarkdownConverter
from src.parsers.pdf_loader import PDFMarkdownConverter


def collect_hwp_files(input_dir: Path) -> list[Path]:
    """입력 디렉토리에서 HWP/HWPX 파일을 수집합니다."""
    files = list(input_dir.glob("*.hwp")) + list(input_dir.glob("*.hwpx"))
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="HWP/HWPX를 PDF로 변환하고 페이지/표 정보를 추출합니다.")
    parser.add_argument("--input-dir", default="data/files", help="HWP/HWPX 원본 디렉토리")
    parser.add_argument("--output-dir", default="data/preprocessed_pdf", help="변환된 PDF 출력 디렉토리")
    parser.add_argument("--manifest", default="data/preprocessed_pdf/manifest.json", help="메타데이터 출력 JSON")
    parser.add_argument("--overwrite", action="store_true", help="기존 PDF를 덮어씁니다.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    hwp_files = collect_hwp_files(input_dir)
    if not hwp_files:
        print(f"입력 디렉토리에 HWP/HWPX가 없습니다: {input_dir}")
        return

    hwp_converter = HWPMarkdownConverter()
    pdf_converter = PDFMarkdownConverter()

    print("=" * 60)
    print("HWP/HWPX 전처리 시작")
    print(f"- 입력: {input_dir}")
    print(f"- 출력: {output_dir}")
    print(f"- 대상 파일 수: {len(hwp_files)}")
    print("=" * 60)

    records: list[dict[str, object]] = []
    success = 0

    for idx, hwp_path in enumerate(hwp_files, 1):
        print(f"[{idx}/{len(hwp_files)}] {hwp_path.name}", end=" ... ", flush=True)

        try:
            pdf_path = hwp_converter.convert_to_pdf(hwp_path, output_dir, overwrite=args.overwrite)
        except RuntimeError as exc:
            print("실패")
            records.append({
                "source_hwp": str(hwp_path),
                "converted_pdf": None,
                "success": False,
                "error": str(exc),
                "pdf_generation_mode": None,
                "page_count": 0,
                "table_count": 0,
                "table_pages": 0,
                "text_chars": 0,
            })
            continue

        pages = pdf_converter.extract_pages(pdf_path, include_tables=True)
        table_count = sum(int(page.get("table_count", 0)) for page in pages)
        table_pages = sum(1 for page in pages if int(page.get("table_count", 0)) > 0)
        text_chars = sum(len((page.get("content") or "")) for page in pages)

        records.append({
            "source_hwp": str(hwp_path),
            "converted_pdf": str(pdf_path),
            "success": True,
            "error": None,
            "pdf_generation_mode": hwp_converter.last_pdf_generation_mode,
            "page_count": len(pages),
            "table_count": table_count,
            "table_pages": table_pages,
            "text_chars": text_chars,
        })
        success += 1
        print(f"완료 (pages={len(pages)}, tables={table_count})")

    summary = {
        "total_files": len(hwp_files),
        "success_files": success,
        "failed_files": len(hwp_files) - success,
        "records": records,
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print("전처리 완료")
    print(f"- 성공: {summary['success_files']}")
    print(f"- 실패: {summary['failed_files']}")
    print(f"- 매니페스트: {manifest_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
