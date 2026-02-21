# USAGE

## App

```bash
streamlit run /Users/apple/AI_7-team/app/main.py
```

## Main eval

```bash
python -m src.run_eval_b
```

## RAG answer

```bash
python -m src.rag_answer --query "고려대학교 사업 개요" --retriever hybrid --rerank none --generate --output-csv results/node_report_rag_single.csv
```

## Chroma 인덱싱

```bash
# OpenAI 임베딩
python -m src.retrievers.build_chroma_index --input-dir notebooks/data_chunks_rich --persist-dir data_index/chroma_B --collection rfp_b --model-provider openai --model text-embedding-3-small

# KoSimCSE 임베딩(sentence-transformers)
python -m src.retrievers.build_chroma_index --input-dir notebooks/data_chunks_rich --persist-dir data_index/chroma_B --collection rfp_b --model-provider kosimcse

# AUTO (OPENAI_API_KEY 있으면 OpenAI, 없으면 KoSimCSE)
python -m src.retrievers.build_chroma_index --input-dir notebooks/data_chunks_rich --persist-dir data_index/chroma_B --collection rfp_b_auto --model-provider auto
```

## Chroma 검색

```bash
# 기본 의미 검색
python -m src.retrievers.search_chroma --query "한국농어촌공사 입찰 보증금 비율은 얼마인가?" --persist-dir data_index/chroma_B --collection rfp_b_auto --model auto --topk 5

# 메타데이터 필터(org/type/source)
python -m src.retrievers.search_chroma --query "제안서 제출 마감일은 언제인가?" --persist-dir data_index/chroma_B --collection rfp_b_auto --model auto --org 한국농어촌공사 --topk 5
```

## Gold refresh

```bash
python -m src.evaluation.build_eval_gold_rich --input configs/eval_queries_v2_rich.jsonl --output configs/eval_queries_v2_rich.jsonl --top-k 3
```
