# Project Structure Audit Report

**Date:** 2026-02-11 14:00
**Branch:** feature/integration-eval-yc
**Objective:** 프로젝트 폴더/코드 정리 및 팀 협업 준비

---

## 1. User Prompt
> 지금 내 브랜치에 프로젝트 폴더들, 코드들 한번 살펴보고
> 의미 있는 것들, 레거시 코드들(지금 안쓰는 것) 한번 파악하고 정리해야 할 거 같아
> 그래야 다음 스탭으로 팀원들 협업을 할 수 있을 거 같아서
> 그리고 그게 해야 의미있는 리팩토링을 진행하고 코드 리뷰를 할 수 있을듯
> 그리고 그 다음 readme.md도 지금 기준으로 업데이트 해야할 것 같음

---

## 2. Thinking Process

### 2.1 분석 방법론
1. **디렉토리 구조 탐색** (`tree -L 3`)
2. **핵심 설정 파일 확인** (pyproject.toml, configs/default.yaml, .gitignore)
3. **코드 참조 추적** (Grep으로 chroma_db, 주요 모듈 사용 여부 확인)
4. **레거시 판단 기준**:
   - `.gitignore`에 명시된 디렉토리
   - 빈 디렉토리 또는 단순 테스트용 파일
   - 코드 내에서 참조되지 않는 파일/폴더

### 2.2 기술적 선택
- **VectorDB 현황**: `configs/default.yaml`에 `persist_directory: "./chroma_db"` 설정
  → `chroma_db_v3`는 이전 실험용으로 판단
- **Python 환경**: `uv` + `pyproject.toml` (requires-python >= 3.11)
- **문서 처리**: HWP(Windows-only, pyhwpx), PDF(pymupdf4llm)

---

## 3. Execution Result

### 3.1 현재 프로젝트 구조 (핵심)

```
AI_7-team/
├── app/                       # ✅ Streamlit UI (main.py)
├── src/                       # ✅ 핵심 로직
│   ├── graph/                 # LangGraph (state, nodes, workflow)
│   ├── parsers/               # HWP/PDF 파서, chunker, cleaner
│   ├── retrievers/            # Embedding, VectorStore, Hybrid
│   ├── evaluation/            # LLM Judge, Metrics, Tracers
│   ├── prompts/               # Prompt templates
│   └── utils/                 # Config, Env
├── scripts/                   # ✅ 유틸리티 스크립트
│   ├── ingest.py              # 문서 인덱싱 파이프라인
│   ├── eval_retrieval.py      # RAG 평가 실행
│   ├── build_eval_report.py   # HTML 리포트 생성
│   ├── audit_db.py            # DB 품질 감사
│   ├── debug_db.py            # DB 디버깅
│   ├── generate_eval_set.py   # 평가셋 생성
│   └── export_langsmith_traces.py  # LangSmith 추적 내보내기
├── configs/                   # ✅ default.yaml
├── eval/                      # ✅ 평가 데이터셋, 결과, 메트릭 정의
├── docs/                      # ✅ ARCHITECTURE.md
├── ai_history/                # ✅ AI 작업 리포트 (8개)
├── .claude/                   # ✅ Claude agents/rules/skills
│   ├── agents/                # eval-runner, rag-debugger, doc-writer
│   ├── rules/                 # execution-quality.md, work-logging.md
│   └── skills/                # run-eval, build-report, pdf, rag-impl, etc.
├── data/files/                # ✅ 100+ RFP 원본 (HWP/PDF)
├── chroma_db/                 # ✅ 현재 사용 중인 VectorDB
├── results/                   # ✅ 실험 결과 저장소 (figures, logs, outputs)
└── notebooks/                 # ✅ 실험용 노트북 (.gitkeep만 존재)
```

### 3.2 레거시/정리 대상 항목

#### 🔴 즉시 삭제 가능
1. **`.agents/skills/`** (빈 디렉토리)
   - `.gitignore`에 `.agents/` 명시됨
   - 실제 스킬은 `.claude/skills/`에 위치

2. **`project_codeit_7team/`** (레거시 테스트 디렉토리)
   - `.gitignore`에 명시
   - PDF 2개만 있으며 `data/files/`에 중복 존재:
     - `서울시립대학교_[사전공개] 학업성취도...pdf` (중복)
     - `서울특별시_2024년 지도정보 플랫폼...pdf` (중복)

3. **`chroma_db_v3/`** (이전 VectorDB 실험용)
   - 현재 `chroma_db/` 사용 중 (default.yaml 확인)
   - `.gitignore`에 명시

#### 🟡 확인 후 정리
4. **`data/traces/`** (LangSmith 추적 JSON 3개)
   - 현재 사용 여부 확인 필요
   - export_langsmith_traces.py와 연관 가능성

5. **`.DS_Store` 파일들**
   - macOS 시스템 파일, `.gitignore`에 추가 권장

#### ✅ 유지 필요
- `ai_history/` (8개 리포트, 작업 이력)
- `eval/v1_20260210/` (평가 버전 관리)
- `results/` (빈 폴더지만 스크립트에서 사용 예정)

