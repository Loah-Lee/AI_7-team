# Session Timeline (DB Handoff -> Now)

- 작성 시각: 2026-02-27 10:46 KST
- 시간순 범위(기록된 이벤트): T0 ~ T+43:19 (`T0=2026-02-25 15:27 KST`)
- 기준 리포:
  - 아카이브 리포: `/home/panda/codeit_part3/AI_7-team`
  - 작업 리포: `/home/panda/codeit_part3/workspace_collab`
  - dev 반영 리포: `/home/panda/codeit_part3/workspace_collab/.dev_worktree`
- 검증 소스:
  - Git commit log (작성자/변경파일)
  - `../AI_7-team/eval/eval_results*.json` (이전 세션)
  - `eval_resources/eval_results*.json` (이번 세션)

## 1) 전환 시점 (2026-02-25 15:27 KST)

- 세션 전환 기준 커밋: `5ed5b3c`
- 기준 시간축: `T0 = 2026-02-25 15:27 KST`
- 의미:
  - 아카이브 세션 종료
  - 이후 `workspace_collab` 중심으로 DB/레이턴시/생성 정책 개선 진행

---

## 2) 이번 세션 핵심 흐름 (T+00:18 ~ T+43:19)

요청 타임라인 요약:

| 시점(T+) | 사용자 요청(요약) | 조치/변경 | 결과 |
|---|---|---|---|
| T+00:18 ~ T+07:32 | 확장자 불일치, hit 계산, 리포트 표시 정합화 | multi-source 지표/소스 정규화, report label/memo/csv_match 보강 | `current.before_dev_run` ~ `v5-pdf-fix` 기준선 확보 |
| T+18:03 ~ T+22:00 | 레이턴시 0.0/누락, DB `(1)/(2)/backup/main` 비교, API 오류 재실행 | latency 전달 보강, DB별 평가 라벨 분리, fallback/precision 경로 개선 | DB별 성능 차이 명확화(backup 우세), noapierr 재실행 결과 확보 |
| T+22:48 ~ T+24:13 | 최신 dev 대비 차이 분석/동기화 | dev 동기화 + current/latest_sync/current_patch 기준선 분리 | 로컬-원격 편차를 코드/데이터셋 기준으로 분리 가능 |
| T+26:57 ~ T+27:47 | 생성은 정리용으로만 사용, 근거형 우선 요구 | answer_mode 비교 후 extractive short-circuit 반영 | `685d36b` 반영, C/AC 소폭 개선 + latency 감소 |
| T+43:19 | 테스트 질문별 “정답 vs 실제 출력 응답” 비교 요청 | eval 결과에서 질문/정답/실제응답/점수/latency를 CSV로 추출 | 발표용 비교 산출물 `eval_compare_extractive_only_20260226.csv` 생성 |

### 2.1 T+00:18 ~ T+07:32 (2026-02-25 15:45 ~ 22:59): 평가 정합/리포트 안정화

문제:
- source 확장자(`.hwp/.pdf`) 불일치로 hit 왜곡
- multi-source Recall/MRR/hit position 계산 일관성 부족
- report 표시 정보 부족(`label`, `memo`, `csv_match`, per-type latency)

수정(대표 커밋):
- `c86f826`, `127bcb5`, `941de46` (평가 정합)
- `c9b5f31`, `6833b69`, `fd53598` (리포트 표시)
- `f0ab7f3` (csv short-circuit hit 집계)

결과:
- `eval_results_current.before_dev_run.json` (T+00:18, 2026-02-25 15:45): `C=1.8, AC=1.6, R=0.75, MRR=0.75`
- `eval_results_v5-pdf-fix.json` (T+06:06, 2026-02-25 21:33): `C=1.3, AC=1.3, R=0.45, MRR=0.425`

### 2.2 T+18:03 ~ T+22:00 (2026-02-26 09:30 ~ 13:27): DB 전환 + 레이턴시/생성 경로 진단

문제:
- “레이턴시 0.0/누락”, “질문당 레이턴시 확인 어려움”
- DB 버전 변경(`backup`, `(1)`, `(2)`, `main`) 시 점수 급변
- source 표기 불일치 체감

수정(대표 커밋):
- `048d68a`, `d6ca724`, `f5cc477`, `e5a18a4` (retriever/workflow)
- `0278d9b` (latency + draft-driven generation)

결과(라벨별):
- `latency_fix` (T+18:03, 09:30): `C=4.05, AC=3.85, R=0.70, MRR=0.70`
- `run_20260226_db1` (T+19:12, 10:39): `C=1.15, AC=1.10, R=0.20, MRR=0.20`
- `testdb_20260226` (T+19:39, 11:06): `C=1.20, AC=1.00, R=0.20, MRR=0.20`
- `backupdb_20260226` (T+19:51, 11:18): `C=3.75, AC=3.50, R=0.90, MRR=0.90`
- `db2_main_20260226` (T+21:38, 13:05): `C=0.00, AC=0.00, R=0.20, MRR=0.20`
- `rerun_20260226_noapierr` (T+22:00, 13:27): `C=2.70, AC=2.60, R=0.80, MRR=0.80`

### 2.3 T+22:48 ~ T+24:13 (2026-02-26 14:15 ~ 15:40): dev 최신 동기화 + 기준선 정렬

문제:
- “최신 dev 대비 내 결과 차이”

수정:
- dev 동기화 및 코드 차이 정렬
- `current`, `latest_sync`, `current_patch` 기준선 분리

관련 커밋:
- `d9237ef`, `07013fc`, `d758ebe`

결과:
- `current` (T+22:48, 14:15): `C=3.55, AC=3.45, R=0.95, MRR=0.90`
- `latest_sync_20260226` (T+22:55, 14:22): `C=3.45, AC=3.35, R=0.90, MRR=0.90`
- `run_20260226_current_patch` (T+24:13, 15:40): `C=3.75, AC=3.35, R=0.90, MRR=0.90`

### 2.4 T+26:57 ~ T+27:47 (2026-02-26 18:24 ~ 19:14): 생성 정책 확정 + dev 반영

문제:
- 생성형 답변이 체감상 C/AC 저하
- “근거가 2개로 고정되는 느낌”
- “생성은 보기좋게 정리 수준만” 요구

수정:
- answer_mode 비교 실험
- `extractive_draft` 존재 시 생성 생략(short-circuit)

관련 커밋:
- `f5ebb82` (report 불릿 보존)
- `685d36b` (dev): `fix(graph): short-circuit to extractive draft before LLM generation`

결과 비교:
- `dev_dataset_latest` (T+26:59, 18:26): `C=3.6, AC=3.45, F=4.25, CR=4.8, R=1.0, MRR=0.95`, total latency `20.314s`
- `extractive_only_20260226` (T+27:23, 18:50): `C=3.7, AC=3.6, F=4.1, CR=4.75, R=1.0, MRR=0.95`, total latency `10.886s`

해석:
- C/AC 소폭 개선, latency 대폭 감소
- F/CR은 소폭 하락

### 2.5 T+43:19 (2026-02-27 10:46): 질문별 실제 출력 응답 비교 산출물 생성

요청:
- "질문에 대한 실제 답변을 넣어서 정답과 비교하고 싶다"

조치:
- `eval_results_extractive_only_20260226.json`의 `per_query`를 기준으로
- `question`, `expected_answer`, `generated_answer`, `answer_mode`, 지표(C/AC/F/CR), `total_latency_s`를 CSV로 추출

