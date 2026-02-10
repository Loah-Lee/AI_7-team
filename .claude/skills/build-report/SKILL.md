---
name: build-report
description: 평가 결과 JSON에서 HTML 대시보드를 생성한다.
allowed-tools: Bash, Read
---

# /build-report

평가 결과 JSON 파일에서 Chart.js 기반 HTML 대시보드를 생성합니다.

## 실행 절차

1. 리포트 빌드:
   ```bash
   uv run python scripts/build_eval_report.py
   ```

2. 결과 확인:
   - `eval/eval_report.html` 파일 존재 여부 확인
   - 파일 크기 확인 (정상 생성 검증)

3. 사용자에게 안내:
   ```
   eval/eval_report.html이 생성되었습니다.
   브라우저에서 열어 확인하세요: open eval/eval_report.html
   ```
