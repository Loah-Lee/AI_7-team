from __future__ import annotations

# 자체 생성 코드(프로젝트 기존 라이선스에 종속)

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
        return
    except Exception:
        pass

    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_client():
    _load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("openai SDK가 설치되지 않았습니다. pip install openai 로 설치하세요.") from exc
    return OpenAI(api_key=api_key)


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def _chunk_id(text: str) -> str:
    import hashlib

    normalized = _normalize_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _l2_normalize(vecs: np.ndarray) -> np.ndarray:
    if vecs.ndim == 1:
        denom = np.linalg.norm(vecs)
        return vecs if denom == 0 else vecs / denom
    denom = np.linalg.norm(vecs, axis=1, keepdims=True)
    denom[denom == 0] = 1.0
    return vecs / denom


def _has_table_schema(text: str) -> bool:
    # 자체 생성 코드: 표 JSON 스키마 존재 여부를 간단히 감지
    return bool(re.search(r"\"type\"\\s*:\\s*\"table\"", text))


@dataclass(frozen=True)
class DenseMeta:
    chunk_id: str
    source_path: str
    chunk_index: int
    text: str
    is_table: bool = False


@dataclass(frozen=True)
class DenseIndex:
    vectors: np.ndarray
    meta: List[DenseMeta]
    model: str

    def search(self, query_vec: np.ndarray, k: int) -> List[Tuple[DenseMeta, float]]:
        if self.vectors.size == 0:
            return []
        q = _l2_normalize(query_vec.astype(np.float32))
        scores = self.vectors @ q
        k = min(int(k), len(self.meta))
        if k <= 0:
            return []
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self.meta[i], float(scores[i])) for i in idx]

    def score_all(self, query_vec: np.ndarray) -> np.ndarray:
        if self.vectors.size == 0:
            return np.zeros((0,), dtype=np.float32)
        q = _l2_normalize(query_vec.astype(np.float32))
        return (self.vectors @ q).astype(np.float32)

    @classmethod
    def load(cls, index_path: Path, meta_path: Path) -> "DenseIndex":
        data = np.load(index_path)
        vectors = data["vectors"].astype(np.float32)
        vectors = _l2_normalize(vectors)
        meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
        meta = [
            DenseMeta(
                chunk_id=str(item.get("chunk_id", "")),
                source_path=str(item.get("source_path", "")),
                chunk_index=int(item.get("chunk_index", -1)),
                text=str(item.get("text", "")),
                is_table=bool(item.get("is_table", False)),
            )
            for item in meta_raw.get("items", [])
        ]
        model = str(meta_raw.get("model", "text-embedding-3-small"))
        return cls(vectors=vectors, meta=meta, model=model)

    def save(self, index_path: Path, meta_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(index_path, vectors=self.vectors.astype(np.float32))
        meta = {
            "model": self.model,
            "items": [
                {
                    "chunk_id": item.chunk_id,
                    "source_path": item.source_path,
                    "chunk_index": item.chunk_index,
                    "text": item.text,
                    "is_table": item.is_table,
                }
                for item in self.meta
            ],
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _embed_texts(
    client,
    texts: Sequence[str],
    *,
    model: str,
    batch_size: int,
    sleep_s: float,
) -> List[List[float]]:
    embeddings: List[List[float]] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        data = getattr(response, "data", []) or []
        # OpenAI SDK는 입력 순서와 동일하게 반환
        embeddings.extend([item.embedding for item in data])
        if sleep_s > 0 and start + batch_size < total:
            time.sleep(sleep_s)
    return embeddings


def build_dense_index(
    input_dir: Path,
    *,
    output_dir: Path,
    model: str = "text-embedding-3-small",
    batch_size: int = 64,
    sleep_s: float = 0.0,
) -> DenseIndex:
    client = _get_client()

    items: List[DenseMeta] = []
    texts: List[str] = []

    for path in sorted(input_dir.rglob("*.jsonl")):
        for row in _iter_jsonl(path):
            source_path = str(row.get("source_path", ""))
            try:
                chunk_index = int(row.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            text = str(row.get("text", ""))
            chunk_id = str(row.get("chunk_id", "")).strip() or _chunk_id(text)
            is_table = _has_table_schema(text)
            if source_path and chunk_index >= 0 and text:
                items.append(
                    DenseMeta(
                        chunk_id=chunk_id,
                        source_path=source_path,
                        chunk_index=chunk_index,
                        text=text,
                        is_table=is_table,
                    )
                )
                texts.append(text)

    if not items:
        raise RuntimeError(f"인덱스 생성 실패: 입력 청크가 없습니다. ({input_dir})")

    vectors = _embed_texts(
        client,
        texts,
        model=model,
        batch_size=batch_size,
        sleep_s=sleep_s,
    )
    vec_array = np.array(vectors, dtype=np.float32)
    vec_array = _l2_normalize(vec_array)

    index = DenseIndex(vectors=vec_array, meta=items, model=model)
    index_path = output_dir / "index.npz"
    meta_path = output_dir / "meta.json"
    index.save(index_path, meta_path)
    return index


@dataclass
class DenseEmbedder:
    model: str = "text-embedding-3-small"

    def __post_init__(self) -> None:
        self._client = _get_client()

    def embed_query(self, text: str) -> np.ndarray:
        response = self._client.embeddings.create(model=self.model, input=[text])
        data = getattr(response, "data", []) or []
        if not data:
            return np.zeros((0,), dtype=np.float32)
        vec = np.array(data[0].embedding, dtype=np.float32)
        return _l2_normalize(vec)
