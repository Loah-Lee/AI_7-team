"""LangSmith 트레이스를 JSON으로 export하는 스크립트.

공유 링크(public share token)와 직접 run ID 모두 지원.

Usage:
    # 공유 링크의 share token으로 export
    uv run python scripts/export_langsmith_traces.py --shared <share_token_1> [share_token_2] ...

    # 직접 run ID로 export (본인 프로젝트)
    uv run python scripts/export_langsmith_traces.py <run_id_1> [run_id_2] ...
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
from langsmith import Client

# 프로젝트 루트의 .env 로드
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.env import load_env

load_env()


def serialize_value(obj):
    """JSON 직렬화할 수 없는 객체 처리."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return str(obj)
    return str(obj)


def export_shared_run(share_token: str) -> dict:
    """공유 링크의 share token으로 트레이스를 가져온다."""
    base_url = "https://api.smith.langchain.com"

    # 공유 run 메타 정보 조회
    resp = httpx.get(f"{base_url}/public/{share_token}/run")
    resp.raise_for_status()
    run = resp.json()

    run_data = {
        "id": run.get("id"),
        "name": run.get("name"),
        "run_type": run.get("run_type"),
        "status": run.get("status"),
        "inputs": run.get("inputs"),
        "outputs": run.get("outputs"),
        "error": run.get("error"),
        "start_time": run.get("start_time"),
        "end_time": run.get("end_time"),
        "total_tokens": run.get("total_tokens"),
        "prompt_tokens": run.get("prompt_tokens"),
        "completion_tokens": run.get("completion_tokens"),
        "extra": run.get("extra"),
        "tags": run.get("tags"),
        "feedback_stats": run.get("feedback_stats"),
    }

    # child runs
    children = []
    try:
        child_resp = httpx.get(f"{base_url}/public/{share_token}/runs")
        child_resp.raise_for_status()
        child_runs = child_resp.json()

        if isinstance(child_runs, list):
            for child in child_runs:
                children.append({
                    "id": child.get("id"),
                    "name": child.get("name"),
                    "run_type": child.get("run_type"),
                    "status": child.get("status"),
                    "inputs": child.get("inputs"),
                    "outputs": child.get("outputs"),
                    "error": child.get("error"),
                    "start_time": child.get("start_time"),
                    "end_time": child.get("end_time"),
                    "total_tokens": child.get("total_tokens"),
                    "prompt_tokens": child.get("prompt_tokens"),
                    "completion_tokens": child.get("completion_tokens"),
                    "extra": child.get("extra"),
                    "tags": child.get("tags"),
                })
    except Exception as e:
        print(f"  [warning] child runs 조회 실패: {e}")

    run_data["children"] = children
    return run_data


def export_run(client: Client, run_id: str) -> dict:
    """단일 run과 하위 child run들을 dict로 변환."""
    run = client.read_run(run_id)

    run_data = {
        "id": str(run.id),
        "name": run.name,
        "run_type": run.run_type,
        "status": run.status,
        "inputs": run.inputs,
        "outputs": run.outputs,
        "error": run.error,
        "start_time": run.start_time.isoformat() if run.start_time else None,
        "end_time": run.end_time.isoformat() if run.end_time else None,
        "latency_seconds": (
            (run.end_time - run.start_time).total_seconds()
            if run.start_time and run.end_time
            else None
        ),
        "total_tokens": run.total_tokens,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "extra": run.extra,
        "tags": run.tags,
        "feedback_stats": run.feedback_stats,
    }

    # child runs 가져오기
    children = []
    try:
        for child in client.list_runs(
            project_name=run.session_name if hasattr(run, "session_name") else None,
            parent_run_id=run_id,
        ):
            child_data = {
                "id": str(child.id),
                "name": child.name,
                "run_type": child.run_type,
                "status": child.status,
                "inputs": child.inputs,
                "outputs": child.outputs,
                "error": child.error,
                "start_time": child.start_time.isoformat() if child.start_time else None,
                "end_time": child.end_time.isoformat() if child.end_time else None,
                "latency_seconds": (
                    (child.end_time - child.start_time).total_seconds()
                    if child.start_time and child.end_time
                    else None
                ),
                "total_tokens": child.total_tokens,
                "prompt_tokens": child.prompt_tokens,
                "completion_tokens": child.completion_tokens,
                "extra": child.extra,
                "tags": child.tags,
            }

            # child의 child도 가져오기 (2단계)
            grandchildren = []
            for gc in client.list_runs(
                project_name=run.session_name if hasattr(run, "session_name") else None,
                parent_run_id=str(child.id),
            ):
                grandchildren.append({
                    "id": str(gc.id),
                    "name": gc.name,
                    "run_type": gc.run_type,
                    "status": gc.status,
                    "inputs": gc.inputs,
                    "outputs": gc.outputs,
                    "error": gc.error,
                    "latency_seconds": (
                        (gc.end_time - gc.start_time).total_seconds()
                        if gc.start_time and gc.end_time
                        else None
                    ),
                    "total_tokens": gc.total_tokens,
                    "prompt_tokens": gc.prompt_tokens,
                    "completion_tokens": gc.completion_tokens,
                })

            if grandchildren:
                child_data["children"] = grandchildren
            children.append(child_data)
    except Exception as e:
        print(f"  [warning] child runs 조회 실패: {e}")

    run_data["children"] = children
    return run_data


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  공유 링크: python scripts/export_langsmith_traces.py --shared <token1> [token2]")
        print("  직접 run:  python scripts/export_langsmith_traces.py <run_id1> [run_id2]")
        sys.exit(1)

    output_dir = Path(__file__).resolve().parents[1] / "data" / "traces"
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_mode = sys.argv[1] == "--shared"
    ids = sys.argv[2:] if shared_mode else sys.argv[1:]

    if shared_mode:
        for token in ids:
            print(f"\n--- Exporting shared trace: {token} ---")
            try:
                run_data = export_shared_run(token)
                output_file = output_dir / f"trace_{token[:8]}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(run_data, f, ensure_ascii=False, indent=2, default=serialize_value)
                print(f"  -> 저장: {output_file}")
            except Exception as e:
                print(f"  [error] {e}")
    else:
        client = Client()
        for run_id in ids:
            print(f"\n--- Exporting run: {run_id} ---")
            try:
                run_data = export_run(client, run_id)
                output_file = output_dir / f"trace_{run_id[:8]}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(run_data, f, ensure_ascii=False, indent=2, default=serialize_value)
                print(f"  -> 저장: {output_file}")
            except Exception as e:
                print(f"  [error] {e}")

    print(f"\n완료! 파일 위치: {output_dir}")


if __name__ == "__main__":
    main()
