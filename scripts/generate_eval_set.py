"""평가셋(Ground Truth Q&A) 자동 생성 스크립트.

ChromaDB에서 고품질 청크를 샘플링하고, LLM이 Q&A 쌍을 생성하여
eval_resources/eval_dataset.yaml에 저장한다.

실행: uv run python scripts/generate_eval_set.py
      uv run python scripts/generate_eval_set.py --num_pairs 30
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import yaml
from langchain_openai import ChatOpenAI

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


def _get_eval_dir() -> Path:
    """평가 결과 디렉토리 경로를 반환한다. 환경변수 우선, 없으면 eval_resources (fallback: eval)."""
    if custom_dir := os.getenv("EVAL_DIR"):
        return project_root / custom_dir

    eval_resources = project_root / "eval_resources"
    eval_legacy = project_root / "eval"

    if eval_resources.exists():
        return eval_resources
    elif eval_legacy.exists():
        print(f"[WARNING] 'eval/' 폴더가 감지되었습니다. 'eval_resources/'로 이름을 변경하는 것을 권장합니다.")
        return eval_legacy
    else:
        return eval_resources

from src.retrievers.vectorstore import get_vectorstore
from src.utils.config import load_config
from src.utils.env import get_openai_api_key, load_env

# 질문 유형별 비율
QUERY_TYPE_WEIGHTS = {
    "single_doc": 0.6,
    "multi_doc": 0.2,
    "comparison": 0.2,
}

GENERATION_PROMPT_SINGLE = """\
아래는 RFP(제안요청서) 문서에서 추출한 텍스트 청크입니다.

[출처: {source}, 페이지: {page}]
---
{content}
---

이 텍스트를 기반으로 **1개의 Q&A 쌍**을 만들어 주세요.

규칙:
1. 질문은 이 텍스트에서만 답할 수 있는 구체적인 사실 질문이어야 합니다.
2. 답변은 텍스트에 근거하여 간결하게 (1~2문장) 작성합니다.
3. 질문에 기관명이나 사업명을 포함하여 맥락이 명확하게 합니다.

반드시 아래 JSON 형식으로만 응답하세요 (마크다운 없이):
{{"question": "...", "expected_answer": "..."}}
"""

GENERATION_PROMPT_MULTI = """\
아래는 서로 다른 RFP 문서에서 추출한 텍스트 청크 2개입니다.

[청크 1 - 출처: {source1}, 페이지: {page1}]
---
{content1}
---

[청크 2 - 출처: {source2}, 페이지: {page2}]
---
{content2}
---

이 두 청크를 활용하여 **1개의 {query_type_desc} Q&A 쌍**을 만들어 주세요.

규칙:
1. 질문은 두 문서의 정보를 모두 필요로 하는 질문이어야 합니다.
2. 답변은 두 청크를 근거로 간결하게 작성합니다.
3. 질문에 기관명/사업명을 포함합니다.

