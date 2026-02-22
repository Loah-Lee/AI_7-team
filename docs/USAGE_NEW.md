# USAGE NEW

## App

```bash
streamlit run /Users/apple/AI_7-team/app/main.py
streamlit run /Users/apple/AI_7-team/app/streamlit_app.py
streamlit run /Users/apple/AI_7-team/app/gold_app.py
```

## Chroma 기반 RAG 질의

```bash
python -m src.rag_answer --query "한국농어촌공사 입찰 보증금 비율은 얼마인가?" --retriever chroma --chroma-persist-dir data_index/chroma_B --chroma-collection rfp_b_oai --chroma-model text-embedding-3-small --rerank none --topk 50 --context-k 20 --generate --output-csv results/node_report_chroma_oai.csv
```

## Chroma 메타 랭킹(조직별 hit 집계)

`src/retrievers/vectorstore.py`의 `VectorStore.get_ranking()`을 사용해 `org` 단위 랭킹을 계산할 수 있습니다.

## 참고

- `hybrid_alpha=1.0`은 lexical-only baseline입니다.
- 시나리오 B 가이드 충족 보고에는 `alpha<1` 또는 `retriever=chroma` 비교 결과를 함께 포함하세요.
