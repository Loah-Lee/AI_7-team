# Dev Integration Patch Note (2026-02-25)

## 기준
- Base: `origin/dev` @ `9c5bde8`
- 목적: eval 지표 계산 로직 보정
- 제외: 테스트 산출물/리포트/로그(`eval_results_*.json`, `eval_report*.html`, `eval_run*.log`)

## 변경 규모
- 변경 파일: 1개
- 신규 파일: 1개 (이 문서)
- 코드 라인 변경(기존 파일 기준): `+82 / -14`

## 변경 파일
- `src/evaluation/metrics.py`
- `docs/PATCH_NOTE_DEV_INTEGRATION_2026-02-25.md`

## 핵심 수정 사항
1. `ground_truth.sources` 리스트 입력 지원
- 기존: `str` 1개만 가정
- 변경: `str | list[str] | tuple[str,...] | set[str]` 처리

2. source 매칭 정규화 추가
- Unicode NFC 정규화
- 파일 확장자 제거 후 비교 (`.hwp` vs `.pdf` 차이 완화)

3. Retrieval 메트릭 로직 보정
- `calculate_hit_position`: 다중 source 입력 대응
- `calculate_recall_at_k`:
  - 단일 source: top-K 포함 여부
  - 다중 source: strict(all-of) 매칭
- `calculate_avg_score`: 다중 source 입력 대응

## 기대 효과
- source 문자열 표현 차이(정규화/확장자)로 인한 과소평가 완화
- 다중 정답 source 질의의 Recall 계산 일관성 확보
- MRR/Recall 집계가 실제 검색 결과와 더 일치

## 통합 정책
- 코드/문서만 dev 반영
- 평가 실행 결과 파일은 dev 커밋에서 제외

---

## 추가 통합 (Clone Ready) — 2026-02-25

목표: 팀원이 `dev`를 클론한 뒤 바로 동일 동작을 재현할 수 있도록 로컬 그래프 로직을 동기화.

### 반영 파일
- `src/graph/nodes.py`
- `src/graph/workflow.py`

### 의도
- 로컬에서 사용 중이던 질의 해석/워크플로우 로직을 `dev`로 통합
- 실행 산출물(평가 JSON/HTML/로그)은 저장소에 포함하지 않고 코드만 반영

### 제외 항목(의도적 미포함)
- `eval_resources/eval_results_*.json`
- `eval_resources/eval_report*.html`
- `eval_resources/*.log`

### 검증
- `python -m py_compile src/graph/nodes.py src/graph/workflow.py` 통과
