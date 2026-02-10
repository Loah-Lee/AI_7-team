# BiddingMate (입찰메이트) Project Guide

## Context
- B2G 입찰 컨설팅을 위한 RFP 분석 RAG 시스템
- 주요 목표: RFP 요약, 다중 문서 비교, LangGraph 기반 워크플로우 구현

## Tech Stack
- Python 3.10+ (uv managed)
- LLM: GPT-5, Embedding: OpenAI
- Framework: LangGraph, LangSmith, Langfuse, Streamlit

## Commands
- Setup: `uv sync`
- Run UI: `streamlit run app/main.py`
- Test: `pytest`

## Rules
- 모든 파싱 로직은 `parsers/`에 위치하며, HWP와 PDF를 구분한다.
- LangGraph 노드 설계 시 `State` 객체를 엄격히 준수한다.
- 모든 검색 결과는 LangSmith로 트레이싱한다.

## Git Commit Rules:
- 1 logical change = 1 commit
- Use conventional commits (feat:, fix:, refactor:, chore:)
- After each step (Parser, Chunker, Debug Tool), auto-generate git commit command
- Format: git add <file> && git commit -m "<type>: <description>"

# Work Logging Protocol
- Every time a task is completed (e.g., code generation, data cleaning, analysis), create a report file.
- The report must follow this structure:
  1. User Prompt: Raw input from the user.
  2. Thinking Process: Internal logic, assumptions made, and technical choices.
  3. Execution Result: Summary of changes or output generated.
- File naming convention: `YYYYMMDD_HHMM_TaskName_Report.md`
- Always save these reports in the designated 'ai_history' directory.

# System Instruction: Anti-Surface-Level Execution

### 1. Deep Verification Rule
- **Never assume** a task is complete based on code generation alone. You must verify the actual output (e.g., file existence, DB record counts, or terminal log outputs) before reporting success.
- **Verification Requirement:** If you modify a database or a file, you must run a `SELECT` query or a `cat/ls` command to prove the change was applied correctly in the user's actual environment.

### 2. No Hard-coding Policy
- **Real Data Priority:** Do not use static mock data when real data access is available. Always prefer dynamic retrieval and processing from the user's current project environment.
- **Edge Case Handling:** When implementing logic, explicitly explain and handle "Edge Cases" (e.g., what happens if a PDF has 0 text, or a DB table is empty?).

### 3. Self-Critique Step
- **Internal Audit:** Before finalizing any response or report, perform a "Self-Audit." Ask yourself: "Is this result verifiable, or am I just describing what the code *should* do?" 
- **Action over Description:** If the result is not yet verified, run the code and confirm the actual output first.

### 4. Mandatory Evidence
- **Proof of Execution:** All reports and task completions must include "Evidence of Execution." This includes:
  - Terminal output snippets.
  - SQL result counts or data samples.
  - Confirmation of created/modified file paths.