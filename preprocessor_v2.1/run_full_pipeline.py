#!/usr/bin/env python3
"""Full 99-file pipeline run using v2.1.3 modules."""
import sys
import os
import csv
import json
import time
import sqlite3
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

PDF_DIR = PROJECT_ROOT / "output" / "temp_pdf"
OUTPUT_DIR = PROJECT_ROOT / "output"
CHUNKS_DIR = OUTPUT_DIR / "chunks"

ABSOLUTE_TIME_THRESHOLD = 60.0
DYNAMIC_TIME_MULTIPLIER = 3.0
DYNAMIC_MIN_SAMPLES = 10


def check_time_anomaly(duration, history):
    if len(history) < DYNAMIC_MIN_SAMPLES:
        return duration > ABSOLUTE_TIME_THRESHOLD
    avg = sum(history) / len(history)
    return duration > avg * DYNAMIC_TIME_MULTIPLIER


def process_single_pdf(pdf_path, output_dir):
    stem = pdf_path.stem
    result = {
        'file': pdf_path.name,
        'status': 'success',
        'duration_sec': 0.0,
        'chunk_count': 0,
        'sparse_count': 0,
        'dense_count': 0,
        'reindexed': False,
        'error': '',
    }
    t0 = time.time()

    parsed_path = output_dir / f'step1_parsed_{stem}.md'
    parse_pdf_to_markdown(str(pdf_path), str(parsed_path))

    audited_path = output_dir / f'step2_audited_{stem}.md'
    audit_file(str(parsed_path), str(audited_path))

    chunks = process_file(audited_path)
    result['chunk_count'] = len(chunks)

    if len(chunks) == 0:
        result['status'] = 'failed'
        result['error'] = 'zero chunks produced'
        result['duration_sec'] = time.time() - t0
        return result

    chunks_dir = output_dir / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks):
        chunk['chunk_id'] = i
        chunk['doc_id'] = compute_doc_id(parsed_path)
        chunk_file = chunks_dir / f"chunk_{stem}_{i:05d}.json"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    assign_uids(chunks)
    sparse_count = initialize_sparse_db(DB_PATH, chunks)
    dense_count = upsert_dense_vectors(DB_PATH, chunks, EMBEDDING_MODEL)

    result['sparse_count'] = sparse_count
    result['dense_count'] = dense_count
    result['reindexed'] = True

    if not (result['chunk_count'] == sparse_count == dense_count):
        print(f"⚠️ Count mismatch for {pdf_path.name}: "
              f"chunks={result['chunk_count']}, sparse={sparse_count}, dense={dense_count}")

    result['duration_sec'] = time.time() - t0
    return result


def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob('*.pdf'))
    total = len(pdf_files)
    print(f"{'='*60}")
    print(f"Full Pipeline Run: {total} PDF files")
    print(f"DB: {DB_PATH}")
    print(f"{'='*60}\n")

    results = []
    durations = []
    failed = 0

    for idx, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{idx}/{total}] {pdf_path.name}")
        try:
            result = process_single_pdf(pdf_path, OUTPUT_DIR)
        except Exception as e:
            result = {
                'file': pdf_path.name,
                'status': 'failed',
                'duration_sec': 0.0,
                'chunk_count': 0,
                'sparse_count': 0,
                'dense_count': 0,
                'reindexed': False,
                'error': str(e),
            }
            print(f"❌ {pdf_path.name}: {e}")

        results.append(result)

        if result['status'] == 'failed':
            failed += 1
            continue

        if check_time_anomaly(result['duration_sec'], durations):
            print(f"⚠️ Time anomaly: {pdf_path.name} took {result['duration_sec']:.1f}s")
        durations.append(result['duration_sec'])

    summary_path = OUTPUT_DIR / 'execution_summary.csv'
    fieldnames = ['file', 'status', 'duration_sec', 'chunk_count',
                  'sparse_count', 'dense_count', 'reindexed', 'error']
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    ok = total - failed
    total_chunks = sum(r['chunk_count'] for r in results)
    total_sparse = sum(r['sparse_count'] for r in results)
    total_dense = sum(r['dense_count'] for r in results)

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Files: {ok}/{total} succeeded, {failed} failed")
    if durations:
        print(f"Time:  avg={sum(durations)/len(durations):.1f}s, total={sum(durations):.0f}s")
    print(f"Chunks: {total_chunks}")
    print(f"Sparse: {total_sparse}")
    print(f"Dense:  {total_dense}")
    print(f"Summary: {summary_path}")

    if failed > 0:
        print(f"\nFailed files:")
        for r in results:
            if r['status'] == 'failed':
                print(f"  {r['file']}: {r['error']}")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        for table in ['chunks', 'sparse']:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"DB {table}: {count} rows")
            except Exception as e:
                print(f"DB {table}: {e}")

    print(f"\nDB size: {Path(DB_PATH).stat().st_size / (1024*1024):.1f} MB")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
