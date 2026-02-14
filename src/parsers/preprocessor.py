#!/usr/bin/env python3
"""통합 전처리기: CSV + 원본(HWP/PDF) 매칭 후 마크다운/매니페스트 생성."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.parsers.csv_loader import CSVMarkdownConverter
from src.parsers.hwp_loader import HWPMarkdownConverter
from src.parsers.pdf_loader import PDFMarkdownConverter


class UnifiedCorpusPreprocessor:
    """RFP 원본/CSV 통합 코퍼스를 생성하는 전처리기."""

    def __init__(self, input_dir: str | Path, output_dir: str | Path) -> None:
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.pdf_dir = self.output_dir / "pdf"
        self.markdown_dir = self.output_dir / "markdown"
        self.manifest_path = self.output_dir / "manifest.json"

        self.csv_converter = CSVMarkdownConverter()
        self.hwp_converter = HWPMarkdownConverter()
        self.pdf_converter = PDFMarkdownConverter()

    def build(self, overwrite: bool = False, max_rows: int | None = None) -> dict[str, Any]:
        """통합 코퍼스를 생성하고 매니페스트를 반환합니다."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        csv_path = self._find_csv_path()
        markdown_rows = self.csv_converter.convert_file(csv_path)
        if max_rows is not None:
            markdown_rows = markdown_rows[:max_rows]

        records: list[dict[str, Any]] = []
        for md in markdown_rows:
            record = self._build_record(md, overwrite=overwrite)
            records.append(record)

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "csv_path": str(csv_path),
            "total_rows": len(markdown_rows),
            "matched_source_files": sum(1 for r in records if r.get("source_exists")),
            "records": records,
        }
        self.manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    def _find_csv_path(self) -> Path:
        candidates = sorted(self.input_dir.glob("data_list*.csv"))
        if not candidates:
            candidates = sorted(self.input_dir.glob("*data*.csv"))
        if not candidates:
            raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {self.input_dir}")
        return candidates[0]

    def _resolve_source_file(self, filename: str) -> Path | None:
        if not filename:
            return None
        exact = self.input_dir / filename
        if exact.exists():
            return exact

        stem = Path(filename).stem
        for path in self.input_dir.glob(f"{stem}.*"):
            if path.suffix.lower() in {".pdf", ".hwp", ".hwpx"}:
                return path
        return None

    @staticmethod
    def _safe_name(text: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
        return cleaned.strip("_") or "unknown"

    def _build_record(self, md_row: Any, overwrite: bool) -> dict[str, Any]:
        row_meta = dict(md_row.metadata or {})
        source_file = self._resolve_source_file(md_row.filename)
        source_exists = source_file is not None and source_file.exists()

        source_type = ""
        converted_pdf: Path | None = None
        page_chunks: list[dict[str, Any]] = []

        if source_exists and source_file is not None:
            source_type = source_file.suffix.lower().lstrip(".")
            if source_file.suffix.lower() in {".hwp", ".hwpx"}:
                converted_pdf = self.hwp_converter.convert_to_pdf(
                    source_file,
                    self.pdf_dir,
                    overwrite=overwrite,
                )
                if converted_pdf:
                    page_chunks = self.pdf_converter.extract_pages(converted_pdf, include_tables=True)
                else:
                    page_chunks = self.hwp_converter.extract_pages(source_file)
            elif source_file.suffix.lower() == ".pdf":
                page_chunks = self.pdf_converter.extract_pages(source_file, include_tables=True)

        markdown_text = self._build_unified_markdown(md_row, source_file, converted_pdf, page_chunks)
        md_name_seed = f"{md_row.row_num:03d}_{Path(md_row.filename or md_row.org_name).stem}"
        md_name = f"{self._safe_name(md_name_seed)}.md"
        md_path = self.markdown_dir / md_name
        md_path.write_text(markdown_text, encoding="utf-8")

        table_count = sum(int(p.get("table_count", 0) or 0) for p in page_chunks)
        record = {
            "row_num": md_row.row_num,
            "org_name": md_row.org_name,
            "project_name": md_row.project_name,
            "filename": md_row.filename,
            "file_format": md_row.file_format,
            "source_exists": source_exists,
            "source_path": str(source_file) if source_file else None,
            "source_type": source_type,
            "converted_pdf": str(converted_pdf) if converted_pdf else None,
            "page_count": len(page_chunks),
            "table_count": table_count,
            "markdown_path": str(md_path),
            "metadata": row_meta,
        }
        return record

    def _build_unified_markdown(
        self,
        md_row: Any,
        source_file: Path | None,
        converted_pdf: Path | None,
        page_chunks: list[dict[str, Any]],
    ) -> str:
        lines: list[str] = []
        title = f"{md_row.org_name} - {md_row.project_name}".strip(" -")
        lines.append(f"# {title}\n")

        lines.append("## CSV 메타데이터")
        for key, value in (md_row.metadata or {}).items():
            if value in ("", None):
                continue
            lines.append(f"- **{key}**: {value}")
        lines.append("")

        lines.append("## 원본 파일 매칭")
        lines.append(f"- **source_path**: {source_file if source_file else '매칭 실패'}")
        lines.append(f"- **converted_pdf**: {converted_pdf if converted_pdf else '없음'}")
        lines.append(f"- **extracted_pages**: {len(page_chunks)}")
        lines.append("")

        lines.append("## 원본 문서 추출 내용")
        if not page_chunks:
            lines.append("원본 텍스트 추출에 실패했습니다.")
            lines.append("")
            return "\n".join(lines)

        for page in page_chunks:
            page_num = page.get("page", "?")
            table_count = int(page.get("table_count", 0) or 0)
            lines.append(f"### 페이지 {page_num} (표 {table_count}개)")
            content = (page.get("content") or "").strip()
            if content:
                lines.append(content)
            lines.append("")

        return "\n".join(lines)
