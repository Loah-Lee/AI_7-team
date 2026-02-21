from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class QueryIntent:
    raw_query: str
    query_type: str = "generic"
    keywords: List[str] = field(default_factory=list)


@dataclass
class OrgInfo:
    org_name: str = ""
    matched: bool = False


@dataclass
class ChatState:
    intent: QueryIntent
    org: OrgInfo
    contexts: List[Dict[str, object]] = field(default_factory=list)
    answer: str = ""
    status: str = "not_found"
    citations: List[int] = field(default_factory=list)