결과 산출물:
- `eval_resources/eval_compare_extractive_only_20260226.csv` (`20`행, 질문별 비교 가능)
- `eval_resources/eval_answer_compare_all_logs_long_20260227.csv` (`341`행, 로그별 질문/응답 long format)
- `eval_resources/eval_answer_compare_matrix_by_id_20260227.csv` (`20x39`, 질문별 로그 응답 매트릭스)
- `eval_resources/eval_answer_compare_transitions_20260227.csv` (`17`행, 인접 로그 간 응답 변경률)
- `eval_resources/eval_answer_compare_transition_detail_20260227.csv` (`302`행, 문항 단위 변경 상세)

활용:
- 슬라이드 23~27의 "문제별 변화 근거"에 질문 단위 증거로 바로 인용 가능
- 악화/개선 문항의 실제 응답 문장 비교(예: `eval_016`, `eval_017`)에 사용
- 로그 전이별 응답 변경률(몇 문항의 답변 문장이 바뀌었는지)까지 추적 가능

---

## 3) 대화 기반 상세 로그 (T0 기준 시간순)

### 3.1 아카이브 세션 말기 (2026-02-25 15:27 이전)

1. 브랜치/협업 폴더 기준 정리
- `feature/kt_p`, `jh2`, `feature/jh` 기준점 확인
- `workspace_collab`를 협업 기준 폴더로 확정
- “협업폴더 내부를 기존 루트 구조에 덮어쓰기” 방식으로 반영 정책 합의

2. 변경 허용 범위/호환 규칙 합의
- 파서/리트리버는 당분간 고정, 그래프/프롬프트/설정층 중심 수정
- dev 리트리버 변경을 가져오되 로컬 그래프/프롬프트와 충돌 없이 어댑터로 연결
- 현재 폴더 구조는 유지하고 실행 호환성 우선

3. 실행/배포 관점 요구 정리
- clone + env + data만으로 팀원이 바로 실행 가능한 상태 요청
- 데이터는 Git 추적 제외, 폴더 구조만 유지(`data_index/chroma_B` 포함)
- PR 충돌 대응 및 브랜치 푸시 순서(`jh2 -> jh -> dev`) 반복 확인

4. 품질 문제 집중 제기(오답/성능)
- 사업비/기관정보/TopN 등 실제 질의에서 오답 사례 다수 제시
- CSV 즉답 + DB fallback 워크플로 요구
- Streamlit 체감 속도 개선, 문맥 기억(후속질문) 동작, LangSmith 지연 개선 요청

5. 평가/개선 반복 루프 요청
- 새 eval dataset 테스트 + HTML 생성 반복 요청
- 목표 점수(4점대) 기준으로 정답률/커버리지 상향 요구
- 리트리버 수정 필요성 및 dev 최신 eval dataset 반영 여부 지속 확인

6. 세션 인계/기록 요구
- “대화 원문 전체 저장” 요구가 반복되었고, 시스템 제약상 원문 export 불가 확인
- 대화 결정사항 + Git/Eval 로그 기반 타임라인 문서화로 대체
- 그 결과로 `SESSION_CHAT_ALL_IN_ONE` 문서가 생성되고, 본 문서에 반영됨

근거:
- `../AI_7-team/docs/SESSION_CHAT_ALL_IN_ONE_2026-02-26.md`
- `../AI_7-team/docs/SESSION_TIMELINE_2026-02-26.md`

### 3.2 이번 세션 (T+00:18 이후)

1. T+00:18 레이턴시 미표시 문제 제기
- 요청: “평가 html 레이턴시 안나옴, 노드 시간 측정 가능하게”
- 조치: latency 전달/집계 보강 (`nodes.py`, `workflow.py`, `eval_retrieval.py`)
- 개선: `eval_report_latency_fix.html`에서 표시 복구

2. T+01:00~ 생성형 응답 필요성 제기
- 요청: “추출 결과 바탕으로 다시 생성 가능?”
- 조치: extractive_draft 기반 생성 경로 실험
- 개선: 생성 경로 관측 가능 + 이후 정책 비교 가능

3. T+01:30~ 문서 최신화/브랜치 동기화 반복 요청
- 요청: “문서 최신화”, “dev 당겨오기”, “내 패치+dev 패치 같이”
- 조치: dev 동기화 후 코드 차이 선별 반영
- 개선: 기준선 비교 가능 상태 확보

4. T+18:00~ DB 비교/검증 요청
- 요청: “backup DB 비교”, “(1)/(2)로 재테스트”, “600차원 DB 이유”
- 조치: DB별 라벨 분리 평가 실행
- 개선: `backupdb` 우세, `db1/testdb/db2` 저성능 명확화

5. T+19:00~ source 확장자/정답 판정 이슈
- 요청: “정답 확장자 없애달라”
- 조치: source 정규화/동치 비교 정렬
- 개선: source hit 계산 안정화

6. T+20:00~ 과검색/리포트 가독성 문제
- 요청: “검색 문서가 너무 과도함”, “불릿(-) 표시”
- 조치: report 정리 로직 보강 + 구조화 불릿 보존
- 개선: 카드 가독성 개선 (`f5ebb82`)

7. T+21:00~ API 오류/토큰 사용량 우려
- 요청: “OpenAI 에러?”, “무한루프처럼 계속 사용되나?”
- 조치: 재실행/경로 점검
- 개선: `rerun_20260226_noapierr` 생성, 무한루프 징후 없음

8. T+22:00~ 최신 dev 대비 성능 차이 분석
- 요청: “팀원 최신 dev랑 뭐가 다르냐”
- 조치: 동기화 후 기준선 재평가
- 개선: 차이 원인(DB/정책/코드) 분리 가능

9. T+26:57~ 생성 정책 최종 요구
- 요청: “생성은 보기좋게 정리만”, “extractive_draft 있으면 바로 반환”
- 조치: workflow short-circuit 적용
- 개선: dev 반영 완료 (`685d36b`)

10. T+27:47 이후 타임라인/보고서 통합 정리 요청
- 요청: “이전 실험 포함해서 상세 문서화”
- 조치: 아카이브 + 현재 세션 통합 타임라인 작성
- 개선: 본 문서로 단일 인수인계 기준 확정

---

## 4) 팀원/본인 작업 분리 (시간순)

### 4.1 팀원 주요 커밋 (2026-02-25 -> 2026-02-26)

- `c86f826` (youuuchul): multi-source Recall@K/MRR 지원
- `941de46` (youuuchul): GT source `.hwp -> .pdf` 정합화
- `c9b5f31` (youuuchul): report `--label` 지원
- `127bcb5` (youuuchul): strict multi-source hit position
- `6833b69` (youuuchul): csv_match/per-type latency 표시 보정
- `fd53598` (youuuchul): query memo 표시
- `db3e8bf` (youuuchul): metrics 문서 정리
- `048d68a` (Loah-Lee): single-doc ranking/fallback 정밀화
- `d6ca724` (Loah-Lee): precision fact anchor chunk 강화
- `f5cc477` (Loah-Lee): source metadata 정규화
- `e5a18a4` (Loah-Lee): source-based fallback + eval alignment
- `d758ebe` (Loah-Lee): dynamic retrieval strategy routing
- `07013fc` (Loah-Lee): csv source 보존 + robust hit position
- `f0ab7f3` (Loah-Lee): csv short-circuit hit 집계 보정
- `7db206a` (Loah-Lee): dynamic csv 답변/compact formatting
- `005df82`, `852d068`, `d683373` (adover134): parser/chunker/update 정리
- `76bbc72` (문진우): app 폴더 교체 반영

### 4.2 본인(panda) 커밋 타임라인 (시간순)

