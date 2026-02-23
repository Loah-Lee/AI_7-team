import csv
import os
import time
from pathlib import Path
from typing import List, Dict

ABSOLUTE_TIME_THRESHOLD = 60.0
DYNAMIC_TIME_MULTIPLIER = 3.0
DYNAMIC_MIN_SAMPLES = 10


def process_single_pdf(pdf_path: Path, output_dir: Path) -> Dict:
    from parser_step1 import parse_pdf_to_markdown
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

    import json
    for i, chunk in enumerate(chunks):
        chunk['chunk_id'] = i
        chunk['doc_id'] = compute_doc_id(parsed_path)
        chunk_file = chunks_dir / f"chunk_{stem}_{i:05d}.json"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    assign_uids(chunks)

    hierarchy_entries, section_uid_map = build_hierarchy(chunks)
    apply_section_uids(chunks, section_uid_map)

    # Dense와 Sparse(BM25)가 통합되었으므로 하나의 함수만 호출합니다.
    hybrid_count = upsert_hybrid_chunks(chunks)
    hierarchy_count = upsert_hierarchy_chroma(hierarchy_entries)
    # ensure_indexes()는 ChromaDB에서 알아서 처리하므로 삭제되었습니다.

    # CSV Summary 기록을 위해 sparse/dense 카운트를 동일하게 맞춥니다.
    result['sparse_count'] = hybrid_count
    result['dense_count'] = hybrid_count
    result['hierarchy_count'] = hierarchy_count
    result['reindexed'] = True

    if not (result['chunk_count'] == hybrid_count):
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
    data_dir = Path('./data')
    pdf_dir = Path('output/temp_pdf')
    output_dir = Path('output')
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if data_dir.exists():
        for file in data_dir.iterdir():
            if file.suffix == '.hwp':
                if not (pdf_dir / f'{file.stem}.pdf').exists():
                    os.system(f"python hwp_converter.py '{file}' -o '{pdf_dir}'")
            else:
                import shutil
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
