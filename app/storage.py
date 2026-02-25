from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


DATA_DIR = Path(__file__).parent / "data"
STORE_FILE = DATA_DIR / "workspace_store.json"


def _default_store() -> dict[str, Any]:
    return {
        "projects": [],
        "items": [],
    }


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE_FILE.exists():
        STORE_FILE.write_text(json.dumps(_default_store(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_store() -> dict[str, Any]:
    ensure_store()
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_store()


def save_store(store: dict[str, Any]) -> None:
    ensure_store()
    STORE_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def list_projects(store: dict[str, Any]) -> list[dict[str, Any]]:
    return list(store.get("projects", []))


def add_project(store: dict[str, Any], name: str) -> dict[str, Any]:
    project = {
        "id": str(uuid4()),
        "name": name.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    store.setdefault("projects", []).append(project)
    save_store(store)
    return project


def delete_project(store: dict[str, Any], project_id: str) -> None:
    store["projects"] = [p for p in store.get("projects", []) if p.get("id") != project_id]
    store["items"] = [i for i in store.get("items", []) if i.get("project_id") != project_id]
    save_store(store)


def add_item(store: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": str(uuid4()),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        **item,
    }
    store.setdefault("items", []).append(payload)
    save_store(store)
    return payload


def items_by_project(store: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [i for i in store.get("items", []) if i.get("project_id") == project_id]
