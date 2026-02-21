from __future__ import annotations

import re
from typing import Dict, Iterable, List


def extract_org_prefix(query: str) -> str | None:
    toks = query.strip().split()
    if not toks:
        return None
    cand = toks[0]
    if re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|원)$", cand) or cand.startswith("한국"):
        return cand
    return None


def filter_by_org(rows: Iterable[Dict[str, object]], org: str | None) -> List[Dict[str, object]]:
    if not org:
        return list(rows)
    out: List[Dict[str, object]] = []
    for row in rows:
        source_path = str(row.get("source_path", ""))
        if org in source_path:
            out.append(row)
    return out
