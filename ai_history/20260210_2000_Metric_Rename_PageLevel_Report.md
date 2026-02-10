# 지표명 리네이밍 + Page-Level Recall 활성화 + 평가 실행

## User Prompt
1. Answer Recall → Answer Coverage (Retrieval Recall@K와 혼동 방지)
2. Relevance → Context Relevance (검색된 context의 관련성 정의에 부합)
3. Hit Rate@K → Recall@K (표준 RAG 평가 용어로 통일)
4. Page-Level Recall 활성화 (이전 작업에서 코드 수정 완료)
5. 평가 실행 + HTML 리포트 생성

## Thinking Process
- `answer_recall` → `answer_coverage`: JSON 키, 변수명, 프롬프트, 표시명 전체 변경
- `relevance` → `context_relevance`: 동일하게 전체 변경
- `hit_rate_at_k` → `recall_at_k_source`: summary 키 변경, 함수명 `calculate_hit_rate_at_k` → `calculate_recall_at_k_summary`
- LLM Judge 프롬프트의 채점 기준 섹션명과 JSON 출력 형식도 동시 변경

## Execution Result

### 수정 파일 (10개)

| 파일 | 변경 내용 |
|------|----------|
| `src/evaluation/llm_judge.py` | 프롬프트(Answer Coverage, Context Relevance), JSON 키, fallback |
| `src/evaluation/metrics.py` | `calculate_hit_rate_at_k` → `calculate_recall_at_k_summary`, `calculate_hit_position`에 page 파라미터 |
| `scripts/eval_retrieval.py` | 변수/키 전체 리네이밍, page-level 병렬 계산, 콘솔 출력 |
| `scripts/build_eval_report.py` | HTML 카드/차트/query card 전체 리네이밍 + page-level 추가 |
| `eval/METRICS.md` | 지표 정의서 전면 개편 (4대 지표 + Retrieval 보조지표) |
| `CLAUDE.md` | 평가 체계 지표명 업데이트 |
| `KPI.md` | KPI 테이블 지표명 + 약점 유형 업데이트 |
| `.claude/skills/run-eval/SKILL.md` | 출력 지표명 업데이트 |
| `.claude/agents/eval-runner.md` | 분석 관점 지표명 업데이트 |
| `docs/ARCHITECTURE.md` | 평가 체계 + 약점 지표명 업데이트 |

### 평가 결과 (label=current, top_k=5)

**LLM Judge (0~5)**
| 지표 | 점수 |
|------|:---:|
| Correctness | 3.85 |
| Answer Coverage | 3.55 |
| Faithfulness | 4.95 |
| Context Relevance | 4.70 |

**Retrieval 보조**
| 지표 | Source | Page |
|------|:---:|:---:|
| Recall@5 | 0.90 | 0.30 |
| MRR | 0.90 | 0.15 |

### 핵심 인사이트
- **Source vs Page 격차 확인**: Recall@5가 0.90 → 0.30으로 급락. 같은 PDF의 엉뚱한 페이지가 검색되는 비율이 60%
- **Faithfulness 최고 (4.95)**: 환각 거의 없음
- **Context Relevance 높음 (4.70)**: 검색 품질 양호하나 page 정밀도 개선 필요
- HTML 리포트: `eval/eval_report.html` (64KB)
