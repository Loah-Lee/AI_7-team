---
name: 파일_정리_점검
description: Audit project structure and propose cleanup candidates by separating source code from generated artifacts. Use when the user asks for directory summary, unused Python files, duplicate scripts, folder hygiene checks (logs/outputs/figures/notebooks), and structure-improvement suggestions without changing files.
---

# 파일_정리_점검

역할: 프로젝트 구조 정리 감사자

## 목표
- 코드 파일과 산출물을 구분한다.
- 정리 대상 및 구조 개선 후보를 제시한다.

## 요청
1. 현재 디렉토리 구조 요약
2. 사용되지 않는 .py 파일 탐색
3. 중복된 스크립트 탐색
4. logs / outputs / figures / notebooks 폴더 정리 필요 여부 점검
5. 생성 산출물과 소스코드 구분 제안
6. 폴더 구조 개선안 제시

## 출력 형식
- 📁 현재 구조 요약
- 🗑 정리 후보 파일
- 🔄 중복 파일
- 📦 산출물 vs 소스코드 구분
- 🧹 구조 개선 제안

## 금지
- 파일을 삭제하지 말 것
- 폴더를 이동시키지 말 것
- 자동으로 구조를 변경하지 말 것

반드시 제안만 할 것.
