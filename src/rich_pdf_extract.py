from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


def _ensure_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PyMuPDF(fitz)가 설치되지 않았습니다. pip install pymupdf 로 설치하세요."
        ) from exc


def _extract_images(doc, doc_id: str, assets_root: Path) -> List[Path]:
    assets_dir = assets_root / doc_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Path] = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        images = page.get_images(full=True)
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
    max_docs: int = 3,
) -> Dict[str, int]:
    _log_start(input_dir, output_root)

    if not input_dir.exists():
        exc = FileNotFoundError(f"Input directory not found: {input_dir}")
        _log_fail("scan", input_dir, exc)
        raise exc

    pdfs = [p for p in sorted(input_dir.rglob("*.pdf")) if p.is_file()]
    targets = pdfs[:max_docs]

    summary = {"processed": 0, "succeeded": 0, "failed": 0}

    for path in targets:
        summary["processed"] += 1
        try:
            fitz = _ensure_fitz()
            doc = fitz.open(path.as_posix())
            text_parts = [doc.load_page(i).get_text("text") for i in range(len(doc))]
            text = "\n\n".join(t.strip() for t in text_parts if t.strip())

            doc_id = path.stem
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
