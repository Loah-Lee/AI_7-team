#!/usr/bin/env python3
"""입찰메이트 v17 - RAG 시스템 평가 스크립트."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

# LangChain (LangSmith 트레이싱)
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langsmith import traceable

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

from src.utils.config import OPENAI_API_KEY, DEFAULT_MODEL
from src.graph.workflow import RAGChatbotV17

# LangSmith 환경 변수 설정
if os.environ.get("LANGSMITH_TRACING") == "true" and os.environ.get("LANGSMITH_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = os.environ.get("LANGSMITH_API_KEY", "")
    os.environ["LANGCHAIN_ENDPOINT"] = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com/")
    os.environ["LANGCHAIN_PROJECT"] = os.environ.get("LANGSMITH_PROJECT", "my-test")
    print(f"🔍 LangSmith 트레이싱 활성화: {os.environ.get('LANGCHAIN_PROJECT')}")

# ============================================================================
# LLM Judge 프롬프트
# ============================================================================

JUDGE_PROMPT = """당신은 RAG 시스템의 답변을 평가하는 전문가입니다.

다음 기준으로 0~5점을 부여하세요:
1. Correctness (정확성): 생성된 답변이 기대 답변과 의미적으로 일치하는가?
2. Answer Coverage (답변 커버리지): 기대 답변의 핵심 정보가 생성 답변에 얼마나 누락 없이 포함되었는가?
3. Faithfulness (충실성): 생성된 답변이 검색된 context에 근거하고 있는가? (환각 없는가)
4. Context Relevance (검색 관련성): 검색된 context가 질문에 실제로 관련 있는가?

질문: {question}
기대 답변: {expected_answer}
생성된 답변: {generated_answer}
검색된 Context: {retrieved_context}

