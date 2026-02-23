# src/utils — 설정 + 환경변수 관리

## 파일 구성

| 파일 | 역할 | 핵심 함수 |
|------|------|----------|
| `config.py` | YAML 설정 로드 | `load_config()` |
| `env.py` | 환경변수 로딩 | `load_env()`, `get_openai_api_key()`, `get_langfuse_keys()` |

## config.py

- `load_config(config_path)`: `configs/default.yaml` 로드
- 경로 미지정 시 프로젝트 루트 자동 탐지 (`Path(__file__).parents[2]`)
- 반환: 순수 `dict[str, Any]` (캐싱 없음, 호출마다 파일 읽기)

### YAML 구조 (configs/default.yaml)

```yaml
llm:
  model: "gpt-5-mini"
  temperature: 0.0
  max_tokens: 4096

embedding:
  model: "text-embedding-3-small"

vectorstore:
  collection_name: "rfp_docs"
  persist_directory: "./chroma_db_eval_yc"

retriever:
  search_type: "mmr"
  top_k: 8
  fetch_k: 50
  lambda_mult: 0.7
  score_threshold: 0.3

chunking:
  chunk_size: 1000
  chunk_overlap: 200
```

## env.py

- `load_env()`: `.env` 파일 로드 (1회만, `_loaded` 플래그로 중복 방지)
- `override=False` → 기존 환경변수 우선
- 키 접근 함수:
  - `get_openai_api_key()` → 없으면 `EnvironmentError` raise
  - `get_langsmith_api_key()` → 없으면 `None`
  - `get_langfuse_keys()` → `{public_key, secret_key, host}` dict

## 사용 패턴

```python
# 설정값 접근
from src.utils.config import load_config
config = load_config()
top_k = config["retriever"]["top_k"]

# API 키 접근
from src.utils.env import get_openai_api_key, load_env
load_env()  # .env 로드 (최초 1회)
key = get_openai_api_key()
```

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| config.py | YAML 전용 로더 | YAML + 하드코딩 상수 (`OPENAI_API_KEY` 등) 혼재 |
| env.py | `load_env()` + getter 함수 | 동일 (integration-eval-yc에서 복사) |
| API 키 관리 | `env.py`로 통일 | `config.py` 모듈 레벨 변수 + `env.py` 이중 관리 |
| helpers.py | 없음 | `remove_josa()`, `format_amount()` 등 UI 헬퍼 |
