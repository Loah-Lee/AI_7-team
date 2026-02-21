from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_MONEY_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:원|만원|천원|억원)\b")
_DATE_RE = re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}\s*월\s*\d{1,2}\s*일\b")
_PERIOD_RE = re.compile(r"\b\d+\s*(?:개월|개월간|일|일간|년)\b")


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s.strip().lower().replace(",", ""))


def _type_match(expected_type: str, answer: str) -> bool:
    if expected_type == "percent":
        return bool(_PERCENT_RE.search(answer))
    if expected_type == "money":
        return bool(_MONEY_RE.search(answer))
    if expected_type == "date":
        return bool(_DATE_RE.search(answer))
    if expected_type == "period":
        return bool(_PERIOD_RE.search(answer))
    return bool(answer.strip())


def evaluate_answers(eval_path: Path, pred_path: Path, out_path: Path, fail_path: Path) -> None:
    truth_rows = list(_iter_jsonl(eval_path))
    truth = {str(r.get("query_id", "")): r for r in truth_rows}

    pred = pd.read_csv(pred_path)
    rows: List[Dict[str, object]] = []
    for _, p in pred.iterrows():
        qid = str(p.get("query_id", ""))
        t = truth.get(qid, {})
        expected_type = str(t.get("expected_type", "text"))
        expected_value = str(t.get("expected_value", "")).strip()
        must_contain = t.get("must_contain", [])
        if not isinstance(must_contain, list):
            must_contain = []

        answer = str(p.get("answer", ""))
        answer_status = str(p.get("answer_status", ""))
        has_citation = int(p.get("has_citation", 0)) if str(p.get("has_citation", "")).strip() else 0

        exact_match = 0
        if expected_value:
            exact_match = int(_normalize(expected_value) in _normalize(answer))

        type_match = int(_type_match(expected_type, answer))

        must_ok = 1
        for token in must_contain:
            tok = str(token).strip()
            if tok and tok not in answer:
                must_ok = 0
                break

        grounded = int(has_citation == 1)
        answered = int(answer_status in {"ok", "partial"})

        rows.append(
            {
                "query_id": qid,
                "query": p.get("query", ""),
                "answer_status": answer_status,
                "expected_type": expected_type,
                "expected_value": expected_value,
                "exact_match": exact_match,
                "type_match": type_match,
                "must_contain_match": must_ok,
                "grounded": grounded,
                "answered": answered,
                "answer": answer,
            }
        )

    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    summary = {
        "queries": len(df),
        "answered_rate": float(df["answered"].mean()) if len(df) else 0.0,
        "grounded_rate": float(df["grounded"].mean()) if len(df) else 0.0,
        "type_match_rate": float(df["type_match"].mean()) if len(df) else 0.0,
        "exact_match_rate(only_labeled)": float(df[df["expected_value"] != ""]["exact_match"].mean()) if len(df[df["expected_value"] != ""]) else None,
    }

    fails = df[(df["type_match"] == 0) | (df["grounded"] == 0)]
    fail_path.parent.mkdir(parents=True, exist_ok=True)
    fails.to_csv(fail_path, index=False)

    print("ANSWER EVAL SUMMARY")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"output={out_path}")
    print(f"fails={len(fails)}")
    print(f"fail_output={fail_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", default="configs/answer_eval_v1.jsonl")
    parser.add_argument("--pred", default="results/node_report_rag_final.csv")
    parser.add_argument("--out", default="results/answer_eval_report.csv")
    parser.add_argument("--fail-out", default="results/fail_answers.csv")
    args = parser.parse_args()

    evaluate_answers(
        eval_path=Path(args.eval_set),
        pred_path=Path(args.pred),
        out_path=Path(args.out),
        fail_path=Path(args.fail_out),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
