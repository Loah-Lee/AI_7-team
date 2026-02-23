# AI_START.md

## Purpose
이 레포에서 AI(Codex 포함)는 **CODEX_CONSTITUTION.md를 최상위 규칙(헌법)**으로 준수하며 작업한다.  
이 파일은 AI가 작업을 시작할 때 반드시 참조하는 **진입점(Start Point)**이다.

---

## Governing Rules
- 최상위 규칙: **CODEX_CONSTITUTION.md**
- 헌법과 충돌 시, 이 파일의 내용은 **무효**로 간주한다.
- 헌법에 명시되지 않은 운영 방식만 이 파일에서 보조적으로 정의한다.

---

## Collaboration Model
- **설계·논의·판단**: Codex 앱 (또는 AI 대화)
- **실제 실행**: VS Code 내 터미널
- AI는 **터미널 명령을 직접 실행하지 않는다**
- AI는 항상 **실행 전 명령어를 먼저 제시**한다

---

## Scenario Priority (Guide Sync)
- 본 저장소 기본 실험 축은 **시나리오 B(클라우드 API 기반)** 로 둔다.
- 실험/보고 시 최소 비교 단위:
  1) lexical baseline
  2) vector retrieval(Dense/Chroma)
  3) hybrid retrieval
- `hybrid_alpha`는 HybridRetriever에서만 사용한다.
  - HybridRetriever 기준 `hybrid_alpha=1.0`은 lexical-only baseline으로 분류한다.
  - ChromaRetriever에는 `hybrid_alpha`가 적용되지 않는다.
- Chroma 운영 모드에서는 기관명 없는 질의를 검색하지 않고, 기관명 재입력을 요청한다.

---

## Execution Discipline (3-Command Rule)
- 한 번에 제시하는 터미널 명령은 **최대 3개**
- 각 명령의 목적을 한 줄로 설명한다
- 불필요한 반복 실행을 제안하지 않는다
- 각 명령 안내에는 반드시 아래 2가지를 포함한다:
  - 이 명령이 **무엇을 실행/검증하는지**
  - 실행 후 생성/갱신되는 **결과물 저장 경로**
- 명령 실행 결과를 해석할 때도, 최종 산출물의 경로를 다시 명시한다

---

## ✍️ Coding & Change Policy
- **최소 변경 원칙**을 따른다
- 기존 코드 구조를 존중한다
- 수정이 필요한 파일만 정확히 지정한다
- “리팩토링”은 명시적으로 요청된 경우에만 수행한다

---

## 🌐 Language & Style
- 모든 설명과 응답은 **한국어**로 한다
- 과장·추측·확신 없는 단정 표현을 피한다
- 모르면 “모른다”고 말하고, 다음 확인 단계를 제시한다

---

## 🚀 How to Start (for AI)
작업을 시작할 때 AI는 다음을 전제로 한다:

> “CODEX_CONSTITUTION.md를 최상위 규칙으로 준수하며,  
> AI_START.md의 협업·실행 방식을 따른다.”

이 문장을 기준으로 모든 판단을 수행한다.
