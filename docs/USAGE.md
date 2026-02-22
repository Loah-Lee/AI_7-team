# USAGE

## App

```bash
streamlit run /Users/apple/AI_7-team/app/main.py
```

## Main eval

```bash
python -m src.run_eval_b
```

## Hybrid 최종 기준 실행

```bash
python -m src.rag_answer --query-file configs/eval_queries_v2_rich.jsonl --retriever hybrid --rerank none --topk 50 --context-k 20 --hybrid-alpha 1.0 --generate --output-csv results/node_report_hybrid_final_locked_meta_tuned.csv
python -m src.evaluate_answer --eval-set configs/answer_eval_v1.jsonl --pred results/node_report_hybrid_final_locked_meta_tuned.csv --out results/answer_eval_report_hybrid_final_locked_meta_tuned.csv --fail-out results/fail_answers_hybrid_final_locked_meta_tuned.csv
```

## True Hybrid 비교(alpha<1)

```bash
python -m src.rag_answer --query-file configs/eval_queries_qmix_q20.jsonl --retriever hybrid --rerank none --topk 50 --context-k 20 --hybrid-alpha 0.9 --output-csv results/node_report_hybrid_a09.csv
```

## RAG answer

```bash
python -m src.rag_answer --query "고려대학교 사업 개요" --retriever hybrid --rerank none --hybrid-alpha 1.0 --generate --output-csv results/node_report_rag_single.csv
```

## Chroma 인덱싱

```bash
# 시나리오 B 고정(OpenAI 임베딩)
python -m src.retrievers.build_chroma_index --input-dir notebooks/data_chunks_rich --persist-dir data_index/chroma_B --collection rfp_b_oai --model-provider openai --model text-embedding-3-small
```

## Chroma 실험 (청킹 500/60)

```bash
# rich 청킹 + Chroma 인덱스를 한 번에 재구축
python /Users/apple/AI_7-team/scripts/rebuild_db.py --chunk-rich --chroma --chunk-size 500 --overlap 60 --chunk-output-dir notebooks/data_chunks_rich_500_60 --chroma-dir data_index/chroma_B_500_60 --collection rfp_b_500_60_oai --model text-embedding-3-small
```

## Chroma 검색

```bash
# 기본 의미 검색
python -m src.retrievers.search_chroma --query "한국농어촌공사 입찰 보증금 비율은 얼마인가?" --persist-dir data_index/chroma_B --collection rfp_b_oai --model text-embedding-3-small --topk 5

# 메타데이터 필터(org/type/source)
python -m src.retrievers.search_chroma --query "제안서 제출 마감일은 언제인가?" --persist-dir data_index/chroma_B --collection rfp_b_oai --model text-embedding-3-small --org 한국농어촌공사 --topk 5
```

## 해석 기준

- `hybrid_alpha=1.0` 결과는 lexical baseline으로 분류한다.
- 벡터 기반 성능 확인은 `hybrid_alpha<1` 또는 `retriever=chroma`로 별도 비교한다.

## Gold refresh

```bash
python -m src.evaluation.build_eval_gold_rich --input configs/eval_queries_v2_rich.jsonl --output configs/eval_queries_v2_rich.jsonl --top-k 3
```