정렬 기준:
- `git log --author='panda' --since='2026-02-25 15:27 +0900' --reverse`
- dev 전용 반영 커밋(`f5ebb82`, `685d36b`)은 `.dev_worktree` 기준 시각 사용

| 순서 | 시각(KST) | 커밋 | 변경 요약 | 핵심 파일 |
|---:|---|---|---|---|
| 1 | 2026-02-25 16:06 | `6fd2f39` | source matching 보정 (recall/mrr, multi-source GT) | `src/evaluation/metrics.py` |
| 2 | 2026-02-25 16:10 | `80da4c4` | graph/workflow를 dev 기준으로 동기화 | `src/graph/nodes.py`, `src/graph/workflow.py` |
| 3 | 2026-02-25 16:21 | `3e79d92` | ranking fast-path 및 csv metadata 기반 랭킹 보정 | `src/graph/workflow.py` |
| 4 | 2026-02-25 21:19 | `233341a` | fact retrieval 안정화 + source-equivalent scoring 강화 | `src/graph/workflow.py`, `src/evaluation/metrics.py`, `src/prompts/templates.py` |
| 5 | 2026-02-26 09:45 | `0278d9b` | latency 전달 + draft-driven generation 통합 | `src/graph/nodes.py`, `src/graph/workflow.py`, `scripts/eval_retrieval.py` |
| 6 | 2026-02-26 11:37 | `8bdc178` | evidence-first 2-step answer generation | `src/graph/nodes.py`, `src/graph/workflow.py`, `src/prompts/templates.py` |
| 7 | 2026-02-26 14:55 | `d9237ef` | 최신 dev 병합 동기화(기준선 정렬) | merge commit |
| 8 | 2026-02-26 15:17 | `f5ebb82` (dev) | eval report 카드의 구조/불릿 보존 | `scripts/build_eval_report.py` |
| 9 | 2026-02-26 19:14 | `685d36b` (dev) | extractive_draft short-circuit (생성 스킵) | `src/graph/workflow.py` |

요약 효과:
- 평가 정합(소스 매칭) -> 검색 지표 안정화
- graph/workflow 동기화 + retrieval 안정화 -> 정답률/커버리지 개선 기반 확보
- latency 계측 전달 + 생성 short-circuit -> 평균 지연시간 크게 감소

---

### 4.3 코드 변경 전/후 (커밋 근거)

아래는 요청하신 형태대로, 실제 커밋 diff에서 확인한 `변경 전 -> 변경 후` 핵심 코드입니다.

1. `0278d9b` - 평가 레이턴시가 0.0으로 고정되던 문제
- 파일: `scripts/eval_retrieval.py`
- 변경 전:
```python
"latencies": {},
```
- 변경 후:
```python
"latencies": response.get("latencies", {}),
```
- 영향:
  - 그래프에서 계산한 단계별 레이턴시가 평가 JSON/HTML까지 전달됨.

2. `0278d9b` - 노드 단위 시간 측정 + 추출초안 전달
- 파일: `src/graph/nodes.py`
- 변경 전(요약):
```python
class QueryIntentParser:
    def __init__(...):
        self.last_parse_used_llm = False

    def parse(...):
        ...

class RFPAnswerGenerator:
    def __init__(...):
        self.llm = llm

    def generate(self, query, context, history=""):
        ...
```
- 변경 후(요약):
```python
import time

class QueryIntentParser:
    def __init__(...):
        self.last_parse_used_llm = False
        self.last_parse_elapsed = 0.0

    def parse(...):
        started = time.perf_counter()
        try:
            ...
        finally:
            self.last_parse_elapsed = time.perf_counter() - started

class RFPAnswerGenerator:
    def __init__(...):
        self.last_generation_elapsed = 0.0

    def generate(self, query, context, history="", extractive_draft=""):
        started = time.perf_counter()
        try:
            ...
        finally:
            self.last_generation_elapsed = time.perf_counter() - started
```
- 영향:
  - 파싱/생성 소요시간을 노드에서 직접 측정.
  - 생성 프롬프트에 `extractive_draft`를 주입할 수 있어 2-step 생성 실험 가능.

3. `0278d9b` - 워크플로 payload 표준화(단계별 latencies)
- 파일: `src/graph/workflow.py`
- 변경 전(요약):
```python
def answer(...):
    ...
    return payload  # 각 분기에서 개별 반환
```
- 변경 후(요약):
```python
def _finalize_payload(payload):
    payload["latencies"] = {
        "analyze_query": ...,
        "retrieve": ...,
        "extract_evidence": ...,
        "generate": ...,
    }
    return payload

def answer(...):
    ...
    return _finalize_payload(payload)
```
- 영향:
  - 빈 질의/short-circuit/실패 경로 포함 모든 응답에 latencies 구조를 일관 주입.
  - HTML에서 일부 케이스만 0.0으로 보이던 현상 완화.

4. `07013fc` - source hit 판정 강화(동치 소스명 비교)
- 파일: `src/evaluation/metrics.py`
- 변경 전:
```python
gt_set = set(gt_sources)
...
norm_src = _normalize_source_name(doc.get("source"))
if norm_src in gt_set and norm_src not in found_at:
    found_at[norm_src] = idx
```
- 변경 후:
```python
for gt_source in gt_sources:
    if gt_source in found_at:
        continue
    if _is_equivalent_source_name(retrieved_source, gt_source):
        found_at[gt_source] = idx
```
- 영향:
  - 확장자/표기 차이(`.pdf`, 공백/기호)로 miss 되던 hit position을 동치 비교로 보정.

5. `07013fc` - CSV short-circuit에서도 retrieved_docs 합성
- 파일: `src/graph/workflow.py`
- 변경 전(요약):
```python
if not isinstance(payload.get("retrieved_docs"), list):
    payload["retrieved_docs"] = self._serialize_retrieved_docs(self.vector_store.last_search_results)
```
- 변경 후(요약):
```python
if source_type == "csv" and isinstance(evidence_items, list):
    # evidence의 source로 retrieved_docs를 합성
    payload["retrieved_docs"] = csv_retrieved_docs
```
- 영향:
  - CSV 즉답 경로에서도 source-level Recall/MRR/hit_position 평가 가능.

6. `f5ebb82` - HTML 답변 카드 불릿/구조 보존
- 파일: `scripts/build_eval_report.py`
- 변경 전(요약):
```javascript
line = original
  .replace(/^\\s*[-*•]\\s*/, '')
  .replace(/^#+\\s*/, '')
```
- 변경 후(요약):
```javascript
const headingMatch = trimmed.match(/(핵심 답변|근거 요약|출처).../i);
...
if (hadBullet || inStructuredSection) {
  line = `- ${line}`;
}
```
- 영향:
  - `"핵심 답변/근거 요약/출처"` 구조와 `-` 불릿이 유지되어 가독성 개선.

7. `685d36b` - 추출 초안 우선 반환(extractive short-circuit)
- 파일: `src/graph/workflow.py`
- 변경 전:
```python
extractive_draft = extractive_answer
...
answer = self.answer_generator.generate(...)
```
- 변경 후:
```python
if extractive_draft:
    return _attach_retrieved_docs(self._build_answer_payload(
        answer=extractive_draft,
        answer_mode="extractive",
        ...
    ))
```
- 영향:
  - 추출 초안이 있으면 LLM 재생성을 생략하고 즉시 반환.
  - 생성은 사실상 "보기 좋게 정리" 보조 용도로 축소, latency 감소.

---

### 4.4 전/후 비교 요약 (발표용)

