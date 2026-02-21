from __future__ import annotations

import re


def preview(text: str, max_len: int = 200) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    return s if len(s) <= max_len else s[:max_len] + "..."
