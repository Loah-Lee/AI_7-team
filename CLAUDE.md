# BiddingMate (입찰메이트) Project Guide

## Context
- B2G 입찰 컨설팅을 위한 RFP 분석 RAG 시스템
- 주요 목표: RFP 요약, 다중 문서 비교, LangGraph 기반 워크플로우 구현

## Tech Stack
- Python 3.11+ (uv managed)
- LLM: GPT-5, Embedding: OpenAI text-embedding-3-small
- Framework: LangGraph, LangSmith, Langfuse, Streamlit

## Commands
- Setup: `uv sync`
- Run UI: `streamlit run app/main.py`
- Test: `pytest`
- Eval: `uv run python scripts/eval_retrieval.py --label current --top_k 5`

## Rules
- 모든 파싱 로직은 `parsers/`에 위치하며, HWP와 PDF를 구분한다.
- LangGraph 노드 설계 시 `State` 객체를 엄격히 준수한다.
- 모든 검색 결과는 LangSmith로 트레이싱한다.
- 평가 체계: LLM-as-Judge 4지표 (Correctness, Answer Coverage, Faithfulness, Context Relevance) → `eval_resources/METRICS.md` 참조

## Git Commit Rules
- 1 logical change = 1 commit
- Use conventional commits (feat:, fix:, refactor:, chore:)
- Format: `git add <file> && git commit -m "<type>: <description>"`