| 주제 | 변경 전 | 변경 후 | 추가된 것 | 효과(발표 포인트) |
|---|---|---|---|---|
| 레이턴시 수집/표시 | eval 단계에서 `latencies`를 비워서(`{}`) 받는 케이스 존재 | 그래프 응답의 `latencies`를 그대로 전달하고, workflow에서 전 경로 공통 finalize | `nodes.py` 단계 시간측정, `workflow.py` 공통 `latencies` 주입, `eval_retrieval.py` 전달 | 0.0/누락 케이스 감소, 병목 단계 파악 가능, 튜닝 근거 확보 |
| 검색 성능 판정(hit/recall) | source 문자열이 조금만 달라도 miss 처리 | 동치 소스명 비교 + CSV short-circuit에서도 `retrieved_docs` 합성 | `_is_equivalent_source_name` 기반 판정, CSV evidence->retrieved_docs 변환 | 확장자/표기 차이로 놓치던 hit 복구, Recall/MRR 신뢰도 향상 |
| 답변 생성 정책 | 추출 근거가 있어도 LLM 생성 단계로 진입 가능 | `extractive_draft` 있으면 즉시 extractive 반환(short-circuit) | `workflow.py` early return 분기 | 사실형 질문에서 지연시간 감소, C/AC 소폭 개선, 불필요 생성 축소 |
| 리포트 가독성 | 구조/불릿 정리가 깨져 읽기 어려운 카드 존재 | `"핵심 답변/근거 요약/출처"` 및 `-` 불릿 보존 | `build_eval_report.py` 정리 로직 보강 | 리뷰/발표 시 해석 시간 감소, 결과 설명력 상승 |

발표용 1분 요약 스크립트(초안):
1. "이번 패치의 핵심은 생성을 늘리는 게 아니라, 근거 추출을 신뢰할 수 있게 만드는 것이었습니다."
2. "먼저 레이턴시가 0.0으로 보이던 문제를 고쳐서 질문 단위로 분석/검색/근거추출/생성 시간을 분리 관측 가능하게 했습니다."
3. "다음으로 source 판정 로직을 강화해 확장자나 파일명 표기 차이로 hit가 누락되던 문제를 줄였습니다."
4. "그리고 추출 초안이 충분하면 LLM 재생성을 건너뛰도록 바꿔, 응답 지연을 낮추면서 정확도/커버리지를 유지 또는 개선했습니다."
5. "마지막으로 HTML 리포트 가독성을 보완해 팀원이 같은 결과를 더 빠르게 검증할 수 있도록 정리했습니다."

핵심 수치(해당 타임라인 기준):
- `dev_dataset_latest -> extractive_only_20260226`
- `Correctness: 3.6 -> 3.7 (+0.1)`
- `Answer Coverage: 3.45 -> 3.6 (+0.15)`
- `Recall/MRR: 동일 (1.0 / 0.95)`
- `Total Latency: 20.314s -> 10.886s`

---

### 4.5 작업별 점수 개선 요약 (PPT용)

아래 표는 "작업 1개 해결 -> 직전 대비 점수 변화" 기준으로 정리했습니다.

| 작업 | 해결한 문제 | 비교 기준(전 -> 후) | Correctness | Coverage | Recall@5 | MRR | 보조지표/해석 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | DB 선택/연결 오류로 hit 저하 | `testdb_20260226 -> backupdb_20260226` | `+2.55` (1.20->3.75) | `+2.50` (1.00->3.50) | `+0.70` (0.20->0.90) | `+0.70` (0.20->0.90) | DB 정상화가 성능에 가장 큰 영향 |
| 2 | 최신 dev 동기화 후 로컬 패치 반영 | `latest_sync_20260226 -> run_20260226_current_patch` | `+0.30` (3.45->3.75) | `+0.00` (3.35->3.35) | `+0.00` (0.90->0.90) | `+0.00` (0.90->0.90) | 정확성 중심 미세 개선 |
| 3 | 생성 과개입으로 근거형 답변 약화 | `dev_dataset_latest -> extractive_only_20260226` | `+0.10` (3.60->3.70) | `+0.15` (3.45->3.60) | `+0.00` (1.00->1.00) | `+0.00` (0.95->0.95) | Faithfulness `-0.15`, Context Relevance `-0.05` trade-off |
| 4 | 레이턴시 관측 불가/0.0 누락 | `dev_dataset_latest -> extractive_only_20260226` | - | - | - | - | Total latency `20.314s -> 10.886s` (`-46.4%`) |
| 5 | 세션 초기 대비 종합 개선 | `current.before_dev_run -> latest_sync_20260226` | `+1.65` (1.80->3.45) | `+1.75` (1.60->3.35) | `+0.15` (0.75->0.90) | `+0.15` (0.75->0.90) | 평가/워크플로/리트리버 정합 개선 누적 효과 |

PPT용 문구(그대로 사용 가능):
1. "가장 큰 성능 차이는 알고리즘보다 DB 품질/연결 정합에서 발생했습니다."
2. "그 다음 단계에서 dev 동기화 + 로컬 패치로 정확성을 추가로 끌어올렸습니다."
3. "마지막으로 생성 단계를 정리용으로 제한해 정확도/커버리지를 유지하면서 지연시간을 약 46% 줄였습니다."

주의(발표 시 한 줄 언급):
- 일부 비교는 코드 변경과 DB/실행조건 변경이 동시에 포함되어 있어, 절대적 인과보다는 "실험 기준선 대비 개선폭"으로 해석하는 것이 정확합니다.

---

### 4.6 프롬프트/그래프 담당 관점: 응답 경로 + 문제별 변화

응답 출력 경로(`src/graph/workflow.py`, `src/graph/nodes.py`)는 아래 3가지로 동작합니다.

1. `extractive` 우선 경로
- 조건: `_should_try_extractive_first(...)`가 참이고 `extractive_draft` 확보
- 동작: `685d36b` 이후 `extractive_draft`를 즉시 반환(LLM 재생성 스킵)
- 효과: 사실형 질문에서 `answer_mode=extractive` 비중 증가, 생성 지연 감소

2. `generative` 경로
- 조건: 추출 초안이 없거나 비교/요약형으로 생성이 필요한 경우
- 동작: `answer_generator.generate(query, context, history, extractive_draft=...)`
- 프롬프트: `[핵심 답변] / [근거 요약] / [출처]` 구조 강제

3. `hybrid` fallback 경로
- 조건: 생성 결과가 불확실/오류이거나 비교 구조가 잘못 생성된 경우
- 동작: 규칙 기반 근거 답변으로 재대체(`_build_non_llm_answer`)
- 효과: 환각성 문장 완화, 근거형 답변 회귀

생성 경로 변화(비교 기준: `dev_dataset_latest -> extractive_only_20260226`):
- `answer_mode` 분포: `extractive 13 -> 17`, `generative 6 -> 1`, `hybrid 1 -> 2`
- `generate latency > 0` 문항 수: `7/20 -> 3/20`
- 문항 평균 `generate` 시간: `17.28s -> 8.31s`
- 총 평균 latency: `20.314s -> 10.886s` (`-46.4%`)

문제별 변화(응답문장 기준, 같은 답변 제외):
- 전체 20문항 중 응답 텍스트 변경 문항: `6문항` (`eval_007`, `eval_008`, `eval_009`, `eval_011`, `eval_016`, `eval_017`)
- C+AC 기준 개선: `1문항` (`eval_016`)
- C+AC 기준 악화: `1문항` (`eval_017`)
- C+AC 동일(지연/모드 중심 변화): `4문항` (`eval_007`, `eval_008`, `eval_009`, `eval_011`)