다음 JSON 형식으로만 응답하세요:
{{
    "correctness": <0-5>,
    "coverage": <0-5>,
    "faithfulness": <0-5>,
    "context_relevance": <0-5>,
    "reasoning": "<간단한 설명>"
}}
"""


# ============================================================================
# 평가 실행
# ============================================================================

def load_eval_dataset(dataset_path: str) -> list[dict]:
    """평가 데이터셋을 로드합니다."""
    with open(dataset_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def calculate_retrieval_metrics(
    results: list[dict],
    chatbot: RAGChatbotV17
) -> dict[str, Any]:
    """검색 메트릭을 계산합니다."""
    recall_at_k_source = []
    recall_at_k_page = []
    mrr_source = []
    mrr_page = []

    for result in results:
        ground_truth = result['ground_truth']
        retrieved_docs = result.get('retrieved_docs', [])

        expected_source = ground_truth.get('source', '')
        expected_page = ground_truth.get('page', None)

        # Recall@K 계산
        found_source = False
        found_page = False
        rank_source = 0
        rank_page = 0

        for i, doc in enumerate(retrieved_docs):
            doc_source = doc.get('metadata', {}).get('source', '')
            doc_page = doc.get('metadata', {}).get('page', None)

            if not found_source and expected_source in doc_source:
                found_source = True
                rank_source = i + 1

            if not found_page and expected_source in doc_source:
                if expected_page is None or doc_page == expected_page:
                    found_page = True
                    rank_page = i + 1

        recall_at_k_source.append(1.0 if found_source else 0.0)
        recall_at_k_page.append(1.0 if found_page else 0.0)
        mrr_source.append(1.0 / rank_source if rank_source > 0 else 0.0)
        mrr_page.append(1.0 / rank_page if rank_page > 0 else 0.0)

    return {
        'recall_at_k_source': sum(recall_at_k_source) / len(recall_at_k_source) if recall_at_k_source else 0,
        'recall_at_k_page': sum(recall_at_k_page) / len(recall_at_k_page) if recall_at_k_page else 0,
        'mrr_source': sum(mrr_source) / len(mrr_source) if mrr_source else 0,
        'mrr_page': sum(mrr_page) / len(mrr_page) if mrr_page else 0,
    }


@traceable(name="eval_llm_judge", run_type="llm")
def evaluate_with_llm_judge(
    question: str,
    expected_answer: str,
    generated_answer: str,
    retrieved_context: str,
    llm: ChatOpenAI
) -> dict[str, Any]:
    """LLM Judge로 답변을 평가합니다."""
    prompt = JUDGE_PROMPT.format(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        retrieved_context=retrieved_context[:2000]
    )

    try:
        messages = [
            SystemMessage(content="당신은 RAG 시스템 평가 전문가입니다."),
            HumanMessage(content=prompt)
        ]

        response = llm.invoke(messages)
        result = json.loads(response.content)
        return {
            'correctness': result.get('correctness', 0),
            'coverage': result.get('coverage', 0),
            'faithfulness': result.get('faithfulness', 0),
            'context_relevance': result.get('context_relevance', 0),
            'reasoning': result.get('reasoning', '')
        }
    except Exception as e:
        print(f"LLM Judge 오류: {e}")
        return {
            'correctness': 0,
            'coverage': 0,
            'faithfulness': 0,
            'context_relevance': 0,
            'reasoning': f'오류: {e}'
        }


@traceable(name="eval_retrieval_run", run_type="chain")
def run_evaluation(
    chatbot: RAGChatbotV17,
    dataset: list[dict],
    label: str = "current",
    llm: ChatOpenAI | None = None,
    top_k: int = 10
) -> dict[str, Any]:
    """평가를 실행합니다."""
    results = []

    print(f"\n{'='*60}")
    print(f"평가 시작: {len(dataset)}개 질문")
    print(f"{'='*60}\n")

    for i, item in enumerate(dataset, 1):
        question_id = item['id']
        question = item['question']
        expected_answer = item['expected_answer']
        ground_truth = item.get('ground_truth', {})
        query_type = item.get('query_type', 'single_doc')

        print(f"[{i}/{len(dataset)}] {question_id}: {question[:50]}...")

        start_time = time.time()

        # 챗봇 응답 생성
        result = chatbot.answer(question, top_k=top_k)
        generated_answer = result.get('answer', '')
        response_time = time.time() - start_time

        # 검색된 문서 가져오기
        retrieved_docs = []
        if hasattr(chatbot.vector_store, 'last_search_results'):
            retrieved_docs = chatbot.vector_store.last_search_results

        # 검색 컨텍스트 구성
        retrieved_context = "\n\n".join([
            f"[{doc.get('metadata', {}).get('source', 'Unknown')}]\n{doc.get('text', '')[:500]}"
            for doc in retrieved_docs[:3]
        ])

        # LLM Judge 평가
        judge_scores = {}
        if llm:
            judge_scores = evaluate_with_llm_judge(
                question, expected_answer, generated_answer, retrieved_context, llm
            )

        result_item = {
            'id': question_id,
            'question': question,
            'expected_answer': expected_answer,
            'generated_answer': generated_answer,
            'ground_truth': ground_truth,
            'query_type': query_type,
            'response_time': response_time,
            'retrieved_docs': retrieved_docs,
            'retrieved_context': retrieved_context,
            **judge_scores
        }

        results.append(result_item)

        print(f"  응답 시간: {response_time:.2f}초")
        if judge_scores:
            print(f"  점수: C={judge_scores.get('correctness', 0)}/5, "
                  f"Cv={judge_scores.get('coverage', 0)}/5, "
                  f"F={judge_scores.get('faithfulness', 0)}/5, "
                  f"CR={judge_scores.get('context_relevance', 0)}/5")
        print()

    # 검색 메트릭 계산
    retrieval_metrics = calculate_retrieval_metrics(results, chatbot)

    # LLM Judge 메트릭 계산
    llm_metrics = {}
    if results and all('correctness' in r for r in results):
        llm_metrics = {
            'avg_correctness': sum(r.get('correctness', 0) for r in results) / len(results),
            'avg_coverage': sum(r.get('coverage', 0) for r in results) / len(results),
            'avg_faithfulness': sum(r.get('faithfulness', 0) for r in results) / len(results),
            'avg_context_relevance': sum(r.get('context_relevance', 0) for r in results) / len(results),
        }

    # 전체 메트릭
    overall_metrics = {
        'total_questions': len(results),
        'avg_response_time': sum(r['response_time'] for r in results) / len(results),
        **retrieval_metrics,
        **llm_metrics
    }

    return {
        'label': label,
        'metrics': overall_metrics,
        'results': results
    }


def main() -> None:
    """메인 진입점 함수."""
    import argparse

    parser = argparse.ArgumentParser(description='입찰메이트 RAG 평가')
    parser.add_argument('--label', default='current', help='평가 라벨')
    parser.add_argument('--dataset', default='eval/eval_dataset.yaml', help='데이터셋 경로')
    parser.add_argument('--output', default='eval/eval_results.json', help='결과 저장 경로')
    parser.add_argument('--top_k', type=int, default=10, help='검색할 문서 수')
    parser.add_argument('--no-judge', action='store_true', help='LLM Judge 사용 안 함')

    args = parser.parse_args()

    # 챗봇 초기화
    print("챗봇 초기화 중...")
    chatbot = RAGChatbotV17()

    # 데이터셋 로드
    print(f"데이터셋 로드: {args.dataset}")
    dataset = load_eval_dataset(args.dataset)

    # LLM Judge 모델 (LangChain + LangSmith 트레이싱)
    judge_llm = None
    if not args.no_judge and OPENAI_API_KEY:
        judge_llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=DEFAULT_MODEL,
        )
        print("LLM Judge 활성화")
    else:
        print("LLM Judge 비활성화")

    # 평가 실행
    eval_result = run_evaluation(
        chatbot,
        dataset,
        args.label,
        judge_llm,
        top_k=args.top_k
    )

    # 결과 저장
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(eval_result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print("평가 완료!")
    print(f"{'='*60}")
    print(f"\n전체 메트릭:")
    for key, value in eval_result['metrics'].items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
