---
name: collab-journal-writer
description: Generate a daily collaboration journal entry in Korean using the user's fixed template sections (Plan, Work Done, Insights, Issues & Fixes, Next Steps). Use when the user asks with [협업일지_작성], asks to summarize today’s work into a journal format, or wants a concise end-of-day project log.
---

# 협업일지_작성

사용자가 협업일지 작성을 요청하면 아래 형식으로 바로 작성한다.

## 작성 규칙
- 한국어로 작성한다.
- 과장 없이 사실 기반으로 작성한다.
- 오늘 대화/작업 기준으로만 작성한다.
- 불명확한 내용은 단정하지 않고 짧게 표시한다.
- 문제 항목은 실제 발생한 건만 작성하고, 없으면 "- 없음"으로 쓴다.
- 문장은 짧고 실무적으로 쓴다.
- 사용자가 `1. 오늘의 목표 (Plan)` 내용을 직접 제공하면, Plan은 사용자 입력을 그대로 기준으로 삼고 `2~5` 섹션만 작성한다.

## 출력 템플릿
아래 구조를 그대로 사용한다.

## 1. 오늘의 목표 (Plan)

- 

---

## 2. 오늘 내가 한 일 (Work Done)

- 

---

## 3. 오늘의 인사이트 / 배운 점 (Insights)

- 

---

## 4. 문제·이슈 / 해결 과정 (Issues & Fixes)

- **문제1:**
- **원인:**
- **시도한 해결:**
- **결과:**

---

## 5. 내일의 계획 (Next Steps)
- 

## 작성 절차
1. 사용자가 `1. 오늘의 목표 (Plan)`을 제공했는지 먼저 확인한다.
2. Plan 제공 시: `2. Work Done`부터 `5. Next Steps`까지만 작성하고, Work Done은 Plan 기준 달성/진행 항목 중심으로 정리한다.
3. Plan 미제공 시: 오늘 대화에서 목표/실행/결과를 추출해 `1~5`를 모두 작성한다.
4. Insights는 재사용 가능한 교훈만 1~2개로 요약한다.
5. Issues & Fixes는 문제-원인-해결-결과를 한 세트로 쓰며, 해결한 문제 수에 따라 양식에 맞춰 늘려서 작성한다.

## 품질 체크
- 템플릿 섹션 누락 없음
- 입력 모드(Plan 제공/미제공)와 출력 범위가 일치함
- 중복 문장 없음
- 추측성 문장 최소화
- 바로 복붙 가능한 상태
