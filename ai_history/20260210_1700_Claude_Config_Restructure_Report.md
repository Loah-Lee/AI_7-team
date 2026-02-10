# .claude 디렉토리 구조화 및 CLAUDE.md 슬림화

**일시:** 2026-02-10 15:00 ~ 17:00
**작업자:** Claude Opus 4.6

---

## 1. User Prompt

> CLAUDE.md에 있는 규칙, 에이전트, 스킬 정의를 `.claude/` 하위 디렉토리로 분리 정리하고, CLAUDE.md는 25줄 이내 핵심 규칙만 남기기. 프로젝트 아키텍처 문서도 별도 생성.

---

## 2. Thinking Process

### 2.1 문제 인식

기존 `CLAUDE.md`에 모든 규칙이 단일 파일로 집중:
- 실행 품질 규칙, 작업 로깅 프로토콜, 에이전트 정의, 스킬 정의가 혼재
- 파일이 길어질수록 컨텍스트 효율 저하
- 역할별 분리가 안 되어 유지보수 어려움

### 2.2 설계 방향

Claude Code의 `.claude/` 디렉토리 구조를 활용하여 관심사 분리:

```
.claude/
├── rules/          ← 항상 시스템 프롬프트에 로드되는 규칙
│   ├── execution-quality.md   (Deep Verification, No Hard-coding 등)
│   └── work-logging.md        (ai_history 보고서 프로토콜)
├── agents/         ← Task 도구로 호출되는 서브에이전트 정의
│   ├── eval-runner.md         (평가 실행/분석)
│   ├── rag-debugger.md        (검색/생성 디버깅)
│   └── doc-writer.md          (보고서/문서 작성)
├── skills/         ← /slash-command로 호출되는 스킬
│   ├── run-eval/SKILL.md      (RAG E2E 평가 실행)
│   └── build-report/SKILL.md  (HTML 대시보드 생성)
└── settings.local.json
```

### 2.3 핵심 원칙

- **CLAUDE.md** = 25줄 이내, 프로젝트 컨텍스트 + 기본 명령어 + 핵심 규칙만
- **rules/** = 시스템 프롬프트에 자동 주입 → 모든 대화에서 적용
- **agents/** = 특화 에이전트 (sonnet/haiku 모델 지정으로 비용 최적화)
- **skills/** = 사용자가 `/run-eval`, `/build-report`로 직접 호출

---

## 3. Execution Result

### 3.1 생성/수정 파일 목록

| 파일 | 상태 | 설명 |
|---|---|---|
| `CLAUDE.md` | **수정** | 25줄로 슬림화 (컨텍스트+명령어+규칙 요약) |
| `.claude/rules/execution-quality.md` | **신규** | Deep Verification, No Hard-coding, Self-Critique, Mandatory Evidence |
| `.claude/rules/work-logging.md` | **신규** | ai_history 보고서 규격 (파일명, 구조, 저장 위치) |
| `.claude/agents/eval-runner.md` | **신규** | RAG 평가 실행/분석 에이전트 (model: sonnet) |
| `.claude/agents/rag-debugger.md` | **신규** | 파이프라인 단계별 디버깅 에이전트 (model: sonnet) |
| `.claude/agents/doc-writer.md` | **신규** | 보고서/문서 작성 에이전트 (model: haiku) |
| `.claude/skills/run-eval/SKILL.md` | **신규** | /run-eval 슬래시 커맨드 정의 |
| `.claude/skills/build-report/SKILL.md` | **신규** | /build-report 슬래시 커맨드 정의 |
| `docs/ARCHITECTURE.md` | **신규** | 파이프라인/모듈/검색전략/평가체계 전체 아키텍처 |

### 3.2 CLAUDE.md 변경 전후

**Before**: 규칙/에이전트/스킬 정의까지 포함한 장문 (80줄+)
**After**: 25줄, 4개 섹션 (Context, Tech Stack, Commands, Rules)

### 3.3 에이전트 설계

| 에이전트 | 모델 | 용도 | 도구 |
|---|---|---|---|
| eval-runner | sonnet | 평가 실행 + 결과 분석 + 개선점 도출 | Bash, Read, Grep, Glob |
| rag-debugger | sonnet | 특정 질문의 검색/생성 품질 디버깅 | Bash, Read, Grep, Glob |
| doc-writer | haiku | ai_history 보고서 + 프로젝트 문서 | Read, Glob, Grep, Write |

### 3.4 스킬 정의

| 스킬 | 트리거 | 기능 |
|---|---|---|
| `/run-eval` | `/run-eval [label]` | 평가 실행 → 결과 JSON 읽기 → 요약 출력 → HTML 리포트 |
| `/build-report` | `/build-report` | JSON → Chart.js HTML 대시보드 생성 |

### 3.5 memory 업데이트

`~/.claude/projects/.../memory/MEMORY.md`에 Documentation Structure 섹션 추가:
- `.claude/rules/`, `.claude/agents/`, `.claude/skills/` 구조 기록
- `docs/ARCHITECTURE.md`, `KPI.md`, `eval/METRICS.md` 경로 기록
