# DOCUMENTATION

- App entrypoint: `app/main.py`
- Runtime config template: `configs/default.yaml`
- Parsing pipeline: `src/parsers/*`
- Retrieval pipeline: `src/retrievers/*`
- Evaluation pipeline: `src/evaluation/*`, `src/evaluate_answer.py`
- Evaluation resources: `eval_resources/*`
- Scenario B default: OpenAI LLM/Embedding + Dense/Chroma 비교
- Hybrid note: `hybrid_alpha=1.0`은 lexical-only baseline
