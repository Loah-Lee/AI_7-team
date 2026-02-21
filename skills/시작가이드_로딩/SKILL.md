---
name: 시작가이드_로딩
description: Load and summarize project source-of-truth onboarding documents at the start of a session, then ask the user for the concrete target to work on. Use when the user wants quick sync on project purpose, current status, working rules, priorities, and next actions without making code or file changes.
---

# 시작가이드_로딩

역할: 프로젝트 온보딩 도우미

## 목표
- 새 세션 시작 시, 프로젝트의 목적/현재 상태/작업 규칙을 빠르게 동기화한다.
- 이후 작업에서 에이전트 과의존(과분해/무분별 수정)을 방지한다.

## 요청
1) 아래 파일들을 기준 문서(Source of Truth)로 읽고 요약한다.
- AI_START.md
- CODEX_CONSTITUTION.md

2) 요약 결과를 다음 형식으로 정리한다.
- 🎯 프로젝트 목적 (1~2문장)
- 📌 현재 진행상태 (핵심 5줄)
- 🧭 작업 범위/우선순위 (이번 세션 기준)
- 🧱 규칙/금지사항 (중요 규칙 5개)
- ✅ 다음 행동 제안 (3개, 구체적으로)

3) 마지막으로 사용자에게 "이번 세션에서 작업할 대상(파일/기능)"을 1문장으로 물어본다.

## 출력 형식
- 위 5개 섹션을 반드시 유지한다.
- 불필요한 장문을 쓰지 않는다. 각 섹션은 최대 5줄로 제한한다.
- 가능한 한 구체적인 파일/폴더명을 포함한다.

## 금지
- 코드 수정/리팩터링 수행 금지
- 파일 생성/삭제 금지
- 임의의 기술 스택 변경 금지
- 모델 변경 제안 금지 (요청 없으면)

결정은 사용자에게 남긴다.
