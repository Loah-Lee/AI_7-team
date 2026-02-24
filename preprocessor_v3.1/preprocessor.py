import csv
import argparse
import json
import os
import shutil
import time
import unicodedata
from pathlib import Path
from typing import List, Dict

ABSOLUTE_TIME_THRESHOLD = 60.0
DYNAMIC_TIME_MULTIPLIER = 3.0
DYNAMIC_MIN_SAMPLES = 10


def _documents_to_parsed_markdown(docs: list, source_name: str, output_path: Path) -> None:
    """pdf_loader 출력(List[Document]) → <<PAGE: N>> 마커 포함 markdown 파일 변환."""
    title = unicodedata.normalize('NFC', output_path.stem)
    title = title.replace('step1_parsed_', '')
    total_pages = max((d.metadata.get('page', 1) for d in docs), default=1) if docs else 0

    lines = [
        '---',
        f'document_title: "{title}"',
        f'source_file: "{source_name}"',
        f'total_pages: {total_pages}',
        '---',
        '',
    ]

    for doc in docs:
        page = doc.metadata.get('page', 1)
        lines.append(f'<<PAGE: {page}>>')
        lines.append('')
        lines.append(doc.page_content)
        lines.append('')

    output_path.write_text('\n'.join(lines), encoding='utf-8')


def process_single_pdf(pdf_path: Path, output_dir: Path) -> Dict:
    from pdf_loader import load_pdf
    from auditor_step2 import audit_file
    from chunker_step4 import process_file
    from storage_step5 import (
        compute_doc_id, assign_uids, build_hierarchy, apply_section_uids,
        upsert_hybrid_chunks, upsert_hierarchy_chroma
    )

    stem = pdf_path.stem
    result = {
        'file': pdf_path.name,
        'status': 'success',
        'duration_sec': 0.0,
        'chunk_count': 0,
        'sparse_count': 0,
        'dense_count': 0,
        'hierarchy_count': 0,
        'reindexed': False,
        'error': '',
    }
    t0 = time.time()

    # Step 1: PDF → markdown (pdf_loader 기반)
    parsed_path = output_dir / f'step1_parsed_{stem}.md'
    docs = load_pdf(pdf_path)
    _documents_to_parsed_markdown(docs, pdf_path.name, parsed_path)

    # Step 2: Auditor
    audited_path = output_dir / f'step2_audited_{stem}.md'
    audit_file(str(parsed_path), str(audited_path))

    # Step 3-7: Chunker
    chunks = process_file(audited_path)
    result['chunk_count'] = len(chunks)

    if len(chunks) == 0:
        result['status'] = 'failed'
        result['error'] = 'zero chunks produced'
        result['duration_sec'] = time.time() - t0
        return result

    # Chunk 저장 + doc_id 할당
    chunks_dir = output_dir / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks):
        chunk['chunk_id'] = i
        chunk['doc_id'] = compute_doc_id(parsed_path)
        chunk_file = chunks_dir / f"chunk_{stem}_{i:05d}.json"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    # UID + Hierarchy
    assign_uids(chunks)
    hierarchy_entries, section_uid_map = build_hierarchy(chunks)
    apply_section_uids(chunks, section_uid_map)

    # Storage (ChromaDB)
    hybrid_count = upsert_hybrid_chunks(chunks)
    hierarchy_count = upsert_hierarchy_chroma(hierarchy_entries)

    result['sparse_count'] = hybrid_count
    result['dense_count'] = hybrid_count
    result['hierarchy_count'] = hierarchy_count
    result['reindexed'] = True

    if result['chunk_count'] != hybrid_count:
        print(f"⚠️ Count mismatch for {pdf_path.name}: "
              f"chunks={result['chunk_count']}, inserted={hybrid_count}")

    result['duration_sec'] = time.time() - t0
    return result


def check_time_anomaly(
    duration: float,
    history: List[float],
) -> bool:
    if len(history) < DYNAMIC_MIN_SAMPLES:
        return duration > ABSOLUTE_TIME_THRESHOLD
    avg = sum(history) / len(history)
    return duration > avg * DYNAMIC_TIME_MULTIPLIER


def write_summary(results: List[Dict], output_path: Path) -> None:
    fieldnames = ['file', 'status', 'duration_sec', 'chunk_count',
                  'sparse_count', 'dense_count', 'hierarchy_count',
                  'reindexed', 'error']
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"📄 Summary written to {output_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preprocessor v3.1 Pipeline')
    parser.add_argument('--input', '-i', type=str, default=None,
                        help='입력 폴더 경로 (기본값: <프로젝트 루트>/data)')
    args = parser.parse_args()
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    data_dir = Path(args.input).resolve() if args.input else PROJECT_ROOT / 'data'
    pdf_dir = PROJECT_ROOT / 'output' / 'temp_pdf'
    output_dir = PROJECT_ROOT / 'output'
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if data_dir.exists():
        for file in data_dir.iterdir():
            if file.suffix == '.hwp':
                if not (pdf_dir / f'{file.stem}.pdf').exists():
                    os.system(f"python '{PROJECT_ROOT / 'hwp_converter.py'}' '{file}' -o '{pdf_dir}'")
            else:
                shutil.copy2(file, pdf_dir / file.name)

    pdf_files = sorted(pdf_dir.glob('*.pdf'))
    print(f"Found {len(pdf_files)} PDF files\n")

    results: List[Dict] = []
    durations: List[float] = []
    failed = 0

    for pdf_path in pdf_files:
        try:
            result = process_single_pdf(pdf_path, output_dir)
        except Exception as e:
            result = {
                'file': pdf_path.name,
                'status': 'failed',
                'duration_sec': 0.0,
                'chunk_count': 0,
                'sparse_count': 0,
                'dense_count': 0,
                'hierarchy_count': 0,
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

    write_summary(results, output_dir / 'execution_summary.csv')

    total = len(results)
    ok = total - failed
    print(f"\n{'='*60}")
    print(f"✅ Complete: {ok}/{total} succeeded, {failed} failed")
    if durations:
        print(f"   Avg time: {sum(durations)/len(durations):.1f}s, "
              f"Total: {sum(durations):.0f}s")
    print(f"{'='*60}")
