# src/prompts — 프롬프트 템플릿

## 파일 구성

| 파일 | 역할 |
|------|------|
| `templates.py` | 모든 `ChatPromptTemplate` 정의 (4개) |

## 프롬프트 목록

| 프롬프트 | 호출 위치 | 입력 변수 | 용도 |
|---------|----------|----------|------|
| `QUERY_ANALYSIS_PROMPT` | `nodes.py:analyze_query()` | `{query}` | 질의 유형/메타데이터 JSON 추출 |
| `RAG_GENERATION_PROMPT` | `nodes.py:generate()` | `{query}`, `{context}`, `{chat_history}` | 최종 답변 생성 |
| `EVIDENCE_EXTRACTION_PROMPT` | `nodes.py:extract_evidence()` | `{query}`, `{retrieved_docs}` | 검색 결과에서 핵심 근거 추출 |
| `OUT_OF_SCOPE_PROMPT` | `nodes.py:generate()` | `{query}` | 범위 밖 질문 안내 |

## 프롬프트 설계 특징

### QUERY_ANALYSIS_PROMPT
- B2G 입찰 RFP 도메인 전문가 역할
- 추출 대상: `query_type`, `keywords`(최대 3개), `institution`, `project_name`, `year`
- 키워드 규칙: 쿼리 원문에 이미 포함된 단어는 제외
- JSON only 출력 지시 (마크다운 코드블록 금지)

### RAG_GENERATION_PROMPT
- B2G 입찰 컨설턴트 역할
- 핵심 규칙: context에 있는 정보만 사용, 부분 정보라도 최대 활용
- 출처(문서명, 페이지) 명시 필수
- 답변 형식: 소제목(###) 구분, 수치 필수 포함, 불릿(-) 정리
- `{chat_history}`는 `placeholder`로 대화 히스토리 자동 삽입

### EVIDENCE_EXTRACTION_PROMPT
- 최대 7개 근거까지 추출
- 수치(예산/금액/기간) 원문 그대로 인용 (요약/반올림 금지)
- 표 데이터는 행/열 구조 유지
- 상충 정보는 각각 별도 표기
- 관련 근거 없으면 명시

### OUT_OF_SCOPE_PROMPT
- RFP 범위 밖 질문에 대한 정중한 안내
- 시스템 역할 설명 + RFP 관련 질문 유도

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| 형식 | `ChatPromptTemplate` (LangChain) | f-string 직접 구성 |
| 프롬프트 수 | 4개 | 5개 (SYSTEM_PROMPT 추가) |
| 근거 추출 | 별도 프롬프트 | RAG 프롬프트 내 통합 |
| 대화 히스토리 | placeholder 자동 삽입 | 수동 메시지 구성 |
