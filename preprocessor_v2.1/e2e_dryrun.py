#!/usr/bin/env python3
"""v2.1.2 E2E dry-run: parser → auditor → chunker → storage on 3 samples."""
import sys
import os
import json
import sqlite3
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))

os.chdir(PROJECT_ROOT)

from parser_step1 import parse_pdf_to_markdown
from auditor_step2 import audit_file
from chunker_step4 import process_file
from storage_step5 import (
    compute_doc_id, assign_uids, initialize_sparse_db,
    upsert_dense_vectors, DB_PATH, EMBEDDING_MODEL,
)

SAMPLES = ["sample1", "sample20", "sample50"]
PDF_DIR = PROJECT_ROOT / "output" / "temp_pdf"
OUTPUT_DIR = PROJECT_ROOT / "output"
CHUNKS_DIR = OUTPUT_DIR / "chunks"
TEST_DB = PROJECT_ROOT / "DB" / "document_dryrun.db"

DB_OVERRIDE = str(TEST_DB)


def run_pipeline(stem: str):
    pdf_path = PDF_DIR / f"{stem}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    parsed_path = OUTPUT_DIR / f"step1_parsed_{stem}.md"
    parse_pdf_to_markdown(str(pdf_path), str(parsed_path))

    audited_path = OUTPUT_DIR / f"step2_audited_{stem}.md"
    audit_file(str(parsed_path), str(audited_path))

    chunks = process_file(audited_path)
    if len(chunks) == 0:
        raise RuntimeError(f"Zero chunks produced for {stem}")

    for i, chunk in enumerate(chunks):
        chunk['chunk_id'] = i
        chunk['doc_id'] = compute_doc_id(parsed_path)

    assign_uids(chunks)

    sparse_count = initialize_sparse_db(DB_OVERRIDE, chunks)
    dense_count = upsert_dense_vectors(DB_OVERRIDE, chunks, EMBEDDING_MODEL)

    return {
        'stem': stem,
        'chunk_count': len(chunks),
        'sparse_count': sparse_count,
        'dense_count': dense_count,
        'chunks': chunks,
    }


def verify(results):
    all_ok = True
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    for r in results:
        stem = r['stem']
        print(f"\n--- {stem} ---")

        if r['chunk_count'] == 0:
            print(f"  FAIL: chunk_count == 0")
            all_ok = False
        else:
            print(f"  OK: chunk_count = {r['chunk_count']}")

        missing_doc_id = 0
        unknown_doc_id = 0
        missing_meta_doc_id = 0
        for c in r['chunks']:
            if 'doc_id' not in c:
                missing_doc_id += 1
            elif c['doc_id'] == 'unknown':
                unknown_doc_id += 1
            meta = c.get('metadata', {})
            if 'doc_id' not in meta:
                missing_meta_doc_id += 1

        if missing_doc_id > 0:
            print(f"  FAIL: {missing_doc_id} chunks missing doc_id")
            all_ok = False
        else:
            print(f"  OK: all chunks have doc_id")

        if unknown_doc_id > 0:
            print(f"  FAIL: {unknown_doc_id} chunks with doc_id='unknown'")
            all_ok = False
        else:
            print(f"  OK: no 'unknown' doc_id")

        if missing_meta_doc_id > 0:
            print(f"  FAIL: {missing_meta_doc_id} chunks missing metadata.doc_id")
            all_ok = False
        else:
            print(f"  OK: all metadata.doc_id present")

        if r['sparse_count'] != r['dense_count']:
            print(f"  FAIL: sparse({r['sparse_count']}) != dense({r['dense_count']})")
            all_ok = False
        else:
            print(f"  OK: sparse == dense == {r['sparse_count']}")

        if r['chunk_count'] != r['sparse_count']:
            print(f"  WARN: chunk_count({r['chunk_count']}) != sparse({r['sparse_count']})")

    print("\n" + "=" * 60)
    if all_ok:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
    print("=" * 60)

    return all_ok


def main():
    if TEST_DB.exists():
        TEST_DB.unlink()
    TEST_DB.parent.mkdir(exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for stem in SAMPLES:
        print(f"\n{'='*60}")
        print(f"Processing: {stem}")
        print(f"{'='*60}")
        r = run_pipeline(stem)
        results.append(r)

    passed = verify(results)

    print(f"\nDry-run DB: {TEST_DB}")
    print(f"DB size: {TEST_DB.stat().st_size / 1024:.1f} KB")

    with sqlite3.connect(DB_OVERRIDE) as conn:
        cursor = conn.cursor()
        for table in ['chunks', 'sparse']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"  {table} rows: {count}")
            except Exception as e:
                print(f"  {table}: {e}")

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
