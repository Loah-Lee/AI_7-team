from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable


def load_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        yield from csv.DictReader(f)
