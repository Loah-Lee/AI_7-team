"""YAML 설정 파일 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """YAML 설정 파일을 로드한다.

    Args:
        config_path: 설정 파일 경로. None이면 configs/default.yaml 사용.

    Returns:
        설정 딕셔너리.
    """
    if config_path is None:
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / "configs" / "default.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