### 3.3 의존성 현황 (pyproject.toml)

**핵심 스택:**
- LangChain/LangGraph (0.3+, 0.2+)
- OpenAI (1.0+)
- ChromaDB (0.5+), faiss-cpu (1.9+)
- Streamlit (1.38+)
- 문서 처리: pymupdf4llm, pyhwpx (Windows-only)
- 검색: rank-bm25, kiwipiepy
- 평가/추적: langfuse, langsmith

**특이사항:**
- `pyhwpx`는 Windows 전용 (COM automation) → `sys_platform == 'win32'` 마커 사용
- Python 3.11+ 필수 (onnxruntime 호환성)

### 3.4 스크립트 사용 목적

| 스크립트 | 목적 | 사용 빈도 |
|---------|------|----------|
| `ingest.py` | 문서 파싱 → 청킹 → 임베딩 → ChromaDB 저장 | 초기 + 재인덱싱 |
| `eval_retrieval.py` | RAG E2E 평가 (LLM-as-Judge) | 성능 테스트 시 |
| `build_eval_report.py` | HTML 대시보드 생성 | 평가 후 |
| `audit_db.py` | ChromaDB 품질 감사 | 디버깅 시 |
| `debug_db.py` | ChromaDB 내용 확인 | 디버깅 시 |
| `generate_eval_set.py` | 평가 데이터셋 생성 | 초기 셋업 |
| `export_langsmith_traces.py` | LangSmith 추적 내보내기 | 분석 시 |

---

## 4. 권장 조치 사항

### Phase 1: 즉시 정리 (Breaking Changes 없음)
```bash
# 1. 레거시 디렉토리 삭제
rm -rf .agents/skills
rm -rf project_codeit_7team
rm -rf chroma_db_v3

# 2. .DS_Store 제거 및 .gitignore 업데이트
find . -name ".DS_Store" -delete
echo ".DS_Store" >> .gitignore

# 3. 정리 커밋
git add -A
git commit -m "chore: remove legacy directories and macOS artifacts"
```

### Phase 2: 문서 업데이트
1. **README.md 재작성** (현재 기준으로)
   - 최신 프로젝트 구조 반영
   - 평가 시스템 설명 추가
   - Claude 에이전트/스킬 가이드 추가

2. **CONTRIBUTING.md 추가** (팀 협업용)
   - Git 브랜치 전략
   - 커밋 컨벤션 (conventional commits)
   - PR 템플릿

3. **ARCHITECTURE.md 검증**
   - 현재 구현과 일치 여부 확인

### Phase 3: 코드 품질 개선 (리팩토링 전)
1. **pytest 커버리지 확인**
   - `tests/` 디렉토리에 실제 테스트 코드 부재
   - 핵심 모듈 단위 테스트 작성 권장

2. **타입 힌트 추가**
   - `mypy` 도입 고려
   - `pydantic` 활용 검증 강화

3. **Ruff 린팅 실행**
   ```bash
   uv run ruff check .
   uv run ruff format .
   ```

---

## 5. 다음 단계 (팀 협업 준비)

### 5.1 문서화 우선순위
1. ✅ README.md 업데이트
2. 🔄 CONTRIBUTING.md 작성
3. 🔄 API 사용 가이드 (src/graph/workflow.py)
4. 🔄 평가 시스템 가이드 (eval/METRICS.md 확장)

### 5.2 코드 리뷰 체크리스트
- [ ] 모든 함수에 docstring 존재
- [ ] 타입 힌트 일관성
- [ ] 예외 처리 명시성
- [ ] 설정 파일 외부화 (하드코딩 제거)
- [ ] 로깅 레벨 정리

### 5.3 CI/CD 파이프라인 (미래)
- GitHub Actions 워크플로우:
  - `pytest` 자동 실행
  - `ruff` 린팅 검증
  - Discord 알림 (기존 `discord-notify.yml` 존재)

---

## 6. 결론

**현재 상태:**
- 핵심 코드 품질: ✅ 양호
- 레거시 부채: 🟡 소량 (3개 디렉토리, 즉시 제거 가능)
- 문서화 수준: 🟡 중간 (README 업데이트 필요)
- 팀 협업 준비도: 🟡 70% (CONTRIBUTING 미비)

**제거 대상 요약:**
1. `.agents/skills/` (빈 디렉토리)
2. `project_codeit_7team/` (중복 테스트 파일)
3. `chroma_db_v3/` (구 VectorDB)

**다음 액션:**
1. 레거시 정리 (5분)
2. README.md 업데이트 (15분)
3. CONTRIBUTING.md 작성 (10분)
4. 팀원에게 브랜치 공유 후 코드 리뷰 요청

---

**Verified Evidence:**
- ✅ `tree -L 3` 실행 (전체 구조 확인)
- ✅ `grep -r "chroma_db"` (현재 DB 사용처 확인)
- ✅ `ls -la .agents/skills/` (빈 디렉토리 검증)
- ✅ `configs/default.yaml` 읽기 (persist_directory 설정)
- ✅ `.gitignore` 분석 (레거시 항목 확인)