| 문항 | 유형 | answer_mode 변화 | 점수 변화(C/AC/F/CR) | 총 지연(s) 변화 | 비고 |
|---|---|---|---|---|---|
| `eval_007` | single_doc | generative->extractive | `+0/+0/+0/+0` | `26.2 -> 0.4` | 정답 유지 + 대폭 단축 |
| `eval_008` | single_doc | generative->extractive | `+0/+0/+0/+0` | `36.0 -> 0.3` | 정답 유지 + 대폭 단축 |
| `eval_009` | single_doc | generative->extractive | `+0/+0/-2/-2` | `41.4 -> 0.2` | 응답 단순화로 F/CR 하락 |
| `eval_011` | single_doc | generative->extractive | `+0/+0/-1/+0` | `23.2 -> 0.3` | 정답 유지 + F 소폭 하락 |
| `eval_016` | single_doc | generative->generative | `+4/+3/+3/+0` | `109.5 -> 80.0` | 개선폭 최대 문항 |
| `eval_017` | single_doc | generative->hybrid | `-1/-1/-1/+0` | `55.7 -> 37.5` | 악화 대표 문항 |

대표 출력 변화(`eval_results*.json`의 `generated_answer` 필드 비교):
- 주의: `generated_answer`는 필드명이며, 실제로는 `extractive`/`hybrid` 응답도 포함됩니다.
1. `eval_016` (대폭 개선)
- Before: "`검색된 1개 사업(입찰 요약)`" 수준의 일반 요약
- After: "`AS-IS/TO-BE`, 연동/표준화/권한/암호화/시험운영" 등 질문 축에 맞는 항목형 답변으로 개선

2. `eval_017` (악화 사례)
- Before: "도면 치수 명시 없음"으로 보수 응답
- After: "직접 내방 확인 가능" 문구 중심으로 변해 C/AC 하락

3. `eval_007`, `eval_008` (정답 유지 + 지연 단축)
- `generative -> extractive`로 전환되었지만 C/AC/F/CR은 유지
- 생성 단계 제거로 지연이 수십 초에서 1초 미만으로 감소

해석(프롬프트/그래프 담당 결론):
- 이번 변경은 "답변 문장 품질의 평균 상승"보다 "근거형 안정성 + 지연 단축"에 더 큰 효과
- 대부분 문항에서 생성 호출을 줄여도 C/AC는 유지 또는 소폭 개선
- 악화 문항(`eval_004`, `eval_014`, `eval_017`)은 추출 우선 정책에서의 누락/요약 손실 보완이 다음 개선 포인트
- 질문별 실제 출력 비교용 파일: `eval_resources/eval_compare_extractive_only_20260226.csv`
- 로그 전체 비교용 파일:
  - `eval_resources/eval_answer_compare_all_logs_long_20260227.csv`
  - `eval_resources/eval_answer_compare_matrix_by_id_20260227.csv`
  - `eval_resources/eval_answer_compare_transitions_20260227.csv`
  - `eval_resources/eval_answer_compare_transition_detail_20260227.csv`

로그 간 응답 변경 전이(문장 기준) 상위:
- `v5-pdf-fix -> latency_fix`: `20/20` 변경 (`100%`)
- `backupdb_20260226 -> db2_main_20260226`: `20/20` 변경 (`100%`)
- `testdb_20260226 -> backupdb_20260226`: `15/20` 변경 (`75%`)
- `dev_dataset_latest -> extractive_only_20260226`: `6/20` 변경 (`30%`)

### 4.7 질문별 실제응답 비교표 (커밋 반영 흐름)

기준 로그: `before_dev -> current_patch -> dev_latest -> extractive_only`

