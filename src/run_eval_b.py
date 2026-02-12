from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval_harness import run_eval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(Path("configs") / "eval_runtime_b.json"),
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    run_eval(
        input_path=Path(cfg.get("input_path", "configs/eval_queries_v2_rich.jsonl")),
        k=int(cfg.get("k", 10)),
        rerank_mode=str(cfg.get("rerank_mode", "none")),
        llm_model=str(cfg.get("llm_model", "gpt-5-nano")),
        variant=str(cfg.get("variant", "B")),
        retriever=str(cfg.get("retriever", "hybrid")),
        hybrid_alpha=float(cfg.get("hybrid_alpha", 0.8)),
        tune_alpha=bool(cfg.get("tune_alpha", False)),
        table_multiplier=float(cfg.get("table_multiplier", 1.2)),
        dense_index_b=Path(cfg.get("dense_index_b", "data_index/dense_B")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
