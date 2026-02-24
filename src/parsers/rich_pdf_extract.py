from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


def _run_command(args: List[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _convert_hwp_to_pdf(hwp_path: Path, output_pdf: Path, *, timeout_s: int = 180) -> Path:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if output_pdf.exists() and output_pdf.stat().st_mtime >= hwp_path.stat().st_mtime:
        _log_ok("convert_hwp_cached", hwp_path, output_pdf)
        return output_pdf

    try:
        result = _run_command(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_pdf.parent),
                str(hwp_path),
            ],
            timeout_s=timeout_s,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("soffice not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"hwp->pdf timeout after {timeout_s}s") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        reason = f"nonzero exit(code={result.returncode})"
        if stderr:
            reason += f" | stderr={stderr[:200]}"
        elif stdout:
            reason += f" | stdout={stdout[:200]}"
        raise RuntimeError(reason)

    generated = output_pdf.parent / f"{hwp_path.stem}.pdf"
    if generated.exists() and generated != output_pdf:
        output_pdf.unlink(missing_ok=True)
        generated.replace(output_pdf)

    if not output_pdf.exists():
        raise RuntimeError(f"converted pdf not found: {output_pdf}")

    _log_ok("convert_hwp", hwp_path, output_pdf)
    return output_pdf


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _build_doc_id_map(pdfs: List[Path], *, input_dir: Path) -> Dict[Path, str]:
    input_root = input_dir.resolve()
    by_stem: Dict[str, List[Path]] = {}
    for pdf in pdfs:
        by_stem.setdefault(pdf.stem, []).append(pdf)

    result: Dict[Path, str] = {}
    for stem, paths in by_stem.items():
        if len(paths) == 1:
            result[paths[0]] = stem
            continue
        for path in paths:
            rel = path.relative_to(input_root).as_posix()
            result[path] = f"{stem}__{_short_hash(rel)}"
    return result


def _ensure_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PyMuPDF(fitz)가 설치되지 않았습니다. pip install pymupdf 로 설치하세요."
        ) from exc


def _is_rendered_on_page(page, xref: int) -> bool:
    """현재 페이지에서 실제로 렌더링된 이미지인지 확인한다."""
    try:
        rects = page.get_image_rects(xref)
    except Exception:
        # 좌표 조회가 실패하면 기존 동작과의 호환을 위해 저장을 허용한다.
        return True
    return bool(rects)


def _extract_images(doc, doc_id: str, assets_root: Path) -> List[Path]:
    assets_dir = assets_root / doc_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Path] = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        images = [img for img in page.get_images(full=True) if _is_rendered_on_page(page, img[0])]
        for img_index, img in enumerate(images, start=1):
            xref = img[0]
            try:
                pix = doc.extract_image(xref)
                image_bytes = pix.get("image")
                ext = pix.get("ext", "png")

                out_path = assets_dir / f"p{page_index + 1}_img{img_index}.png"

                if ext.lower() == "png":
                    out_path.write_bytes(image_bytes)
                else:
                    fitz = _ensure_fitz()
                    pixmap = fitz.Pixmap(doc, xref)
                    if pixmap.n - pixmap.alpha >= 4:  # CMYK 등
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    pixmap.save(out_path.as_posix())
                    pixmap = None

                saved.append(out_path)
            except Exception:
                continue
    return saved


def _build_markdown(doc_id: str, text: str, assets: List[Path]) -> str:
    lines: List[str] = [f"# {doc_id}", "", text.strip()]

    for asset in assets:
        rel_path = Path("..") / "data_assets" / doc_id / asset.name
        lines.append("")
        lines.append(f"![PLACEHOLDER]({rel_path.as_posix()})")

    return "\n".join(lines).strip() + "\n"


def extract_rich(
    input_dir: Path = Path("data_raw"),
    output_root: Path = Path("notebooks") / "data_rich",
    assets_root: Path = Path("notebooks") / "data_assets",
    *,
    max_docs: int | None = None,
    auto_convert_hwp: bool = True,
    hwp_pdf_root_name: str = "_converted_pdf",
) -> Dict[str, int]:
    _log_start(input_dir, output_root)

    if not input_dir.exists():
        exc = FileNotFoundError(f"Input directory not found: {input_dir}")
        _log_fail("scan", input_dir, exc)
        raise exc

    pdfs = [p for p in sorted(input_dir.rglob("*.pdf")) if p.is_file()]
    converted_root = input_dir / hwp_pdf_root_name
    if auto_convert_hwp:
        hwps = [p for p in sorted(input_dir.rglob("*.hwp")) if p.is_file()]
        for hwp in hwps:
            if converted_root in hwp.parents:
                continue
            rel = hwp.relative_to(input_dir)
            out_pdf = (converted_root / rel).with_suffix(".pdf")
            try:
                pdfs.append(_convert_hwp_to_pdf(hwp, out_pdf))
            except Exception as exc:
                _log_fail("convert_hwp", hwp, exc)

    pdfs = sorted({p.resolve() for p in pdfs})
    targets = pdfs if max_docs is None else pdfs[:max_docs]
    doc_id_map = _build_doc_id_map(targets, input_dir=input_dir)

    summary = {"processed": 0, "succeeded": 0, "failed": 0}

    for path in targets:
        summary["processed"] += 1
        try:
            fitz = _ensure_fitz()
            doc = fitz.open(path.as_posix())
            text_parts = [doc.load_page(i).get_text("text") for i in range(len(doc))]
            text = "\n\n".join(t.strip() for t in text_parts if t.strip())

            doc_id = doc_id_map.get(path, path.stem)
            assets = _extract_images(doc, doc_id, assets_root)

            output_root.mkdir(parents=True, exist_ok=True)
            md_path = output_root / f"{doc_id}.md"
            md_path.write_text(_build_markdown(doc_id, text, assets), encoding="utf-8")

            manifest_path = output_root / f"{doc_id}.manifest.json"
            manifest = {
                "doc_id": doc_id,
                "source_pdf": path.as_posix(),
                "markdown_path": md_path.as_posix(),
                "assets": [p.as_posix() for p in assets],
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            _log_ok("extract", path, md_path)
            _log_ok("manifest", path, manifest_path)
            summary["succeeded"] += 1
        except Exception as exc:
            _log_fail("extract", path, exc)
            summary["failed"] += 1

    return summary


if __name__ == "__main__":
    extract_rich()