| 질문(id) | 정답(요약) | 실제응답1(before_dev) | 실제응답2(current_patch) | 실제응답3(dev_latest) | 실제응답4(extractive_only) |
|---|---|---|---|---|---|
| eval_001 강릉어선안전조업국 상황관제시스템 구축 사업의 총 사업 예산(부… | 사업 금액은 210,000,000원(금 이억일천만원, VAT 포… | 수협중앙회 문서 기준 사업비는 2,996,000,000원입니다. | 수협중앙회 사업비은(는) `약 2.1억 원 (210,000,000원) (부가가치세 포… | 동일 | 동일 |
| eval_002 한국수자원공사에서 진행하는 사업은 총 몇 개이며, 각각의 사업… | 총 3개의 사업이 진행 중이며, 사업명은 다음과 같습니다. 1.… | 한국수자원공사 문서에서 질문 관련 조항을 확인했습니다. | 한국수자원공사에서 진행 중인 사업은 총 3개입니다. | 동일 | 동일 |
| eval_003 2024년 대학산학협력활동 실태조사 시스템(UICC) 기능개선… | 입찰 참여 시작일은 2024년 10월 14일 오전 10시이며, … | 한국연구재단 문서 기준 문서 기준 기한/일정 값은 `2024 년`입니다. | 한국연구재단 입찰 참여 시작일은 `2024-10-14 오전 10시`이고, 마감일은 `… | 동일 | 동일 |
| eval_004 국가과학기술지식정보서비스(NTIS)에서 실시하는 통합정보시스템… | 본 사업의 추정 사업비는 140,000,000원이며, 입찰 참여… | 국가과학기술지식정보서비스 기본 정보입니다. | 국가과학기술지식정보서비스 요약입니다. | 동일 | 동일 |
| eval_005 사단법인 보험개발원 '실손보험 청구 전산화 시스템 구축 사업'… | CPU는 2 x 2.90GHz Intel Xeon Gold541… | 📊 **검색된 1개 사업** (입찰 요약) | 사단법인 보험개발원 CPU 최소 사양은 `2 x 2.90GHz Intel Xeon G… | 동일 | 동일 |
| eval_006 고려대학교 차세대 포털·학사 정보시스템 구축사업에서 개발에 사… | 저작권에 문제가 없어야 하며, 비용이 발생할 경우 주사업자가 부… | 고려대학교 문서에서 이미지/글꼴 저작권 비용 부담 주체를 직접 명시한 조항… | 고려대학교 책임 주체는 `사업자(제안사/주사업자)`로 확인됩니다. | 동일 | 동일 |
| eval_007 사업장 사회보험료 지원 고시 개정에 따른 정보시스템 보완 개발… | 계약체결일로부터 180일 이내 (6개월)입니다. | 국민연금공단 문서 기준 문서 기준 값은 `180 일`입니다. | 국민연금공단 값은 `180 일`입니다. | 본 사업의 기간은 계약체결일부터 180일(6개월)입니다. | 국민연금공단 값은 `180 일`입니다. |
| eval_008 국민연금공단_2024년 이러닝시스템 운영 용역 세부산출내역서에… | 11,000명에게 제공됩니다. | 국민연금공단 문서 기준 문서 기준 단위/수량 값은 `113,330명`입니다. | 국민연금공단 직무교육 대상 인원은 `11,000명`입니다. | 11,000명: 문서에 따르면 직무교육은 11,000명에게 제공됩니다. | 국민연금공단 직무교육 대상 인원은 `11,000명`입니다. |
| eval_009 을지대학교 비교과시스템 개발 사업에서 계약상대자는 사업 완료 … | 완료보고서, 납품 및 검사조서를 제출하여 감독관에게 검사 승인을… | A 문서: ## 1. 본인은을지대학교비교과시스템개발사업관련업무중알게될일체의내용이직무상… | 을지대학교 주요 제출서류/준수사항은 다음 4개 항목입니다. | 문서에는 사업 완료 후 검사(승인) 시 제출해야 할 서류 목록이 명시되어 있지 않습니… | 을지대학교 주요 제출서류/준수사항은 다음 4개 항목입니다. |
| eval_010 국가과학기술지식정보서비스 통합정보시스템 고도화 용역에서 기술능… | 기술능력 평가분야 배점한도의 85% 이상인 제안사를 협상적격자로… | 제공된 문서에서 `국가과학기술지식정보서비스` 관련 정보를 찾지 못했습니다. | 국가과학기술지식정보서비스 협상적격자 선정 기준은 `기술능력 평가점수 배점한도의 85%… | 동일 | 동일 |
| eval_011 BioIN_의료기기산업 종합정보시스템(정보관리기관) 기능개선 … | 웹페이지의 용량은 3MB 이내로 개발해야 하며 단, 홍보 등 특… | BioIN 문서 기준 문서 기준 용량 값은 `3MB`입니다. | BioIN 용량 값은 `3MB`입니다. | 웹페이지 용량은 3MB 이내로 개발해야 합니다. 단, 홍보 등 특성에 따라 3MB를 … | BioIN 용량 값은 `3MB`입니다. |
| eval_012 한국농수산식품유통공사 농산물가격안정기금 정부예산회계연계시스템에… | 시스템은 장애가 발생하면 12시간 이내에 데이터를 복구해야 합니… | 한국농수산식품유통공사 문서 기준 질문의 핵심값을 특정할 직접 근거가 부족해 단정 답변… | 한국농수산식품유통공사 복구기한은 `12시간이내`입니다. | 동일 | 동일 |
| eval_013 수문자료정보관리시스템(HDIMS) 재구축사업(3단계)의 추진 … | 수문자료정보관리시스템(HDIMS) 재구축사업(3단계)의 추진 목… | 한국수자원조사기술원 문서에서 질문 관련 조항을 확인했습니다. | 한국수자원조사기술원 추진 목표는 다음과 같습니다. | 동일 | 동일 |
| eval_014 한국수출입은행의 모잠비크 마푸토 지능형교통시스템(ITS) 구축… | Guidelines for the Economic Analysi… | 한국수출입은행 문서에서 질문 관련 조항을 확인했습니다. | 한국수출입은행 참고 가이드 관련 근거는 `(EDCF Feasibility Study … | 동일 | 동일 |
| eval_015 남서울대학교 스마트 정보시스템 활성화(학사) 사업 수행 시 참… | 참여인원에 대해 월 1회 정보보안교육을 수행하고, 교육결과는 발… | 남서울대학교 문서 기준 문서의 직접 근거 문구는 `# [ 혁신 - 국고 ] 스마트 정… | 남서울대학교 정보보안교육 주기는 `월1회`입니다. | 동일 | 동일 |
| eval_016 세종테크노파크 인사정보 전산시스템 구축 사업에서 관련 소프트웨… | 세종테크노파크 인사정보 전산시스템 구축 사업의 관련 소프트웨어 … | 세종테크노파크 문서에서 질문 관련 조항을 확인했습니다. | 세종테크노파크 문서에서 질문 관련 조항을 확인했습니다. | 📊 **검색된 1개 사업** (입찰 요약) | 문서에는 현행(AS‐IS)에서 사용 중인 개별 소프트웨어명·제품 현황은 명시되어 있지… |
| eval_017 우즈베키스탄 열린 의정활동 상하원 사업의 '지역의회 회의실' … | 최소규격의 가로 총 길이는 10,000mm이며, 세부 분할 치수… | 📊 **검색된 11개 사업** (입찰 요약) | KOICA 전자조달 치수 관련 근거는 `도면열람및세부사항은직접내방하여확인가능`입니다. | 문서에 가로(가운데 문 포함) 최소규격·최대규격의 세부 치수는 명시되어 있지 않습니다… | KOICA 전자조달 치수 관련 근거는 `도면열람및세부사항은직접내방하여확인가능`입니다. |
| eval_018 사단법인 아시아물위원회 사무국의 ‘우즈벡-키르기즈스탄 기후변화… | 본 사업의 사업책임자(PM)는 제안사 소속 1명(공동도급 시 대… | 사단법인아시아물위원회사무국 문서 기준 문서 기준 핵심투입인력 관련 직접 근거는 `- … | 사단법인아시아물위원회사무국 PM 산정 기준은 `참여율은 직접 참여 100%, 감독/사… | 동일 | 동일 |
| eval_019 축산물품질평가원에서 주관하는 사업들과 각 사업의 추진 배경과 … | 축산물품질평가원에서 주관하는 주요 사업과 각 사업의 추진 배경 … | 축산물품질평가원 문서 기준 문서의 직접 근거 문구는 `나. 추진배경및필요성------… | 축산물품질평가원 주요 사업의 추진 배경/목적 요약입니다. | 동일 | 동일 |
| eval_020 한국연구재단이 추진하는 사업 중, 사업기간이 상대적으로 짧고 … | 조건에 부합하는 사업은 '2024년 대학 산학협력활동 실태조사 … | 한국연구재단 문서에서 질문 관련 조항을 확인했습니다. | 한국연구재단 단위/수량 값은 `10MB`입니다. | 동일 | 동일 |

요약(응답 문장 변경률):
- `실제응답1(before_dev) -> 실제응답2(current_patch)`: `20/20` 변경 (`100.0%`)
- `실제응답2(current_patch) -> 실제응답3(dev_latest)`: `6/20` 변경 (`30.0%`)
- `실제응답3(dev_latest) -> 실제응답4(extractive_only)`: `6/20` 변경 (`30.0%`)

### 4.8 답변별 점수 비교 분석 (4단계)

분석 기준:
- 비교 단계: `before_dev -> current_patch -> dev_latest -> extractive_only`
- 지표: `Correctness(C)`, `Answer Coverage(AC)`, `Faithfulness(F)`, `Context Relevance(CR)`
- 상세 산출물: `eval_resources/eval_score_compare_4runs_20260227.csv`

단계별 평균 점수:

| 단계 | C | AC | F | CR |
|---|---:|---:|---:|---:|
| before_dev | 1.80 | 1.60 | 3.95 | 3.75 |
| current_patch | 3.75 | 3.35 | 4.35 | 4.65 |
| dev_latest | 3.60 | 3.45 | 4.25 | 4.80 |
| extractive_only | 3.70 | 3.60 | 4.10 | 4.75 |

단계별 `C+AC` 변화 개수:
- `before_dev -> current_patch`: 개선 `14`, 악화 `1`, 동일 `5`
- `current_patch -> dev_latest`: 개선 `4`, 악화 `4`, 동일 `12`
- `dev_latest -> extractive_only`: 개선 `3`, 악화 `3`, 동일 `14`

핵심 해석:
1. `before_dev -> current_patch`에서 정확성 계열(C/AC)이 가장 크게 상승
- 파이프라인/그래프 정합화의 효과가 가장 크게 나타난 구간

2. `dev_latest -> extractive_only`에서는 C/AC 소폭 상승, F/CR 소폭 하락
- 근거형 우선으로 지연은 줄었지만 일부 문항에서 충실성(F) 평가가 낮아짐

3. 문항별 최대 개선/악화 (`before_dev -> extractive_only`, C+AC 기준)
- 최대 개선: `eval_005`, `eval_010` (`+10`)
- 다음 개선: `eval_012` (`+9`), `eval_001`, `eval_003` (`+8`)
- 최대 악화: `eval_009` (`-8`), `eval_017` (`-1`)

응답은 `동일`인데 점수가 바뀐 케이스 (`dev_latest -> extractive_only`):
- `eval_002`: `dC/dAC/dF/dCR = 0/+1/0/+1`
- `eval_004`: `-1/0/0/0`
- `eval_010`: `0/0/-1/0`
- `eval_014`: `0/-1/0/0`
- `eval_015`: `0/+1/0/0`
- `eval_020`: `0/0/-1/0`

해석:
- LLM-as-Judge 특성상 답변 문장 동일 여부와 점수 변화가 항상 1:1 대응되지는 않음
- 따라서 발표 시에는 `문장 변화`와 `점수 변화`를 분리해서 설명하는 것이 정확함

### 4.9 문제별 점수 비교/해석 (20문항 상세)

비교 기준: `before_dev -> current_patch -> dev_latest -> extractive_only`

표기 규칙: `C/AC/F/CR`

| 문항 | 유형 | before_dev | current_patch | dev_latest | extractive_only | C+AC Δ(최종-초기) | 답변문장 변경 단계 | 해석 |
|---|---|---:|---:|---:|---:|---:|---|---|
| eval_001 강릉어선안전조업국 상황관제시스템 구축 사업의 총 사업 예산(부가가치세 포함)… | csv_match | 1/1/5/1 | 5/5/4/5 | 5/5/4/5 | 5/5/4/5 | +8 | 1->2 | 초기 저점에서 대폭 개선 후 안정화. |
| eval_002 한국수자원공사에서 진행하는 사업은 총 몇 개이며, 각각의 사업명은 무엇입니까? | csv_match | 2/2/4/3 | 3/3/2/4 | 3/3/2/3 | 3/4/2/4 | +3 | 1->2 | 소폭 개선(부분 항목 회복). 추출 우선 단계에서 추가 개선. |
| eval_003 2024년 대학산학협력활동 실태조사 시스템(UICC) 기능개선 사업의 입찰 … | csv_match | 1/1/2/3 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +8 | 1->2 | 초기 저점에서 대폭 개선 후 안정화. |
| eval_004 국가과학기술지식정보서비스(NTIS)에서 실시하는 통합정보시스템 고도화 용역의… | csv_match | 3/2/2/3 | 4/2/5/4 | 4/3/5/5 | 3/3/5/5 | +1 | 1->2 | 소폭 개선(부분 항목 회복). 추출 우선 단계에서 일부 하락. |
| eval_005 사단법인 보험개발원 '실손보험 청구 전산화 시스템 구축 사업' RFP 기준으… | single_doc | 0/0/1/3 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +10 | 1->2 | 초기 저점에서 대폭 개선 후 안정화. |
| eval_006 고려대학교 차세대 포털·학사 정보시스템 구축사업에서 개발에 사용된 이미지·글… | single_doc | 2/2/5/5 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +6 | 1->2 | 전반 개선, 후반 미세 변동. |
| eval_007 사업장 사회보험료 지원 고시 개정에 따른 정보시스템 보완 개발사업에서 사업기… | single_doc | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +0 | 1->2,2->3,3->4 | 최종 기준 유지(단계별 변동 상쇄). |
| eval_008 국민연금공단_2024년 이러닝시스템 운영 용역 세부산출내역서에 따르면 '직무… | single_doc | 2/2/2/5 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +6 | 1->2,2->3,3->4 | 전반 개선, 후반 미세 변동. |
| eval_009 을지대학교 비교과시스템 개발 사업에서 계약상대자는 사업 완료 후 검사 승인을… | single_doc | 5/5/5/5 | 1/0/2/3 | 1/1/5/5 | 1/1/3/3 | -8 | 1->2,2->3,3->4 | 최종 악화, 보완 필요 문항. |
| eval_010 국가과학기술지식정보서비스 통합정보시스템 고도화 용역에서 기술능력 평가점수로 … | single_doc | 0/0/5/0 | 5/5/4/5 | 5/5/3/5 | 5/5/2/5 | +10 | 1->2 | 초기 저점에서 대폭 개선 후 안정화. |
| eval_011 BioIN_의료기기산업 종합정보시스템(정보관리기관) 기능개선 사업(2차)에서… | single_doc | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | 5/5/4/5 | +0 | 1->2,2->3,3->4 | 최종 기준 유지(단계별 변동 상쇄). |
| eval_012 한국농수산식품유통공사 농산물가격안정기금 정부예산회계연계시스템에서 시스템 장애… | single_doc | 1/0/5/4 | 5/5/5/5 | 5/5/5/5 | 5/5/5/5 | +9 | 1->2 | 초기 저점에서 대폭 개선 후 안정화. |
| eval_013 수문자료정보관리시스템(HDIMS) 재구축사업(3단계)의 추진 목표는 무엇입니… | single_doc | 1/1/4/4 | 4/3/5/4 | 3/3/5/5 | 3/3/5/5 | +4 | 1->2 | 전반 개선, 후반 미세 변동. |
| eval_014 한국수출입은행의 모잠비크 마푸토 지능형교통시스템(ITS) 구축사업 RFP 텍… | single_doc | 0/0/5/5 | 2/1/5/3 | 2/2/5/3 | 2/1/5/3 | +3 | 1->2 | 소폭 개선(부분 항목 회복). 추출 우선 단계에서 일부 하락. |
| eval_015 남서울대학교 스마트 정보시스템 활성화(학사) 사업 수행 시 참여인원에 대한 … | single_doc | 1/1/5/5 | 4/4/4/5 | 4/3/5/5 | 4/4/5/5 | +6 | 1->2 | 전반 개선, 후반 미세 변동. 추출 우선 단계에서 추가 개선. |
| eval_016 세종테크노파크 인사정보 전산시스템 구축 사업에서 관련 소프트웨어 현황 및 개… | single_doc | 2/1/5/5 | 2/1/5/5 | 1/1/1/5 | 5/4/4/5 | +6 | 1->2,2->3,3->4 | 전반 개선, 후반 미세 변동. 추출 우선 단계에서 추가 개선. |
| eval_017 우즈베키스탄 열린 의정활동 상하원 사업의 '지역의회 회의실' 도면 예시에서 … | single_doc | 1/0/1/1 | 1/0/2/5 | 1/1/2/5 | 0/0/1/5 | -1 | 1->2,2->3,3->4 | 최종 악화, 보완 필요 문항. 추출 우선 단계에서 일부 하락. |
| eval_018 사단법인 아시아물위원회 사무국의 ‘우즈벡-키르기즈스탄 기후변화대응 사업’ 제… | single_doc | 2/2/5/5 | 4/3/5/5 | 3/2/4/5 | 3/2/4/5 | +1 | 1->2 | 소폭 개선(부분 항목 회복). |
| eval_019 축산물품질평가원에서 주관하는 사업들과 각 사업의 추진 배경과 목적을 알려줘 | multi_doc | 1/1/3/5 | 4/4/5/5 | 4/4/5/5 | 4/4/5/5 | +6 | 1->2 | 전반 개선, 후반 미세 변동. |
| eval_020 한국연구재단이 추진하는 사업 중, 사업기간이 상대적으로 짧고 신규 구축이 아… | multi_doc | 1/1/5/3 | 1/1/4/5 | 1/1/4/5 | 1/1/3/5 | +0 | 1->2 | 최종 기준 유지(단계별 변동 상쇄). |

문항별 코멘트(팀 공유용):
- `eval_001` (csv_match): C+AC `2 -> 10` (`+8`), mode `->extractive`, 응답문장 `변경`
- `eval_002` (csv_match): C+AC `4 -> 7` (`+3`), mode `->extractive`, 응답문장 `변경`
- `eval_003` (csv_match): C+AC `2 -> 10` (`+8`), mode `->extractive`, 응답문장 `변경`
- `eval_004` (csv_match): C+AC `5 -> 6` (`+1`), mode `->extractive`, 응답문장 `변경`
- `eval_005` (single_doc): C+AC `0 -> 10` (`+10`), mode `->extractive`, 응답문장 `변경`
- `eval_006` (single_doc): C+AC `4 -> 10` (`+6`), mode `->extractive`, 응답문장 `변경`
- `eval_007` (single_doc): C+AC `10 -> 10` (`+0`), mode `->extractive`, 응답문장 `변경`
- `eval_008` (single_doc): C+AC `4 -> 10` (`+6`), mode `->extractive`, 응답문장 `변경`
- `eval_009` (single_doc): C+AC `10 -> 2` (`-8`), mode `->extractive`, 응답문장 `변경`
- `eval_010` (single_doc): C+AC `0 -> 10` (`+10`), mode `->extractive`, 응답문장 `변경`
- `eval_011` (single_doc): C+AC `10 -> 10` (`+0`), mode `->extractive`, 응답문장 `변경`
- `eval_012` (single_doc): C+AC `1 -> 10` (`+9`), mode `->extractive`, 응답문장 `변경`
- `eval_013` (single_doc): C+AC `2 -> 6` (`+4`), mode `->extractive`, 응답문장 `변경`
- `eval_014` (single_doc): C+AC `0 -> 3` (`+3`), mode `->extractive`, 응답문장 `변경`
- `eval_015` (single_doc): C+AC `2 -> 8` (`+6`), mode `->extractive`, 응답문장 `변경`
- `eval_016` (single_doc): C+AC `3 -> 9` (`+6`), mode `->generative`, 응답문장 `변경`
- `eval_017` (single_doc): C+AC `1 -> 0` (`-1`), mode `->hybrid`, 응답문장 `변경`
- `eval_018` (single_doc): C+AC `4 -> 5` (`+1`), mode `->extractive`, 응답문장 `변경`
- `eval_019` (multi_doc): C+AC `2 -> 8` (`+6`), mode `->extractive`, 응답문장 `변경`
- `eval_020` (multi_doc): C+AC `2 -> 2` (`+0`), mode `->hybrid`, 응답문장 `변경`

### 4.10 개선/악화 원인 분석 (근거 포함)

분석 범위:
- 최종 정책 비교(`dev_latest -> extractive_only`)를 중심으로 개선/악화 원인 분해
- 보조로 전체 흐름(`before_dev -> current_patch -> dev_latest -> extractive_only`)에서 대표 케이스 확인

개선 원인(대표):
1. 추출 우선 응답에서 핵심 슬롯 복원
- 대표 문항: `eval_016` (`C+AC +7`, `2->3`에서 저하 후 `3->4`에서 회복)
- 근거: Judge reason이 "기대 답변 핵심 항목 반영"으로 변경됨
- 해석: 생성형 요약 문구보다 질문 축(AS-IS/TO-BE, 연동/표준화/권한/보안) 중심 응답이 점수 개선에 기여

2. 단일 사실 질의의 안정적 유지 + 지연 단축
- 대표 문항: `eval_007`, `eval_008`
- 근거: `generative->extractive` 전환 후 C/AC 유지, latency 대폭 감소
- 해석: 사실형/수치형은 추출 우선이 성능-지연 균형에 유리

3. 부분 누락 문항의 커버리지 보정
- 대표 문항: `eval_002`, `eval_015` (`AC +1`)
- 근거: 답변문장 유사하지만 Judge에서 커버리지 상향 판정
- 해석: 동일 답변이라도 핵심 항목 포함 여부 판단이 재평가되며 미세 개선 발생

악화 원인(대표):
1. 다중 핵심항목 질문에서 일부 항목 누락
- 대표 문항: `eval_004` (`C+AC -1`)
- 근거: 예산/일정은 맞지만 "주요 사업 범위" 누락으로 정확성 하락
- 해석: CSV 기반 답변에서 다중 슬롯(금액+일정+범위) 동시 커버가 부족

2. 기대 정답이 다중 가이드/근거를 요구하는 문항에서 단일 근거로 수렴
- 대표 문항: `eval_014` (`C+AC -1`)
- 근거: 기대 답변(ADB/EU 가이드 포함) 대비 EDCF 단일 언급으로 AC 하락
- 해석: 추출 우선 정책에서 "복수 근거 병합"이 약하면 커버리지 손실

3. 도면/규격형 수치 질의의 근거 부재 처리 실패
- 대표 문항: `eval_017` (`C+AC -2`)
- 근거: 요구 치수(최소/최대 및 분할값)를 제시하지 못해 C/AC 0 수준
- 해석: 문서 본문에 치수 근거가 희박하거나 파싱되지 않은 경우, 안전응답이 점수상 큰 손실로 이어짐

4. 전체 타임라인의 대표 회귀 문항
- 대표 문항: `eval_009` (`before_dev -> current_patch`에서 `C+AC 10 -> 1` 급락)
- 근거: "완료보고서/검사조서" 대신 입찰참가 서류 중심 응답으로 전환
- 해석: 질의 의도(완료 후 검사 단계)와 다른 섹션 근거를 우선 선택한 케이스

패턴 요약(`dev_latest -> extractive_only`, C+AC 기준):
- 개선 3문항: `eval_002`, `eval_015`, `eval_016`
- 악화 3문항: `eval_004`, `eval_014`, `eval_017`
- 공통점:
  - 개선군은 "핵심 슬롯(주체/요건) 직접 제시" 성향
  - 악화군은 "복수 근거/다중 항목 동시 충족" 요구가 큰 문항


---

## 5) 현재 상태 (T+43:19, 2026-02-27 10:46 KST 기준)

- dev 최신 반영 커밋: `685d36b`
- 정책:
  - `extractive_draft` 존재 시 extractive 우선 반환
  - 생성은 정리/보완 중심
- 최근 비교 결론:
  - `dev_dataset_latest` -> `extractive_only_20260226`
  - `Correctness +0.10`, `Coverage +0.15`
  - `Recall/MRR` 동일
  - 평균 지연 `20.314s -> 10.886s`
- 비교 산출물:
  - 질문별 정답/실제응답 비교 CSV: `eval_resources/eval_compare_extractive_only_20260226.csv`
  - 로그 전체 질문/응답 long CSV: `eval_resources/eval_answer_compare_all_logs_long_20260227.csv`
  - 질문별 로그 응답 매트릭스 CSV: `eval_resources/eval_answer_compare_matrix_by_id_20260227.csv`
  - 로그 전이별 응답 변경률 CSV: `eval_resources/eval_answer_compare_transitions_20260227.csv`
  - 로그 전이 문항 상세 CSV: `eval_resources/eval_answer_compare_transition_detail_20260227.csv`

---

## 6) 근거 커맨드 (재현용)

```bash
# 아카이브 세션 기준 문서
sed -n '1,260p' ../AI_7-team/docs/SESSION_TIMELINE_2026-02-26.md

# 아카이브 평가 결과 수
find ../AI_7-team/eval -maxdepth 1 -type f -name 'eval_results*.json' | wc -l
find ../AI_7-team/eval -maxdepth 1 -type f -name 'eval_report*.html' | wc -l

# 현재 세션 평가 결과 수
find eval_resources -maxdepth 1 -type f -name 'eval_results*.json' | wc -l

# 이번 세션 커밋 타임라인
git log --since='2026-02-25' --until='2026-02-27' \
  --date=iso --pretty=format:'%h|%ad|%an|%s'

# dev 최종 반영 커밋 확인
git -C .dev_worktree show --stat --oneline -n 1 685d36b
```
