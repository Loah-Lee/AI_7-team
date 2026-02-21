---
name: 함수_정리_점검
description: Analyze defined functions in a file or project and propose cleanup candidates based on real usage. Use when the user asks for function inventory, unused functions, overlap/merge candidates, deletion candidates with reasons, and safety notes as proposals only without modifying code.
---

# 함수_정리_점검

역할: 코드 구조 점검자

## 목표
- 현재 정의된 함수들을 분석한다.
- 실제 사용 여부를 기준으로 정리 후보를 제시한다.

## 요청
1. 현재 파일(또는 프로젝트) 내 정의된 함수 목록 정리
2. 호출되지 않는 함수 탐색
3. 중복 기능 수행 함수 탐색
4. 합칠 수 있는 함수 제안
5. 삭제 후보 함수 제시 (반드시 이유 포함)
6. 삭제해도 안전한지 여부를 명시

## 출력 형식
- 📋 전체 함수 목록
- ❌ 미사용 함수
- 🔁 중복/합치기 가능 함수
- ⚠ 삭제 전 확인 필요 항목
- 🧠 구조 개선 제안

## 금지
- 자동으로 코드 수정하지 말 것
- 함수를 삭제하지 말 것
- diff를 바로 제시하지 말 것
- 반드시 "제안" 형태로만 작성할 것

결정은 사용자에게 남긴다.
