from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _is_asset_chunk(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    return (
        "../data_assets/" in t
        or t.lstrip().startswith("![")
        or '"type": "table"' in t
        or '"type":"table"' in t
        or "캡션" in t
        or "그림" in t
        or "도표" in t
    )


def build_asset_chunks(*, input_dir: Path, output_dir: Path) -> Dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"total": 0, "kept": 0}

    for src in sorted(input_dir.rglob("*.jsonl")):
        rel = src.relative_to(input_dir)
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        with dst.open("w", encoding="utf-8") as wf:
            for row in _iter_jsonl(src):
                stats["total"] += 1
                text = str(row.get("text", ""))
                if not _is_asset_chunk(text):
                    continue
                wf.write(json.dumps(row, ensure_ascii=False) + "\n")
                stats["kept"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(Path("notebooks") / "data_chunks_rich"))
    parser.add_argument("--output-dir", default=str(Path("notebooks") / "data_chunks_rich_asset_v1"))
    args = parser.parse_args()

    stats = build_asset_chunks(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
    )
    print("INGEST OK | build_asset_chunks")
    print(f"input={Path(args.input_dir)}")
    print(f"output={Path(args.output_dir)}")
    print(f"total={stats['total']} kept={stats['kept']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
