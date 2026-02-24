#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import subprocess
import time
from collections import Counter
from pathlib import Path

import chromadb

DB_PATH = Path('data/chroma_db_v17_v2_p120').resolve()
COLLECTION = 'rfp_docs_v17_openai'
LOG_PATH = Path('tmp/progress_tracker.log')
SAMPLE_SEC = 300


def total_docs() -> int:
    base = Path('data/files')
    exts = {'.pdf', '.hwp', '.hwpx'}
    return sum(1 for p in base.iterdir() if p.is_file() and p.suffix.lower() in exts)


def db_stats(client: chromadb.PersistentClient) -> tuple[int, dict[str, int]]:
    col = client.get_collection(COLLECTION)
    metas = col.get(include=['metadatas']).get('metadatas', [])
    ctr = Counter((m or {}).get('type', '?') for m in metas)
    sources = {(m or {}).get('source', '') for m in metas if (m or {}).get('type') in {'pdf', 'hwp'}}
    sources.discard('')
    return len(sources), dict(ctr)


def active_hwp5html() -> tuple[int, str]:
    proc = subprocess.run(
        "ps -ef | rg 'hwp5html' -S | rg -v 'rg hwp5html'",
        shell=True,
        text=True,
        capture_output=True,
    )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return 0, '-'
    return len(lines), lines[0]


def fmt_eta(minutes: float | None) -> str:
    if minutes is None:
        return 'unknown'
    if minutes < 0:
        return '0m'
    if minutes < 1:
        return '<1m'
    h = int(minutes // 60)
    m = int(round(minutes % 60))
    if h:
        return f'{h}h {m}m'
    return f'{m}m'


def main() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_PATH))
    total = total_docs()

    start_ts = dt.datetime.now()
    history: list[tuple[dt.datetime, int]] = []

    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(f"\n=== progress tracker start {start_ts.strftime('%F %T')} ===\n")
        f.write(f"db={DB_PATH} collection={COLLECTION} total_docs={total}\n")

        while True:
            now = dt.datetime.now()
            indexed, types = db_stats(client)
            hwp_count, hwp_line = active_hwp5html()
            history.append((now, indexed))

            # recent 3-sample average speed (docs/min)
            eta_min: float | None = None
            if len(history) >= 3:
                t0, c0 = history[-3]
                t1, c1 = history[-1]
                minutes = (t1 - t0).total_seconds() / 60.0
                delta = c1 - c0
                if minutes > 0 and delta > 0:
                    speed = delta / minutes
                    remaining = max(0, total - indexed)
                    eta_min = remaining / speed if speed > 0 else None

            prev_indexed = history[-2][1] if len(history) >= 2 else indexed
            delta_latest = indexed - prev_indexed
            pct = (indexed / total * 100.0) if total else 0.0

            line = (
                f"[{now.strftime('%F %T')}] indexed={indexed}/{total} ({pct:.1f}%) "
                f"delta={delta_latest:+d} hwp5html={hwp_count} eta={fmt_eta(eta_min)} "
                f"types={types} active={hwp_line}"
            )
            print(line, flush=True)
            f.write(line + "\n")
            f.flush()

            if indexed >= total and hwp_count == 0:
                end_ts = dt.datetime.now()
                elapsed_min = (end_ts - start_ts).total_seconds() / 60.0
                done = (
                    f"DONE at {end_ts.strftime('%F %T')} elapsed={elapsed_min:.1f}m "
                    f"indexed={indexed}/{total}"
                )
                print(done, flush=True)
                f.write(done + "\n")
                f.flush()
                break

            time.sleep(SAMPLE_SEC)


if __name__ == '__main__':
    main()
