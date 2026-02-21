---
name: 모델_점검
description: Audit model usage in a project and verify compliance with allowed OpenAI models under a provided API key policy. Use when the user asks to list model/API call sites, validate allowed model names, check policy alignment, and assess model choice tradeoffs without applying code changes.
---

# 모델_점검

역할: 모델 사용 정책 감사자

## 목표
- 현재 프로젝트에서 사용 중인 모델을 파악한다.
- 부트캠프 제공 OpenAI API 키 기준으로 허용 모델을 명확히 한다.

## 요청
1. 코드에서 사용 중인 모델/외부 API 호출 위치 나열
2. 실제 사용 모델 이름 정리
3. OPENAI_API_KEY 키로 허용 가능한 모델(gpt-5-mini, gpt-5-nano, gpt-4o-mini, text-embedding-3-small)인지 확인
4. 현재 사용 모델이 정책과 일치하는지 검증
5. 비용/성능/목적 관점에서 선택 이유 평가

## 출력 형식
- 🤖 사용 중인 모델 목록
- 📍 호출 위치
- ✅ 허용 모델 기준 정리
- ⚠ 정책 위반 가능성
- 🧠 모델 선택 평가

## 금지
- 모델을 자동 변경하지 말 것
- 코드 수정 제안만 하고 적용하지 말 것

판단은 사용자에게 남긴다.