반드시 아래 JSON 형식으로만 응답하세요 (마크다운 없이):
{{"question": "...", "expected_answer": "..."}}
"""


def _sample_chunks(collection, num_samples: int, min_length: int = 200) -> list[dict]:
    """ChromaDB 컬렉션에서 고품질 청크를 샘플링한다."""
    all_data = collection.get(include=["documents", "metadatas"])
    ids = all_data["ids"]
    documents = all_data["documents"]
    metadatas = all_data["metadatas"]

    candidates = []
    for i in range(len(ids)):
        meta = metadatas[i] or {}
        text = documents[i] or ""

        # 목차, 서식, 짧은 텍스트 제외
        if meta.get("is_toc") or meta.get("is_form"):
            continue
        if len(text.strip()) < min_length:
            continue

        candidates.append({
            "id": ids[i],
            "content": text,
            "source": meta.get("source", "unknown"),
            "page": meta.get("page"),
            "institution": meta.get("institution", ""),
            "metadata": meta,
        })

    if len(candidates) <= num_samples:
        return candidates

    # 기관별 균형 샘플링
    by_institution: dict[str, list[dict]] = {}
    for c in candidates:
        inst = c["institution"] or "unknown"
        by_institution.setdefault(inst, []).append(c)

    sampled: list[dict] = []
    institutions = list(by_institution.keys())
    random.shuffle(institutions)

    per_inst = max(1, num_samples // len(institutions))
    for inst in institutions:
        pool = by_institution[inst]
        random.shuffle(pool)
        sampled.extend(pool[:per_inst])

    # 부족분 채우기
    remaining = [c for c in candidates if c not in sampled]
    random.shuffle(remaining)
    while len(sampled) < num_samples and remaining:
        sampled.append(remaining.pop())

    return sampled[:num_samples]


def _parse_llm_json(text: str) -> dict | None:
    """LLM 응답에서 JSON을 추출한다."""
    text = text.strip()
    # 마크다운 코드블록 제거
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```") and not inside:
                inside = True
                continue
            elif line.strip().startswith("```") and inside:
                break
            elif inside:
                json_lines.append(line)
        text = "\n".join(json_lines)

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def generate_eval_set(num_pairs: int = 20, model: str | None = None) -> list[dict]:
    """LLM 기반으로 평가셋을 생성한다."""
    load_env()
    config = load_config()
    llm_model = model or config.get("llm", {}).get("model", "gpt-5-mini")

    llm = ChatOpenAI(
        model=llm_model,
        temperature=0.7,
        api_key=get_openai_api_key(),
    )

    vectorstore = get_vectorstore()
    collection = vectorstore._collection

    total_chunks = collection.count()
    print(f"[INFO] ChromaDB 청크 수: {total_chunks}")

    if total_chunks == 0:
        print("[ERROR] ChromaDB에 청크가 없습니다. ingest.py를 먼저 실행하세요.")
        return []

    # 질문 유형별 개수 결정
    type_counts = {}
    for qtype, weight in QUERY_TYPE_WEIGHTS.items():
        type_counts[qtype] = max(1, round(num_pairs * weight))
    # 반올림 오차 보정
    diff = num_pairs - sum(type_counts.values())
    type_counts["single_doc"] += diff

    # single_doc용 샘플
    single_needed = type_counts["single_doc"]
    multi_needed = type_counts["multi_doc"] + type_counts["comparison"]
    total_samples = single_needed + multi_needed * 2  # multi/comparison은 청크 2개씩
    samples = _sample_chunks(collection, total_samples)

    print(f"[INFO] 샘플링된 청크: {len(samples)}개")
    print(f"[INFO] 생성 목표: single_doc={type_counts['single_doc']}, "
          f"multi_doc={type_counts['multi_doc']}, comparison={type_counts['comparison']}")

    eval_items: list[dict] = []
    idx = 0

    # 1) single_doc 질문 생성
    print("\n[1/3] single_doc 질문 생성 중...")
    for i in range(type_counts["single_doc"]):
        if idx >= len(samples):
            break
        chunk = samples[idx]
        idx += 1

        prompt = GENERATION_PROMPT_SINGLE.format(
            source=chunk["source"],
            page=chunk.get("page", "N/A"),
            content=chunk["content"][:2000],
        )

        try:
            result = llm.invoke(prompt)
            parsed = _parse_llm_json(result.content)
            if not parsed:
                print(f"  [SKIP] JSON 파싱 실패 (single_doc #{i+1})")
                continue

            eval_items.append({
                "id": f"eval_{len(eval_items)+1:03d}",
                "question": parsed["question"],
                "expected_answer": parsed["expected_answer"],
                "ground_truth": {
                    "source": chunk["source"],
                    "page": chunk.get("page"),
                },
                "query_type": "single_doc",
                "metadata_filter": (
                    {"institution": chunk["institution"]}
                    if chunk["institution"]
                    else {}
                ),
            })
            print(f"  [OK] eval_{len(eval_items):03d}: {parsed['question'][:50]}...")
        except Exception as e:
            print(f"  [ERROR] single_doc #{i+1}: {e}")

    # 2) multi_doc / comparison 질문 생성
    for qtype in ["multi_doc", "comparison"]:
        count = type_counts[qtype]
        desc = "다중 문서 참조" if qtype == "multi_doc" else "비교 분석"
        print(f"\n[{'2' if qtype == 'multi_doc' else '3'}/3] {qtype} 질문 생성 중...")

        for i in range(count):
            if idx + 1 >= len(samples):
                break
            chunk1 = samples[idx]
            chunk2 = samples[idx + 1]
            idx += 2

            # 가능하면 서로 다른 출처 선택
            if chunk1["source"] == chunk2["source"] and idx < len(samples):
                chunk2 = samples[idx]
                idx += 1

            prompt = GENERATION_PROMPT_MULTI.format(
                source1=chunk1["source"],
                page1=chunk1.get("page", "N/A"),
                content1=chunk1["content"][:1500],
                source2=chunk2["source"],
                page2=chunk2.get("page", "N/A"),
                content2=chunk2["content"][:1500],
                query_type_desc=desc,
            )

            try:
                result = llm.invoke(prompt)
                parsed = _parse_llm_json(result.content)
                if not parsed:
                    print(f"  [SKIP] JSON 파싱 실패 ({qtype} #{i+1})")
                    continue

                eval_items.append({
                    "id": f"eval_{len(eval_items)+1:03d}",
                    "question": parsed["question"],
                    "expected_answer": parsed["expected_answer"],
                    "ground_truth": {
                        "source": chunk1["source"],
                        "page": chunk1.get("page"),
                    },
                    "query_type": qtype,
                    "metadata_filter": (
                        {"institution": chunk1["institution"]}
                        if chunk1["institution"]
                        else {}
                    ),
                })
                print(f"  [OK] eval_{len(eval_items):03d}: {parsed['question'][:50]}...")
            except Exception as e:
                print(f"  [ERROR] {qtype} #{i+1}: {e}")

    return eval_items


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM 기반 평가셋 자동 생성")
    parser.add_argument("--num_pairs", type=int, default=20, help="생성할 Q&A 쌍 수 (기본: 20)")
    parser.add_argument("--model", type=str, default=None, help="사용할 LLM 모델 (기본: config)")
    parser.add_argument("--output", type=str, default=None, help="출력 파일 경로")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else _get_eval_dir() / "eval_dataset.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BiddingMate 평가셋 자동 생성")
    print("=" * 60)

    eval_items = generate_eval_set(num_pairs=args.num_pairs, model=args.model)

    if not eval_items:
        print("\n[ERROR] 생성된 평가셋이 없습니다.")
        return

    # YAML 저장
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            eval_items,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    print(f"\n{'=' * 60}")
    print(f"[완료] {len(eval_items)}개 Q&A 쌍 생성됨")
    print(f"[저장] {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
