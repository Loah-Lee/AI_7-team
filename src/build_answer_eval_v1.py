from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _expected_type(query: str) -> str:
    q = query.strip()
    if re.search(r"비율|퍼센트|%", q):
        return "percent"
    if re.search(r"예산|금액|비용|얼마", q):
        return "money"
    if re.search(r"마감|일자|언제|날짜", q):
        return "date"
    if re.search(r"기간|며칠|몇\s*개월", q):
        return "period"
    return "text"


def build_answer_eval(input_path: Path, output_path: Path) -> Path:
    rows = []
    for item in _iter_jsonl(input_path):
        query_id = str(item.get("query_id", "")).strip()
        query = str(item.get("query", "")).strip()
        if not query_id or not query:
            continue
        rows.append(
            {
                "query_id": query_id,
                "query": query,
                "expected_type": _expected_type(query),
                "expected_value": "",
                "must_contain": [],
                "notes": "fill expected_value manually if strict exact-match is required",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"INGEST OK | build_answer_eval_v1 | {input_path} -> {output_path} | queries={len(rows)}"
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="configs/eval_queries_v2_rich.jsonl")
    parser.add_argument("--output", default="configs/answer_eval_v1.jsonl")
    args = parser.parse_args()

    build_answer_eval(Path(args.input), Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
