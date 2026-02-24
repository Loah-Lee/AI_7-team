#!/usr/bin/env python3
"""HWP 로더 - LibreOffice를 통한 PDF 변환 후 텍스트 추출."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import re
import html
from typing import Any
from pathlib import Path

sys.path.insert(0, 'src')

from src.utils.config import MIN_SECTION_LENGTH, MAX_PAGES
from src.utils.helpers import normalize_newlines, remove_josa
from src.parsers.pdf_loader import PDFMarkdownConverter


class HWPMarkdownConverter:
    """HWP 문서를 마크다운으로 변환하는 클래스."""

    def __init__(self) -> None:
        """HWP 변환기를 초기화합니다."""
        self.pdf_converter = PDFMarkdownConverter()
        self._check_libreoffice()
        self.hwp5txt_path = self._find_hwp5txt()
        self.hwp5html_path = self._find_hwp5html()
        self.last_pdf_generation_mode: str | None = None

    def _check_libreoffice(self) -> None:
        """LibreOffice 가용성 확인."""
        self.libreoffice_path = self._find_libreoffice()

    @staticmethod
    def _find_hwp5txt() -> str | None:
        """hwp5txt 실행 파일 경로를 찾습니다."""
        candidates = [
            str((Path(__file__).resolve().parents[2] / "venv" / "bin" / "hwp5txt")),
            "/usr/bin/hwp5txt",
            "/usr/local/bin/hwp5txt",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        try:
            result = subprocess.run(["which", "hwp5txt"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _find_hwp5html() -> str | None:
        """hwp5html 실행 파일 경로를 찾습니다."""
        candidates = [
            str((Path(__file__).resolve().parents[2] / "venv" / "bin" / "hwp5html")),
            "/usr/bin/hwp5html",
            "/usr/local/bin/hwp5html",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        try:
            result = subprocess.run(["which", "hwp5html"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _build_libreoffice_env(self, work_dir: Path) -> dict[str, str]:
        """headless 변환에 필요한 LibreOffice 실행 환경을 구성합니다."""
        runtime_dir = work_dir / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["HOME"] = str(work_dir)
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        env["SAL_USE_VCLPLUGIN"] = "svp"
        env["DISPLAY"] = ""
        return env

    def _find_libreoffice(self) -> str | None:
        """LibreOffice 실행 파일 경로를 찾습니다."""
        candidates = [
            '/usr/bin/libreoffice',
            '/usr/bin/soffice',
            '/usr/lib/libreoffice/program/soffice',
            'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
            'C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe',
        ]

        for path in candidates:
            if os.path.exists(path):
                return path

        # which 명령으로 확인
        try:
            result = subprocess.run(
                ['which', 'libreoffice'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        return None

    def _convert_with_libreoffice(self, hwp_path: Path, output_dir: Path) -> Path | None:
        """LibreOffice로 HWP/HWPX를 PDF로 변환합니다."""
        if not self.libreoffice_path:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / ".lo_runtime"
        work_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = work_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.libreoffice_path,
            f"-env:UserInstallation={profile_dir.as_uri()}",
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(hwp_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=self._build_libreoffice_env(work_dir)
            )
        except Exception:
            return None

        converted = output_dir / f"{hwp_path.stem}.pdf"
        if converted.exists():
            return converted

        for candidate in output_dir.glob("*.pdf"):
            if candidate.stem == hwp_path.stem:
                return candidate

        if result.stderr:
            print(f"  ⚠️ LibreOffice 변환 오류: {result.stderr[:200]}")
        return None

    @staticmethod
    def _choose_reportlab_font() -> str:
        """한글 출력 가능한 폰트를 우선 선택하고, 없으면 기본 폰트를 사용합니다."""
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as exc:
            raise RuntimeError(
                "fallback PDF 생성을 위해 reportlab이 필요합니다. `pip install reportlab` 후 다시 시도하세요."
            ) from exc

        candidates = [
            ("NotoSansKR", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            ("NotoSansKR", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
            ("Malgun", "C:\\Windows\\Fonts\\malgun.ttf"),
        ]
        for font_name, font_path in candidates:
            path = Path(font_path)
            if not path.exists():
                continue
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
                return font_name
            except Exception:
                continue
        return "Helvetica"

    @staticmethod
    def _wrap_text_line(line: str, font_name: str, font_size: int, max_width: float) -> list[str]:
        """PDF 렌더링 폭에 맞게 텍스트를 줄바꿈합니다."""
        try:
            from reportlab.pdfbase import pdfmetrics
        except ImportError as exc:
            raise RuntimeError(
                "fallback PDF 생성을 위해 reportlab이 필요합니다. `pip install reportlab` 후 다시 시도하세요."
            ) from exc

        if not line:
            return [""]

        wrapped: list[str] = []
        current = ""
        for ch in line:
            candidate = current + ch
            if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
            current = ch
        if current:
            wrapped.append(current)
        return wrapped or [""]

    def _render_text_pages_to_pdf(
        self,
        pages: list[str],
        output_pdf: Path,
        source_name: str = "",
    ) -> bool:
        """논리 페이지 텍스트를 코드에서 직접 PDF로 렌더링합니다."""
        if not pages:
            return False

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise RuntimeError(
                "fallback PDF 생성을 위해 reportlab이 필요합니다. `pip install reportlab` 후 다시 시도하세요."
            ) from exc

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        font_name = self._choose_reportlab_font()
        font_size = 10
        header_font_size = 9
        margin_x = 40
        margin_y = 48
        page_w, page_h = A4
        max_width = page_w - (margin_x * 2)
        line_height = 14

        pdf = canvas.Canvas(str(output_pdf), pagesize=A4)
        for idx, page_text in enumerate(pages, 1):
            y = page_h - margin_y
            header = f"source: {source_name or output_pdf.stem} | logical page: {idx}"
            pdf.setFont(font_name, header_font_size)
            pdf.drawString(margin_x, y, header)
            y -= (line_height + 4)

            pdf.setFont(font_name, font_size)
            lines = page_text.splitlines() or [page_text]
            for raw in lines:
                for wrapped_line in self._wrap_text_line(raw, font_name, font_size, max_width):
                    if y <= margin_y:
                        pdf.showPage()
                        y = page_h - margin_y
                        pdf.setFont(font_name, header_font_size)
                        pdf.drawString(margin_x, y, header)
                        y -= (line_height + 4)
                        pdf.setFont(font_name, font_size)
                    pdf.drawString(margin_x, y, wrapped_line)
                    y -= line_height
            pdf.showPage()

        pdf.save()
        return output_pdf.exists() and output_pdf.stat().st_size > 0

    def _build_pdf_from_hwp_text(
        self,
        hwp_file: Path,
        output_pdf: Path,
        extracted_text: str | None = None,
    ) -> Path:
        """hwp5txt 텍스트를 사용해 fallback PDF를 생성합니다."""
        extracted = (extracted_text or self._extract_with_hwp5txt(hwp_file)).strip()
        if not extracted:
            raise RuntimeError(
                f"HWP 텍스트 추출 실패(hwp5txt): {hwp_file}"
            )

        logical_pages = self._split_logical_pages(extracted)
        if not logical_pages:
            logical_pages = [extracted]

        rendered = self._render_text_pages_to_pdf(logical_pages, output_pdf, source_name=hwp_file.name)
        if not rendered:
            raise RuntimeError(f"HWP fallback PDF 생성 실패: {hwp_file}")
        return output_pdf

    def _is_pdf_quality_acceptable(self, pdf_path: Path, hwp_text_len: int) -> bool:
        """LibreOffice 변환 결과 품질을 점검합니다."""
        try:
            pages = self.pdf_converter.extract_pages(pdf_path, include_tables=False)
        except Exception:
            return False

        page_count = len(pages)
        text_len = sum(len(str(page.get("content", "") or "").strip()) for page in pages)
        if page_count <= 0 or text_len <= 0:
            return False

        if hwp_text_len <= 2500:
            return page_count >= 1 and text_len >= 800

        # HWP 원문 대비 PDF 추출량이 과도하게 작으면 저품질 변환으로 간주
        min_expected = max(2500, int(hwp_text_len * 0.28))
        return page_count >= 4 and text_len >= min_expected

    def convert_to_pdf(
        self,
        hwp_path: str | Path,
        output_dir: str | Path,
        overwrite: bool = False
    ) -> Path:
        """HWP/HWPX 파일을 PDF로 변환해 저장합니다."""
        hwp_file = Path(hwp_path).resolve()
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        output_pdf = out_dir / f"{hwp_file.stem}.pdf"
        if output_pdf.exists() and not overwrite:
            self.last_pdf_generation_mode = "cached"
            return output_pdf

        hwp_text = self._extract_with_hwp5txt(hwp_file).strip()
        libreoffice_pdf = self._convert_with_libreoffice(hwp_file, out_dir)
        if libreoffice_pdf and libreoffice_pdf.exists():
            if self._is_pdf_quality_acceptable(libreoffice_pdf, len(hwp_text)):
                self.last_pdf_generation_mode = "libreoffice"
                print(f"[HWP->PDF] libreoffice success: {hwp_file.name}")
                return libreoffice_pdf
            print(f"[HWP->PDF] libreoffice output too small, fallback renderer used: {hwp_file.name}")

        if not hwp_text:
            print(f"[HWP->PDF] libreoffice failed and hwp5txt empty: {hwp_file.name}")
        else:
            print(f"[HWP->PDF] libreoffice failed, fallback renderer used: {hwp_file.name}")
        fallback_pdf = self._build_pdf_from_hwp_text(hwp_file, output_pdf, extracted_text=hwp_text)
        self.last_pdf_generation_mode = "fallback_text_render"
        return fallback_pdf

    @staticmethod
    def _split_logical_pages(text: str, max_chars: int = 950) -> list[str]:
        """텍스트를 길이 기준으로 논리 페이지 단위로 분할합니다."""
        raw_lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in raw_lines if line]
        if not lines:
            return []

        pages: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                pages.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len

        if current:
            pages.append("\n".join(current))
        return pages

    @staticmethod
    def _estimate_table_count(text: str) -> int:
        """텍스트 내 표/그림 마커로 표 개수를 추정합니다."""
        if not text:
            return 0
        candidates = [
            len(re.findall(r"<표>", text)),
            len(re.findall(r"\b표\s*\d+\b", text)),
            len(re.findall(r"\|.+\|", text)),
        ]
        return max(candidates) if candidates else 0

    def _extract_with_hwp5txt(self, hwp_path: Path) -> str:
        """hwp5txt로 HWP 텍스트를 추출합니다."""
        if not self.hwp5txt_path:
            return ""
        try:
            result = subprocess.run(
                [self.hwp5txt_path, str(hwp_path)],
                capture_output=True,
                timeout=90,
            )
            if result.returncode != 0:
                return ""
            text = result.stdout.decode("utf-8", errors="ignore").strip()
            cleaned = text.replace("\x00", "")
            cleaned = "".join(
                ch for ch in cleaned
                if (ch.isprintable() or ch in "\n\t\r")
            )
            return normalize_newlines(cleaned)
        except Exception:
            return ""

    def _extract_with_hwp5html(self, hwp_path: Path) -> str:
        """hwp5html로 HWP를 HTML로 변환한 뒤 텍스트를 추출합니다."""
        if not self.hwp5html_path:
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="hwp_html_") as tmp:
                out_dir = Path(tmp)
                result = subprocess.run(
                    [self.hwp5html_path, str(hwp_path), "--output", str(out_dir)],
                    capture_output=True,
                    timeout=180,
                )
                if result.returncode != 0:
                    return ""

                html_path = out_dir / "index.xhtml"
                if not html_path.exists():
                    return ""
                raw = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
        body = (
            body.replace("</p>", "\n")
            .replace("</tr>", "\n")
            .replace("<br/>", "\n")
            .replace("<br>", "\n")
        )
        body = re.sub(r"<[^>]+>", " ", body)
        body = html.unescape(body).replace("\xa0", " ").replace("\x00", "")
        body = normalize_newlines(body)
        lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
        cleaned_lines = [line for line in lines if line]
        return "\n".join(cleaned_lines)

    def extract_pages(self, hwp_path: str | Path) -> list[dict[str, Any]]:
        """HWP/HWPX 문서를 페이지 단위 텍스트/표 정보로 추출합니다."""
        source_path = Path(hwp_path)

        html_text = self._extract_with_hwp5html(source_path)
        if html_text:
            logical_pages = self._split_logical_pages(html_text, max_chars=1800)
            if MAX_PAGES > 0:
                logical_pages = logical_pages[:MAX_PAGES]
            pages: list[dict[str, Any]] = []
            for idx, page_text in enumerate(logical_pages, 1):
                content = normalize_newlines(page_text).strip()
                if not content:
                    continue
                pages.append(
                    {
                        "page": idx,
                        "text": content,
                        "tables": [],
                        "table_count": self._estimate_table_count(content),
                        "content": content,
                    }
                )
            if pages:
                return pages

        with tempfile.TemporaryDirectory(prefix='hwp_convert_') as tmp:
            tmp_dir = Path(tmp)
            pdf_path = self.convert_to_pdf(source_path, tmp_dir, overwrite=True)
            return self.pdf_converter.extract_pages(pdf_path, include_tables=True)

    def convert(self, hwp_path: str | Path, org_name: str | None = None) -> str:
        """HWP를 마크다운으로 변환합니다."""
        path = Path(hwp_path)
        filename = path.name
        org_name = org_name or self.extract_org_name(filename)

        parts = [f"# {org_name}\n"]
        parts.append("## 원본 문서 정보\n")
        parts.append(f"- **파일명**: {filename}\n")
        parts.append("- **파일 형식**: HWP\n")

        pages = self.extract_pages(path)
        if pages:
            total_lines = sum(len((p.get("content") or "").splitlines()) for p in pages)
            total_tables = sum(int(p.get("table_count", 0)) for p in pages)
            parts.append(f"- **추출 페이지 수**: {len(pages)}\n")
            parts.append(f"- **추출된 라인 수**: {total_lines}\n")
            parts.append(f"- **추출된 표 수**: {total_tables}\n")

        parts.append("\n## 문서 내용\n\n")

        if pages:
            for page in pages:
                page_no = page.get("page", "?")
                content = normalize_newlines(str(page.get("content", ""))).strip()
                if content:
                    parts.append(f"### 페이지 {page_no}\n")
                    parts.append(f"{content}\n\n")
        else:
            parts.append("*텍스트 추출 실패 - 파일명 정보만 사용 가능*\n")

        return "".join(parts)

    def _extract_fallback(self, hwp_path: Path) -> str:
        """Fallback: 이진 데이터에서 텍스트 패턴 추출."""
        try:
            import olefile

            if not olefile.isOleFile(hwp_path):
                return ""

            ole = olefile.OleFileIO(hwp_path)
            text_parts = []

            # PrvText (미리보기 텍스트) 시도
            if ole.exists('PrvText'):
                try:
                    prv_text = ole.openstream('PrvText').read()
                    # UTF-16LE 디코딩
                    text = prv_text.decode('utf-16le', errors='ignore')
                    # 프린트 가능한 문자만 추출
                    clean = ''.join(c for c in text if c.isprintable() or c in '\n\t ')
                    if len(clean) > 20:
                        text_parts.append(clean)
                except Exception:
                    pass

            # DocInfo에서 요약 정보 추출
            if ole.exists('DocInfo'):
                try:
                    doc_info = ole.openstream('DocInfo').read()
                    # 문서 제목 등 메타데이터
                    text = doc_info.decode('utf-16le', errors='ignore')
                    clean = ''.join(c for c in text if c.isprintable() or c in '\n\t ')
                    if len(clean) > 20:
                        text_parts.append(clean)
                except Exception:
                    pass

            ole.close()

            if text_parts:
                return normalize_newlines('\n\n'.join(text_parts))

        except Exception:
            pass

        return ""

    @staticmethod
    def extract_org_name(filename: str) -> str:
        """파일명에서 기관명을 추출합니다."""
        parts = filename.replace('.hwp', '').replace('.pdf', '').replace('.hwpx', '').split('_')
        if parts:
            return remove_josa(parts[0].strip())
        return Path(filename).stem

    @staticmethod
    def split_markdown_sections(markdown: str) -> list[str]:
        """마크다운을 섹션 단위로 분할합니다."""
        return markdown.split('## ')

    @staticmethod
    def filter_valid_sections(sections: list[str]) -> list[str]:
        """유효한 섹션만 필터링합니다."""
        return [s for s in sections if len(s.strip()) > MIN_SECTION_LENGTH]
