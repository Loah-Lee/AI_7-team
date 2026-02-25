# DOCUMENTATION

이 문서는 `workspace_collab`의 현재 실행 기준 기술 문서입니다.

## 1. 진입점

- UI: `app/main.py`
- 메인 워크플로우: `src/graph/workflow.py`
- 노드/파서: `src/graph/nodes.py`

## 2. 설정

- 설정 파일: `src/utils/config.py`
- 기본 DB 경로: `data_index/chroma_B`
- 기본 데이터 경로: `data_index/files` (없으면 `data/` 우선)

## 3. 워크플로우 요약

1. 질문 의도 파싱 (`QueryIntentParser`)
2. 후속질문 문맥 반영 (`ConversationContext`)
3. 단축 경로 확인

- CSV short-circuit
- 기관 overview short-circuit
- chunk budget short-circuit

4. 검색/재랭킹 (`VectorStore`)
5. 추출형 응답 또는 LLM 생성 응답

## 4. 검색 계층

- 벡터 저장소: `src/retrievers/vectorstore.py`
- 하이브리드/필터링 호출 어댑터: `workflow.py::_run_retrieval_call`
- org 필터 실패 시 재검색 fallback 지원

## 5. 문서 파싱

- CSV: `src/parsers/csv_loader.py`
- PDF: `src/parsers/pdf_loader.py` (PyMuPDF + pymupdf4llm)
- HWP/HWPX 변환: `src/parsers/hwp_converter.py` (LibreOffice 필요)

## 6. 평가

- LLM Judge: `src/evaluation/llm_judge.py`
- 스크립트:

```bash
python scripts/generate_eval_set.py --num_pairs 20
python scripts/eval_retrieval.py --label collab --top_k 5
```

## 7. 의존성

의존성은 `requirements.txt`를 단일 소스로 사용합니다.

```bash
pip install -r requirements.txt
```

## 8. 운영 체크리스트

- `.env`에 `OPENAI_API_KEY` 설정
- `streamlit run app/main.py` 기동 확인
- 사이드바 기본 질문 11개 스모크 테스트
- 후속질문(`마감일은?`) 문맥 유지 확인

