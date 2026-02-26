#!/usr/bin/env python3
"""Repair Chroma metadata using source name and CSV metadata.

Default behavior:
- normalize `source` to filename stem (no extension)
- backfill `source_ext` from source suffix or `data/data_list.csv`
- keep existing `type` as-is

Optional:
- `--materialize-type` updates `type` to pdf/hwp/csv using inferred extension
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import chromadb

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT_PATH))

from src.utils.config import CHROMA_COLLECTION, CHROMA_PATH, PROJECT_ROOT


def _normalize_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", (text or "").lower())
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", normalized)


def _normalize_ext(value: str | None) -> str:
    ext = str(value or "").strip().lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    if ext in {"hwp", "hwpx"}:
        return "hwp"
    if ext == "csv":
        return "csv"
    return ""


def _load_source_ext_index(csv_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    by_stem: dict[str, str] = {}
    by_key: dict[str, str] = {}
    if not csv_path.exists():
        return by_stem, by_key

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not isinstance(row, dict):
                continue
            filename = str(row.get("파일명") or row.get("filename") or "").strip()
            if not filename:
                continue
            suffix_ext = _normalize_ext(Path(filename).suffix)
            format_ext = _normalize_ext(
                str(row.get("파일형식") or row.get("file_format") or row.get("source_ext") or "")
            )
            ext = suffix_ext or format_ext
            if not ext:
                continue
            stem = Path(filename).stem.strip()
            if not stem:
                continue
            by_stem.setdefault(stem.lower(), ext)
            key = _normalize_key(stem)
            if key:
                by_key.setdefault(key, ext)
    return by_stem, by_key


def _infer_source_and_ext(
    metadata: dict[str, Any],
    by_stem: dict[str, str],
    by_key: dict[str, str],
) -> tuple[str, str]:
    source_raw = str(
        metadata.get("source")
        or metadata.get("source_file")
        or metadata.get("filename")
        or ""
    ).strip()
    source_name = Path(source_raw).name if source_raw else ""
    source_suffix_ext = _normalize_ext(Path(source_name).suffix if source_name else "")
    source_stem = (Path(source_name).stem if source_name else source_raw).strip()

    source_norm = source_stem if source_stem else source_raw
    inferred_ext = source_suffix_ext
    if not inferred_ext and source_norm:
        inferred_ext = by_stem.get(source_norm.lower(), "")
        if not inferred_ext:
            inferred_ext = by_key.get(_normalize_key(source_norm), "")
    return source_norm, inferred_ext


def _iter_batches(collection: Any, batch_size: int) -> tuple[list[str], list[dict[str, Any]]]:
    total = int(collection.count())
    offset = 0
    while offset < total:
        payload = collection.get(include=["metadatas"], limit=batch_size, offset=offset)
        ids = payload.get("ids", []) or []
        metadatas = payload.get("metadatas", []) or []
        if not ids:
            break
        yield ids, metadatas
        offset += len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair Chroma metadata by source name/CSV mapping.")
    parser.add_argument("--db-path", type=str, default=str(CHROMA_PATH), help="Chroma directory path")
    parser.add_argument("--collection", type=str, default=str(CHROMA_COLLECTION), help="Collection name")
    parser.add_argument("--csv-path", type=str, default=str(PROJECT_ROOT / "data" / "data_list.csv"))
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--apply", action="store_true", help="Apply updates to Chroma (default: dry-run)")
    parser.add_argument(
        "--materialize-type",
        action="store_true",
        help="Also update metadata.type using inferred extension",
    )
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=args.db_path)
    collection = client.get_collection(args.collection)
    by_stem, by_key = _load_source_ext_index(Path(args.csv_path))

    total = int(collection.count())
    scanned = 0
    changed = 0
    source_normalized = 0
    ext_filled = 0
    type_materialized = 0

    for ids, metadatas in _iter_batches(collection, batch_size=max(1, args.batch_size)):
        update_ids: list[str] = []
        update_metas: list[dict[str, Any]] = []

        for doc_id, meta in zip(ids, metadatas):
            scanned += 1
            if not isinstance(meta, dict):
                continue
            current = dict(meta)
            source_norm, inferred_ext = _infer_source_and_ext(current, by_stem, by_key)
            new_meta = dict(current)
            did_change = False

            if source_norm and str(current.get("source", "") or "").strip() != source_norm:
                new_meta["source"] = source_norm
                source_normalized += 1
                did_change = True

            current_ext = _normalize_ext(str(current.get("source_ext", "") or ""))
            if inferred_ext and not current_ext:
                new_meta["source_ext"] = inferred_ext
                ext_filled += 1
                did_change = True

            if args.materialize_type and inferred_ext:
                new_type = "hwp" if inferred_ext == "hwp" else inferred_ext
                old_type = str(current.get("type", "") or "").strip().lower()
                if old_type != new_type:
                    new_meta["type"] = new_type
                    type_materialized += 1
                    did_change = True

            if did_change:
                changed += 1
                update_ids.append(str(doc_id))
                update_metas.append(new_meta)

        if args.apply and update_ids:
            collection.update(ids=update_ids, metadatas=update_metas)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] collection={args.collection} total={total} scanned={scanned}")
    print(
        f"[{mode}] changed={changed} source_normalized={source_normalized} "
        f"source_ext_filled={ext_filled} type_materialized={type_materialized}"
    )


if __name__ == "__main__":
    main()
