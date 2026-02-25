#!/usr/bin/env python3
"""입찰메이트 v17 - 메인 워크플로우."""

from __future__ import annotations

import sys
import os
import re
import json
import time
import inspect
import unicodedata
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# LangChain (LangSmith 트레이싱)
from langchain_openai import ChatOpenAI

# 환경 변수는 config import 전에 로드해야 OPENAI_API_KEY 상수가 올바르게 채워진다.
def _load_runtime_env() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parent_root = project_root.parent
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(parent_root / ".env", override=False)
    load_dotenv(override=False)


_load_runtime_env()

# 설정
sys.path.insert(0, 'src')
from src.utils.config import *
from src.utils.helpers import *
from src.graph.state import QueryIntent, QuestionPlan, EvidenceSpan, AnswerDraft

# ============================================================================
# LangSmith 트레이싱 활성화
# ============================================================================
from src.utils.config import (
    LANGSMITH_API_KEY,
    LANGSMITH_TRACING,
    LANGSMITH_ENDPOINT,
    LANGSMITH_PROJECT
)

if LANGSMITH_TRACING and LANGSMITH_API_KEY:
    # LangChain 트레이싱을 위한 환경 변수 설정
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_ENDPOINT"] = LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
    print(f"🔍 LangSmith 트레이싱 활성화: {LANGSMITH_PROJECT}")
else:
    print("ℹ️ LangSmith 트레이싱 비활성화")

# ============================================================================
# RAG 챗봇 (RAG Chatbot)
# ============================================================================


def _ensure_parsers_package_compat() -> None:
    """파서 패키지 __init__ 불일치 시 서브모듈 import를 허용하도록 보정."""
    if "src.parsers" in sys.modules:
        return

    parsers_dir = Path(__file__).resolve().parents[1] / "parsers"
    compat_module = types.ModuleType("src.parsers")
    compat_module.__path__ = [str(parsers_dir)]
    compat_module.__package__ = "src.parsers"
    sys.modules["src.parsers"] = compat_module

class RAGChatbotV17:
    """입찰메이트 RFP 챗봇 v17 메인 클래스."""

    def __init__(self, data_dir: str = None, db_path: str | None = None) -> None:
        # data_dir이 None이면 설정 기본값을 사용
        if data_dir is None:
            data_dir = str(get_data_dir())

        script_dir = Path(__file__).parent.parent.parent.resolve()
        if Path(data_dir).is_absolute():
            self.data_dir = Path(data_dir).resolve()
        else:
            self.data_dir = (script_dir / data_dir).resolve()

        # data_dir이 디렉토리면 files 하위를 검색
        if self.data_dir.is_dir() and (self.data_dir / "files").is_dir():
            self.data_dir = (self.data_dir / "files").resolve()

        # 기본 data 경로가 비어있는 경우 data_index/files를 우선 사용한다.
        if not self._has_csv_seed_files(self.data_dir):
            fallback_candidates = [
                (script_dir / "data_index" / "files").resolve(),
                (script_dir / "data_index").resolve(),
                get_data_dir().resolve(),
            ]
            for candidate in fallback_candidates:
                probe = candidate
                if probe.is_dir() and (probe / "files").is_dir():
                    probe = (probe / "files").resolve()
                if probe == self.data_dir:
                    continue
                if self._has_csv_seed_files(probe):
                    self.data_dir = probe
                    break

        # LangChain ChatOpenAI 초기화 (LangSmith 트레이싱 자동)
        self.llm = None
        if OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=REASONING_MODEL,
                temperature=0.0,
                timeout=OPENAI_TIMEOUT_SEC,
                max_retries=OPENAI_MAX_RETRIES,
            )

        # 나중에 각 모듈에서 import
        from src.graph.nodes import RFPAnswerGenerator, QueryIntentParser, QuestionPlanner
        _ensure_parsers_package_compat()
        from src.retrievers.vectorstore import VectorStore
        from src.graph.state import ConversationContext

        self.answer_generator = RFPAnswerGenerator(self.llm)
        default_db_path = str(Path(get_default_db_path()).resolve())
        self.vector_store = VectorStore(db_path=db_path or default_db_path)
        self.query_parser = QueryIntentParser(self.llm)
        self.question_planner = QuestionPlanner()
        self.conversation = ConversationContext(max_history=5)
        self.csv_metadata_by_filename: dict[str, dict[str, Any]] = {}
        self.csv_metadata_by_stem: dict[str, dict[str, Any]] = {}
        self.csv_metadata_by_org: dict[str, list[dict[str, Any]]] = {}
        self.csv_metadata_by_org_key: dict[str, list[dict[str, Any]]] = {}
        self.csv_metadata_by_notice_num: dict[str, dict[str, Any]] = {}
        self.csv_metadata_rows: list[dict[str, Any]] = []
        self.csv_question_field_map: dict[str, tuple[str, ...]] = {
            "amount": ("사업비", "예산", "사업 금액", "사 업 비", "사 업 금 액"),
            "notice_num": ("공고번호", "공고 번호", "notice"),
            "open_date": ("공개 일자", "공개일", "공고일"),
            "start_date": ("입찰 참여 시작", "입찰참여 시작", "입찰 시작", "개시일"),
            "end_date": ("입찰 참여 마감", "입찰참여 마감", "입찰 마감", "마감일", "마감"),
            "org_name": ("발주 기관", "발주기관", "기관명"),
            "project_name": ("사업명", "프로젝트명"),
            "summary": ("사업 요약", "요약"),
            "filename": ("파일명", "문서명"),
        }
        self.unified_markdown_dir = (self.data_dir.parent / "processed_runtime" / "markdown").resolve()
        self.unified_markdown_dir.mkdir(parents=True, exist_ok=True)
        self.failed_sources_registry_path = (
            self.data_dir.parent / "processed_runtime" / "indexing_failed_sources.json"
        ).resolve()
        self.failed_sources_registry = self._load_failed_sources_registry()
        self._chunk_budget_cache: dict[str, dict[str, Any]] = {}
        self._chunk_budget_cache_ready = False

        self._load_documents()

    @staticmethod
    def _has_csv_seed_files(base_dir: Path) -> bool:
        """CSV 시드 파일(data_list*.csv)이 존재하는지 확인합니다."""
        if not base_dir or not base_dir.is_dir():
            return False
        return any(base_dir.glob("data_list*.csv")) or any(base_dir.glob("*data*.csv"))

    def _load_documents(self) -> None:
        """모든 문서를 로드하고 변환합니다."""
        if self.vector_store.count > 0:
            print(f"ℹ️ 기존 Chroma 컬렉션 재사용: count={self.vector_store.count}")
            self._load_csv_files(verbose=False, add_chunks=False)
            self._hydrate_org_registry_from_existing_chunks()
            return

        is_initial_load = self.vector_store.count == 0
        self._load_csv_files(verbose=is_initial_load, add_chunks=is_initial_load)

        chunk_counts = self._count_chunks_by_type_compat()
        has_csv_chunks = chunk_counts.get("csv", 0) > 0

        if not has_csv_chunks:
            print("ℹ️ CSV 청크가 없어 CSV 재인덱싱을 수행합니다.")
            self._load_csv_files(verbose=True, add_chunks=True)

        should_load_docs = self._has_unindexed_document_files()
        if should_load_docs:
            print("=" * 60)
            print("입찰메이트 v17 - 마크다운 통합 데이터베이스 구축")
            print("=" * 60)
            self._load_document_files(force_reload=False)
            print("=" * 60)
            print(f"총 {len(self.vector_store.org_registry)}개 기관 등록 완료")
            print(f"벡터 DB 청크 수: {self.vector_store.count}")
            print("=" * 60)
        else:
            # 기존 벡터 DB 재사용 시에도 org_registry를 문서 메타데이터 기준으로 보강한다.
            self._hydrate_org_registry_from_existing_chunks()

    def _load_csv_files(self, verbose: bool = False, add_chunks: bool = False) -> None:
        """CSV 파일을 로드하고 변환합니다."""
        csv_files = []

        # 현재 data_dir에서 CSV 파일 검색
        csv_files.extend(list(self.data_dir.glob("data_list*.csv")))
        csv_files.extend(list(self.data_dir.glob("*data*.csv")))

        # 상위 폴더에서도 CSV 파일 검색 (data_dir이 files 하위인 경우)
        parent_dir = self.data_dir.parent
        if parent_dir.name != "data":
            csv_files.extend(list(parent_dir.glob("data_list*.csv")))
            csv_files.extend(list(parent_dir.glob("*data*.csv")))

        if not csv_files:
            if verbose:
                print("⚠️ CSV 파일을 찾을 수 없습니다.")
            return

        csv_file = csv_files[0]
        if verbose:
            print(f"\n📊 CSV 파일 처리 중: {csv_file.name}")

        from src.parsers.csv_loader import CSVMarkdownConverter
        markdowns = self.vector_store.csv_converter.convert_file(csv_file)
        if verbose:
            print(f"  변환된 마크다운: {len(markdowns)}개")

        self._index_csv_metadata(markdowns)
        self._register_csv_orgs(markdowns)

        if add_chunks:
            self._add_csv_chunks(markdowns)

    def _index_csv_metadata(self, markdowns: list[Any]) -> None:
        """CSV 메타데이터 매칭 인덱스를 구성합니다."""
        self.csv_metadata_by_filename = {}
        self.csv_metadata_by_stem = {}
        self.csv_metadata_by_org = {}
        self.csv_metadata_by_org_key = {}
        self.csv_metadata_by_notice_num = {}
        self.csv_metadata_rows = []

        for md_data in markdowns:
            meta = dict(getattr(md_data, "metadata", {}) or {})
            markdown_text = str(getattr(md_data, "markdown", "") or "")

            # CSVMarkdownConverter는 구조화 필드를 metadata에 넣지 않는 경우가 있어,
            # 마크다운 본문 라벨과 객체 속성에서 값을 보강한다.
            filename = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("filename"),
                    meta.get("파일명"),
                    getattr(md_data, "filename", ""),
                    self._extract_markdown_meta_value(markdown_text, "파일명"),
                )
            )
            stem = Path(filename).stem.lower() if filename else ""
            org_name = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("org_name"),
                    meta.get("org"),
                    meta.get("발주 기관"),
                    meta.get("발주기관"),
                    getattr(md_data, "org_name", ""),
                    self._extract_markdown_meta_value(markdown_text, "발주 기관"),
                )
            )
            project_name = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("project_name"),
                    meta.get("사업명"),
                    getattr(md_data, "project_name", ""),
                    self._extract_markdown_meta_value(markdown_text, "사업명"),
                )
            )
            amount_value = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("amount"),
                    meta.get("사업 금액"),
                    meta.get("사업금액"),
                    getattr(md_data, "amount", ""),
                    self._extract_markdown_meta_value(markdown_text, "사업 금액"),
                )
            )
            summary_value = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("summary"),
                    meta.get("사업 요약"),
                    meta.get("사업요약"),
                    getattr(md_data, "summary", ""),
                    self._extract_markdown_meta_value(markdown_text, "사업 요약"),
                )
            )
            open_date_value = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("open_date"),
                    meta.get("공개 일자"),
                    getattr(md_data, "open_date", ""),
                    self._extract_markdown_meta_value(markdown_text, "공개 일자"),
                )
            )
            start_date_value = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("start_date"),
                    meta.get("입찰 시작일"),
                    meta.get("입찰 참여 시작일"),
                    getattr(md_data, "start_date", ""),
                    self._extract_markdown_meta_value(markdown_text, "입찰 시작일"),
                )
            )
            end_date_value = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("end_date"),
                    meta.get("입찰 마감일"),
                    meta.get("입찰 참여 마감일"),
                    getattr(md_data, "end_date", ""),
                    self._extract_markdown_meta_value(markdown_text, "입찰 마감일"),
                )
            )
            notice_num_raw = self._clean_csv_value(
                self._first_non_empty(
                    meta.get("notice_num"),
                    meta.get("공고 번호"),
                    self._extract_markdown_meta_value(markdown_text, "공고 번호"),
                )
            )
            notice_num = self._normalize_notice_number(notice_num_raw)
            amount_numeric = parse_amount(amount_value)
            org_key = self._normalize_text_for_match(org_name) if org_name else ""

            normalized = {
                **meta,
                "filename": filename,
                "file_stem": stem,
                "org_name": org_name,
                "project_name": project_name,
                "amount": amount_value,
                "summary": summary_value,
                "open_date": open_date_value,
                "start_date": start_date_value,
                "end_date": end_date_value,
                "org_key": org_key,
                "notice_num": notice_num,
                "notice_num_raw": notice_num_raw,
                "amount_numeric": amount_numeric,
            }
            if filename:
                self.csv_metadata_by_filename[filename.lower()] = normalized
            if stem:
                self.csv_metadata_by_stem[stem] = normalized
            if org_name:
                self.csv_metadata_by_org.setdefault(org_name, []).append(normalized)
            if org_key:
                self.csv_metadata_by_org_key.setdefault(org_key, []).append(normalized)
            if notice_num and notice_num not in self.csv_metadata_by_notice_num:
                self.csv_metadata_by_notice_num[notice_num] = normalized
            self.csv_metadata_rows.append(normalized)

    @staticmethod
    def _first_non_empty(*values: Any) -> str:
        """첫 번째 유효 문자열 값을 반환합니다."""
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _clean_csv_value(value: Any) -> str:
        """CSV 메타데이터에서 공란/NaN/정보없음을 정리합니다."""
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = unicodedata.normalize("NFKC", text).lower()
        if lowered in {"nan", "none", "null", "-", "정보 없음", "정보없음"}:
            return ""
        return text

    @staticmethod
    def _extract_markdown_meta_value(markdown: str, label: str) -> str:
        """CSV 마크다운 라벨(`- **라벨**: 값`)에서 값을 추출합니다."""
        if not markdown or not label:
            return ""
        pattern = rf"-\s*\*\*{re.escape(label)}\*\*:\s*(.+)"
        match = re.search(pattern, markdown)
        if not match:
            return ""
        value = match.group(1).strip()
        if value.startswith("**") and value.endswith("**"):
            value = value[2:-2].strip()
        return value

    @staticmethod
    def _normalize_notice_number(value: Any) -> str:
        """공고번호를 숫자 문자열로 정규화합니다."""
        return re.sub(r"[^0-9]", "", str(value or ""))

    def _lookup_csv_metadata(self, source_file: Path, org_name: str) -> dict[str, Any]:
        """원본 파일에 대응되는 CSV 메타데이터를 조회합니다."""
        by_filename = self.csv_metadata_by_filename.get(source_file.name.lower())
        if by_filename:
            return by_filename

        by_stem = self.csv_metadata_by_stem.get(source_file.stem.lower())
        if by_stem:
            return by_stem

        if org_name in self.csv_metadata_by_org and self.csv_metadata_by_org[org_name]:
            return self.csv_metadata_by_org[org_name][0]

        return {}

    @staticmethod
    def _extract_metadata_source(metadata: dict[str, Any]) -> str:
        for key in ("source", "source_file", "filename", "파일명"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _extract_metadata_page(metadata: dict[str, Any]) -> int | None:
        for key in ("page", "page_start", "page_no"):
            value = metadata.get(key)
            try:
                page = int(value)
            except Exception:
                continue
            if page > 0:
                return page
        refs = metadata.get("page_refs")
        if isinstance(refs, list):
            for ref in refs:
                try:
                    page = int(ref)
                except Exception:
                    continue
                if page > 0:
                    return page
        return None

    @staticmethod
    def _extract_metadata_org(metadata: dict[str, Any]) -> str:
        for key in ("org", "org_name", "institution", "발주 기관", "발주기관", "기관명"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _infer_metadata_doc_type(cls, metadata: dict[str, Any]) -> str:
        raw_type = str(metadata.get("type", "") or "").strip().lower()
        if raw_type in {"pdf", "hwp", "csv"}:
            return raw_type

        source = cls._extract_metadata_source(metadata)
        suffix = Path(source).suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".hwp", ".hwpx"}:
            return "hwp"
        if suffix == ".csv":
            return "csv"
        return raw_type or "unknown"

    def _normalize_retrieval_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            metadata = dict(metadata)

            source = str(item.get("source") or self._extract_metadata_source(metadata) or "").strip()
            page = item.get("page")
            if page is None:
                page = self._extract_metadata_page(metadata)
            org = str(metadata.get("org") or self._extract_metadata_org(metadata) or "").strip()
            doc_type = self._infer_metadata_doc_type(metadata)

            if source:
                metadata.setdefault("source", source)
            if page is not None:
                metadata["page"] = page
            if org:
                metadata["org"] = org
            metadata["type"] = doc_type

            normalized.append(
                {
                    **item,
                    "metadata": metadata,
                    "source": source,
                    "page": page,
                }
            )
        return normalized

    def _apply_result_filters(
        self,
        results: list[dict[str, Any]],
        org_name: str | None,
        doc_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        type_filter = {str(t).lower() for t in (doc_types or []) if t}
        filtered: list[dict[str, Any]] = []
        for item in results:
            md = item.get("metadata", {}) or {}
            item_type = self._infer_metadata_doc_type(md)
            item_org = str(md.get("org", "")).strip()
            item_source = self._extract_metadata_source(md)

            if type_filter and item_type not in type_filter:
                continue
            if org_name:
                org_matched = self._org_names_loosely_match(item_org, org_name)
                if not org_matched and item_source:
                    org_key = self._normalize_text_for_match(org_name)
                    source_key = self._normalize_text_for_match(item_source)
                    relaxed_org = re.sub(
                        r"^(사단법인|재단법인|주식회사|\(주\)|\(사\)|\(재\)|유한회사|합자회사|\s)+",
                        "",
                        self._normalize_legal_name_tokens(org_name),
                    ).strip()
                    relaxed_key = self._normalize_text_for_match(relaxed_org)
                    org_matched = bool(
                        (org_key and org_key in source_key)
                        or (relaxed_key and relaxed_key in source_key)
                    )
                if not org_matched:
                    continue
            filtered.append(item)
        return filtered

    def _count_chunks_by_type_compat(self) -> dict[str, int]:
        method = getattr(self.vector_store, "count_chunks_by_type", None)
        if callable(method):
            try:
                data = method()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        counts: dict[str, int] = {}
        try:
            data = self.vector_store.collection.get(include=["metadatas"])
        except Exception:
            return counts

        for md in data.get("metadatas", []) or []:
            meta = md if isinstance(md, dict) else {}
            doc_type = self._infer_metadata_doc_type(meta)
            counts[doc_type] = counts.get(doc_type, 0) + 1
        return counts

    def _get_indexed_sources_compat(self, doc_types: list[str] | None = None) -> set[str]:
        method = getattr(self.vector_store, "get_indexed_sources", None)
        if callable(method):
            try:
                data = method(doc_types=doc_types)
                if isinstance(data, set):
                    return data
            except Exception:
                pass

        type_filter = {str(t).lower() for t in (doc_types or []) if t}
        sources: set[str] = set()
        try:
            data = self.vector_store.collection.get(include=["metadatas"])
        except Exception:
            return sources

        for md in data.get("metadatas", []) or []:
            meta = md if isinstance(md, dict) else {}
            doc_type = self._infer_metadata_doc_type(meta)
            if type_filter and doc_type not in type_filter:
                continue
            source = self._extract_metadata_source(meta)
            if source:
                sources.add(source)
        return sources

    def _collect_org_stats_compat(self) -> dict[str, dict[str, bool]]:
        method = getattr(self.vector_store, "collect_org_stats", None)
        if callable(method):
            try:
                data = method()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        stats: dict[str, dict[str, bool]] = {}
        try:
            data = self.vector_store.collection.get(include=["metadatas"])
        except Exception:
            return stats

        for md in data.get("metadatas", []) or []:
            meta = md if isinstance(md, dict) else {}
            org = self._extract_metadata_org(meta)
            if not org:
                continue
            item = stats.setdefault(org, {"has_pdf": False, "has_hwp": False})
            doc_type = self._infer_metadata_doc_type(meta)
            if doc_type == "pdf":
                item["has_pdf"] = True
            elif doc_type == "hwp":
                item["has_hwp"] = True
        return stats

    def _is_csv_shortcircuit_eligible(self, query: str, intent: QueryIntent, org_name: str = "") -> bool:
        """CSV 엄격 단축 경로 대상 질의인지 판별합니다."""
        if not CSV_SHORTCIRCUIT_ENABLED:
            return False

        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        if not normalized:
            return False
        if intent.query_type == "ranking":
            return False
        if self._is_comparison_query(query):
            return False
        if re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized, flags=re.IGNORECASE):
            return False
        # 숫자/단위/문자셋/복구기한/요구사항 코드 등 정밀 사실 질의는 CSV 단축을 금지한다.
        if self._is_precision_fact_query(query):
            return False

        disallow_tokens = [
            "준수사항", "의무", "절차", "제재", "비교", "차이", "공통", "동시에",
            "두 문서", "복합", "요구사항", "요건", "근거", "조항", "페이지", "텍스트", "본문",
        ]
        if any(token in normalized for token in disallow_tokens):
            return False

        field = self._detect_csv_structured_field(query)
        if not field:
            return False

        # 날짜 컬럼 단축은 입찰/공고 문맥일 때만 허용한다.
        if field in {"open_date", "start_date", "end_date"}:
            # 후속질문 등으로 기관 문맥이 이미 확정된 경우에는 날짜 단축 경로를 허용한다.
            if not any(token in normalized for token in ["입찰", "공고", "참여"]) and not org_name:
                return False
            if any(token in normalized for token in ["복구", "장애", "시스템 장애", "복원"]):
                return False

        # 금액 단축은 명시적 사업비/예산 의도 질의에서만 허용한다.
        if field == "amount" and not self._is_budget_query(query):
            return False
        return True

    def _detect_csv_structured_field(self, query: str) -> str | None:
        """질문에서 CSV 구조화 컬럼 타깃을 식별합니다."""
        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        if not normalized:
            return None

        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["notice_num"]]):
            return "notice_num"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["end_date"]]):
            return "end_date"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["start_date"]]):
            return "start_date"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["open_date"]]):
            return "open_date"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["org_name"]]):
            return "org_name"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["project_name"]]):
            return "project_name"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["summary"]]):
            return "summary"
        if ("추진 배경" in normalized or "추진배경" in normalized or "목적" in normalized) and "사업" in normalized:
            return "summary"
        if any(token in normalized for token in [t.lower() for t in self.csv_question_field_map["filename"]]):
            return "filename"
        if self._is_budget_query(query):
            return "amount"
        amount_tokens = [t.lower() for t in self.csv_question_field_map["amount"] if t.lower() != "예산"]
        if any(token in normalized for token in amount_tokens):
            return "amount"
        return None

    def _extract_notice_num_from_query(self, query: str) -> str:
        """질문에서 공고번호 후보를 추출합니다."""
        normalized = unicodedata.normalize("NFKC", (query or ""))
        matches = re.findall(r"\d{8,14}", normalized)
        if not matches:
            return ""
        return self._normalize_notice_number(matches[0])

    def _score_csv_row_for_query(
        self,
        query: str,
        row: dict[str, Any],
        hints: list[str],
        keyword_keys: list[str],
    ) -> float:
        """질문-CSV 행 매칭 점수를 계산합니다."""
        candidate_text = " ".join(
            [
                str(row.get("org_name", "")),
                str(row.get("project_name", "")),
                str(row.get("filename", "")),
                str(row.get("summary", "")),
                str(row.get("notice_num", "")),
            ]
        )
        candidate_key = self._normalize_text_for_match(candidate_text)
        query_key = self._normalize_text_for_match(query)
        project_name = str(row.get("project_name", "")).strip()
        project_key = self._normalize_text_for_match(project_name)

        score = 0.0

        for hint in hints:
            if hint and hint in candidate_key:
                score += 6.0

        for keyword in keyword_keys:
            if keyword and keyword in candidate_key:
                score += 0.8

        if query_key and len(query_key) >= 8 and query_key in candidate_key:
            score += 8.0

        if project_key and query_key:
            if project_key in query_key:
                score += 8.0

            query_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", query.lower())))
            project_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", project_name.lower())))
            overlap = len(query_tokens.intersection(project_tokens))
            if overlap >= 2:
                score += overlap * 1.6

        normalized_q = unicodedata.normalize("NFKC", query.lower())
        if re.search(r"(입찰|시작|마감|기한|일정|참여)", normalized_q) and row.get("start_date"):
            score += 0.4
        if self._is_budget_query(query) and float(row.get("amount_numeric", 0) or 0) > 0:
            score += 0.6
        if "기능개선" in normalized_q and "기능개선" in unicodedata.normalize("NFKC", project_name.lower()):
            score += 1.2
        if "재구축" in normalized_q and "재구축" in unicodedata.normalize("NFKC", project_name.lower()):
            score += 1.2
        return score

    def _select_csv_row_for_shortcircuit(
        self,
        query: str,
        intent: QueryIntent,
        org_name: str,
    ) -> dict[str, Any] | None:
        """CSV 단축 경로에서 단일 행을 고해상도로 선택합니다."""
        notice_num = self._extract_notice_num_from_query(query)
        if notice_num:
            by_notice = self.csv_metadata_by_notice_num.get(notice_num)
            if by_notice:
                return by_notice

        org_candidates: list[str] = []
        for cand in [org_name, intent.org_name]:
            resolved = self._resolve_known_org_name(cand) if cand else None
            name = resolved or cand
            self._append_unique_org_name(org_candidates, name)
        for cand in self._extract_org_names_from_query(query, limit=3, allow_project_fallback=False):
            resolved = self._resolve_known_org_name(cand) or cand
            self._append_unique_org_name(org_candidates, resolved)

        rows: list[dict[str, Any]] = []
        for candidate_org in org_candidates:
            direct_rows = self.csv_metadata_by_org.get(candidate_org, [])
            if direct_rows:
                rows.extend(direct_rows)
                continue
            org_key = self._normalize_text_for_match(candidate_org)
            if org_key and org_key in self.csv_metadata_by_org_key:
                rows.extend(self.csv_metadata_by_org_key.get(org_key, []))

        # 기관명이 없는 질의(사업명 직접 언급)는 전체 CSV에서 프로젝트 힌트 매칭으로 선택한다.
        if not rows and self.csv_metadata_rows:
            rows.extend(self.csv_metadata_rows)

        deduped_rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for row in rows:
            key = (
                str(row.get("filename", "")).lower(),
                str(row.get("notice_num", "")),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_rows.append(row)

        if len(deduped_rows) == 1:
            return deduped_rows[0]

        if len(deduped_rows) > 1:
            hints = [
                self._normalize_text_for_match(hint)
                for hint in self._extract_project_hints_from_query(query)
                if 2 <= len(hint) <= 80
            ]
            if hints:
                narrowed = []
                for row in deduped_rows:
                    candidate_text = " ".join(
                        [
                            str(row.get("project_name", "")),
                            str(row.get("filename", "")),
                            str(row.get("summary", "")),
                        ]
                    )
                    candidate_key = self._normalize_text_for_match(candidate_text)
                    if any(hint and hint in candidate_key for hint in hints):
                        narrowed.append(row)
                if len(narrowed) == 1:
                    return narrowed[0]
                if len(narrowed) > 1:
                    deduped_rows = narrowed

            # 동일 기관에 다수 사업이 있을 때는 질문 키워드와의 일치도를 우선한다.
            keyword_keys = [
                self._normalize_text_for_match(token)
                for token in self._extract_query_keywords(query, max_keywords=14)
                if len(token) >= 2
            ]
            scored_rows: list[tuple[float, dict[str, Any]]] = []
            for row in deduped_rows:
                score = self._score_csv_row_for_query(query, row, hints=hints, keyword_keys=keyword_keys)
                scored_rows.append((score, row))

            if scored_rows:
                scored_rows.sort(
                    key=lambda item: (
                        item[0],
                        float(item[1].get("amount_numeric", 0) or 0),
                        len(str(item[1].get("project_name", "") or "")),
                    ),
                    reverse=True,
                )
                top_score = scored_rows[0][0]
                second_score = scored_rows[1][0] if len(scored_rows) > 1 else -1.0
                has_project_hints = bool(hints)
                if org_candidates:
                    min_score = 2.2
                elif has_project_hints:
                    min_score = 1.8
                else:
                    min_score = 4.6
                min_margin = 0.2 if has_project_hints else 0.35
                if top_score >= min_score and (len(scored_rows) == 1 or (top_score - second_score) >= min_margin):
                    return scored_rows[0][1]

            # 기관 문맥만 있는 후속질문은 대표성(금액/사업명 보유) 기준으로 1건을 선택한다.
            if org_name:
                ranked_rows = sorted(
                    deduped_rows,
                    key=lambda row: (
                        float(row.get("amount_numeric", 0) or 0),
                        len(str(row.get("project_name", "") or "")),
                        len(str(row.get("summary", "") or "")),
                    ),
                    reverse=True,
                )
                if ranked_rows:
                    return ranked_rows[0]
        return None

    def _build_csv_shortcircuit_payload(
        self,
        query: str,
        field: str,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        """CSV 단축 답변 payload를 생성합니다."""
        org_name = str(row.get("org_name", "")).strip()
        source = str(row.get("filename", "")).strip() or "csv"
        amount_numeric = parse_amount(str(row.get("amount", "")))
        summary_text = str(row.get("summary", "")).strip()
        if summary_text and len(summary_text) > 260:
            summary_text = summary_text[:260].rstrip() + "..."

        value_map: dict[str, tuple[str, str]] = {
            "amount": ("사업비", format_amount(amount_numeric) if amount_numeric > 0 else str(row.get("amount", "")).strip()),
            "notice_num": ("공고번호", str(row.get("notice_num", "")).strip()),
            "open_date": ("공개 일자", str(row.get("open_date", "")).strip()),
            "start_date": ("입찰 참여 시작일", str(row.get("start_date", "")).strip()),
            "end_date": ("입찰 참여 마감일", str(row.get("end_date", "")).strip()),
            "org_name": ("발주 기관", org_name),
            "project_name": ("사업명", str(row.get("project_name", "")).strip()),
            "summary": ("사업 요약", summary_text),
            "filename": ("파일명", source),
        }
        if org_name in self.vector_store.org_registry:
            org_info = self.vector_store.org_registry.get(org_name)
            if org_info:
                if field == "project_name" and not value_map["project_name"][1]:
                    value_map["project_name"] = ("사업명", str(org_info.project_name or "").strip())
                if field == "amount" and not value_map["amount"][1] and org_info.amount_numeric > 0:
                    value_map["amount"] = ("사업비", format_amount(org_info.amount_numeric))
        label, value = value_map.get(field, ("값", ""))
        if not value:
            return None

        prefix = f"{org_name} 문서 기준 " if org_name else "문서 기준 "
        answer = f"{prefix}{label}은(는) `{value}`입니다.\n\n[출처]\n- {source} (CSV)"
        evidence = [
            {
                "source": source,
                "page": None,
                "text": f"{label}: {value}",
                "slot": "value",
                "score": 1.0,
            }
        ]
        return {
            "answer": self._format_answer_for_readability(answer),
            "found": True,
            "source_type": "csv",
            "answer_mode": "extractive",
            "slot_fill_rate": 1.0,
            "evidence_count": len(evidence),
            "confidence": 0.93,
            "evidence": evidence,
            "csv_short_circuit": True,
        }

    def _resolve_csv_org_scope(self, query: str, intent: QueryIntent, org_name: str) -> str:
        """CSV 단축 경로에서 사용할 기관 스코프를 보수적으로 확정합니다."""
        candidates: list[str] = []
        for cand in [org_name, intent.org_name]:
            resolved = self._resolve_known_org_name(cand) if cand else None
            name = resolved or cand
            self._append_unique_org_name(candidates, name)
        for cand in self._extract_org_names_from_query(query, limit=3, allow_project_fallback=False):
            resolved = self._resolve_known_org_name(cand) or cand
            self._append_unique_org_name(candidates, resolved)

        for candidate in candidates:
            if candidate in self.csv_metadata_by_org:
                return candidate
            candidate_key = self._normalize_text_for_match(candidate)
            if candidate_key and candidate_key in self.csv_metadata_by_org_key:
                return candidate
        return ""

    def _try_csv_short_circuit(
        self,
        query: str,
        intent: QueryIntent,
        org_name: str,
    ) -> dict[str, Any] | None:
        """CSV 구조화 필드 질의는 빠르게 즉답하고 종료합니다."""
        if not CSV_SHORTCIRCUIT_ENABLED:
            return None

        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        if not normalized:
            return None
        if self._is_comparison_query(query):
            return None
        org_scope = self._resolve_csv_org_scope(query, intent, org_name)

        asks_budget_schedule_summary = (
            "요약" in normalized
            and any(token in normalized for token in ["예산", "사업비", "금액"])
            and any(token in normalized for token in ["일정", "시작", "마감", "입찰"])
            and any(token in normalized for token in ["범위", "주요", "사업"])
        )
        if asks_budget_schedule_summary:
            row = self._select_csv_row_for_shortcircuit(query, intent, org_name=org_name)
            if row:
                org_label = str(row.get("org_name", "")).strip() or org_name or "해당 사업"
                source = str(row.get("filename", "")).strip() or "csv"
                amount_numeric = parse_amount(str(row.get("amount", "")))
                amount_value = (
                    format_amount(amount_numeric)
                    if amount_numeric > 0
                    else str(row.get("amount", "")).strip() or "정보 없음"
                )
                start_value = str(row.get("start_date", "")).strip() or "-"
                end_value = str(row.get("end_date", "")).strip() or "-"
                summary_value = str(row.get("summary", "")).strip() or "요약 정보 없음"
                if len(summary_value) > 320:
                    summary_value = summary_value[:320].rstrip() + "..."

                answer = (
                    f"{org_label} 문서 기준 요약입니다.\n\n"
                    f"- 예산: `{amount_value}`\n"
                    f"- 입찰 일정: `{start_value}` ~ `{end_value}`\n"
                    f"- 주요 사업 범위: {summary_value}\n\n"
                    f"[출처]\n- {source} (CSV)"
                )
                evidence = [
                    {
                        "source": source,
                        "page": None,
                        "text": f"amount={amount_value}, start={start_value}, end={end_value}",
                        "slot": "value",
                        "score": 1.0,
                    }
                ]
                payload = {
                    "answer": self._format_answer_for_readability(answer),
                    "found": True,
                    "source_type": "csv",
                    "answer_mode": "extractive",
                    "slot_fill_rate": 1.0,
                    "evidence_count": len(evidence),
                    "confidence": 0.95,
                    "evidence": evidence,
                    "csv_short_circuit": True,
                }
                self.conversation.add_exchange(query, payload.get("answer", ""), intent)
                return payload

        # 기관별 사업 개수/사업명 목록 질의
        asks_org_project_list = (
            ("총 몇" in normalized or "몇 개" in normalized or "몇개" in normalized)
            and any(token in normalized for token in ["사업", "사업명", "무엇"])
        )
        if asks_org_project_list and org_scope:
            rows = list(self.csv_metadata_by_org.get(org_scope, []))
            if not rows:
                org_key = self._normalize_text_for_match(org_scope)
                rows = list(self.csv_metadata_by_org_key.get(org_key, [])) if org_key else []
            dedup: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                project = str(row.get("project_name", "")).strip()
                if not project or project in seen:
                    continue
                seen.add(project)
                dedup.append(row)
            if dedup:
                lines = [f"{idx}. {str(row.get('project_name', '')).strip()}" for idx, row in enumerate(dedup, 1)]
                answer = (
                    f"{org_scope}에서 진행 중인 사업은 총 {len(dedup)}개입니다.\n\n"
                    + "\n".join(lines[:12])
                    + "\n\n[출처]\n- data_list (CSV)"
                )
                evidence = [
                    {
                        "source": str(dedup[0].get("filename", "")).strip() or "data_list.csv",
                        "page": None,
                        "text": f"사업 개수: {len(dedup)}",
                        "slot": "value",
                        "score": 1.0,
                    }
                ]
                payload = {
                    "answer": self._format_answer_for_readability(answer),
                    "found": True,
                    "source_type": "csv",
                    "answer_mode": "extractive",
                    "slot_fill_rate": 1.0,
                    "evidence_count": len(evidence),
                    "confidence": 0.94,
                    "evidence": evidence,
                    "csv_short_circuit": True,
                }
                self.conversation.add_exchange(query, payload.get("answer", ""), intent)
                return payload

        # 기관별 사업들의 추진 배경/목적 요약 요청은 CSV 요약 컬럼을 직접 활용한다.
        asks_background_and_purpose = (
            any(token in normalized for token in ["사업들", "각 사업", "주관하는 사업"])
            and any(token in normalized for token in ["추진 배경", "추진배경", "목적"])
        )
        if asks_background_and_purpose and org_scope:
            rows = list(self.csv_metadata_by_org.get(org_scope, []))
            if not rows:
                org_key = self._normalize_text_for_match(org_scope)
                rows = list(self.csv_metadata_by_org_key.get(org_key, [])) if org_key else []
            if rows:
                ranked_rows = sorted(
                    rows,
                    key=lambda row: (
                        len(str(row.get("summary", "") or "")),
                        float(row.get("amount_numeric", 0) or 0),
                    ),
                    reverse=True,
                )
                answer_lines = [f"{org_scope} 주요 사업의 추진 배경/목적 요약입니다.", ""]
                evidence: list[dict[str, Any]] = []
                for idx, row in enumerate(ranked_rows[:4], 1):
                    project_name = str(row.get("project_name", "")).strip() or f"사업 {idx}"
                    summary = str(row.get("summary", "")).strip()
                    summary_lines = [
                        re.sub(r"^\s*[-•·]\s*", "", ln.strip())
                        for ln in summary.splitlines()
                        if len(ln.strip()) >= 8
                    ]
                    compact_summary = " / ".join(summary_lines[:2]) if summary_lines else (summary[:180] if summary else "요약 정보 없음")
                    answer_lines.append(f"{idx}. {project_name}: {compact_summary}")
                    evidence.append(
                        {
                            "source": str(row.get("filename", "")).strip() or "data_list.csv",
                            "page": None,
                            "text": f"{project_name}: {compact_summary}",
                            "slot": "value",
                            "score": 1.0,
                        }
                    )
                answer_lines.append("")
                answer_lines.append("[출처]")
                answer_lines.append("- data_list (CSV)")
                payload = {
                    "answer": self._format_answer_for_readability("\n".join(answer_lines)),
                    "found": True,
                    "source_type": "csv",
                    "answer_mode": "extractive",
                    "slot_fill_rate": 1.0,
                    "evidence_count": len(evidence),
                    "confidence": 0.93,
                    "evidence": evidence,
                    "csv_short_circuit": True,
                }
                self.conversation.add_exchange(query, payload.get("answer", ""), intent)
                return payload

        asks_short_feature_improvement = (
            ("사업기간" in normalized or "기간" in normalized)
            and any(token in normalized for token in ["상대적으로 짧", "짧고", "짧은"])
            and "기능개선" in normalized
        )
        if asks_short_feature_improvement and org_scope:
            rows = list(self.csv_metadata_by_org.get(org_scope, []))
            if not rows:
                org_key = self._normalize_text_for_match(org_scope)
                rows = list(self.csv_metadata_by_org_key.get(org_key, [])) if org_key else []
            if rows:
                def _estimate_duration_days(row: dict[str, Any]) -> float:
                    start = str(row.get("start_date", "")).strip()
                    end = str(row.get("end_date", "")).strip()
                    if start and end:
                        try:
                            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                            delta = (end_dt - start_dt).total_seconds() / 86400.0
                            if delta > 0:
                                return delta
                        except Exception:
                            pass
                    summary_text = str(row.get("summary", "") or "")
                    day_match = re.search(r"(\d{2,4})\s*일", summary_text)
                    if day_match:
                        return float(day_match.group(1))
                    month_match = re.search(r"(\d{1,2})\s*개월", summary_text)
                    if month_match:
                        return float(month_match.group(1)) * 30.0
                    return float("inf")

                normalized_rows = []
                for row in rows:
                    project_name = str(row.get("project_name", "")).strip()
                    duration_days = _estimate_duration_days(row)
                    normalized_rows.append((duration_days, project_name, row))

                candidate_rows = [item for item in normalized_rows if "기능개선" in item[1]]
                target_pool = candidate_rows or normalized_rows
                target_pool = [item for item in target_pool if item[0] != float("inf")] or target_pool
                target_pool.sort(key=lambda item: item[0])
                selected = target_pool[0] if target_pool else None
                if selected:
                    selected_days, selected_name, selected_row = selected
                    compare_row = None
                    for item in sorted(normalized_rows, key=lambda x: x[0], reverse=True):
                        if item[1] != selected_name:
                            compare_row = item
                            break
                    duration_text = (
                        f"{int(selected_days)}일"
                        if selected_days not in {float('inf'), float('-inf')}
                        else "기간 정보 없음"
                    )
                    answer_lines = [
                        f"조건에 부합하는 사업은 `{selected_name}`입니다.",
                        "",
                        f"- 선택 근거: 기능개선 성격 + 상대적으로 짧은 사업기간(`{duration_text}`)",
                    ]
                    if compare_row:
                        compare_days, compare_name, _ = compare_row
                        if compare_days not in {float('inf'), float('-inf')}:
                            answer_lines.append(f"- 비교 근거: `{compare_name}`는 약 `{int(compare_days)}일`로 더 긴 편입니다.")
                    answer_lines.extend(["", "[출처]", "- data_list (CSV)"])
                    evidence = [
                        {
                            "source": str(selected_row.get("filename", "")).strip() or "data_list.csv",
                            "page": None,
                            "text": f"{selected_name} / duration={duration_text}",
                            "slot": "value",
                            "score": 1.0,
                        }
                    ]
                    payload = {
                        "answer": self._format_answer_for_readability("\n".join(answer_lines)),
                        "found": True,
                        "source_type": "csv",
                        "answer_mode": "extractive",
                        "slot_fill_rate": 1.0,
                        "evidence_count": len(evidence),
                        "confidence": 0.9,
                        "evidence": evidence,
                        "csv_short_circuit": True,
                    }
                    self.conversation.add_exchange(query, payload.get("answer", ""), intent)
                    return payload

        if not self._is_csv_shortcircuit_eligible(query, intent, org_name=org_name):
            return None

        field = self._detect_csv_structured_field(query)
        if not field:
            return None

        row = self._select_csv_row_for_shortcircuit(query, intent, org_name=org_name)
        if not row:
            return None

        # "시작일과 마감일 각각" 같이 복수 필드를 묻는 경우 두 값을 한 번에 응답
        asks_start = any(token in normalized for token in ["시작", "개시", "참여 시작"])
        asks_end = any(token in normalized for token in ["마감", "종료", "기한"])
        if asks_start and asks_end:
            start_value = str(row.get("start_date", "")).strip()
            end_value = str(row.get("end_date", "")).strip()
            if start_value or end_value:
                org_label = str(row.get("org_name", "")).strip() or org_name
                source = str(row.get("filename", "")).strip() or "csv"
                answer = (
                    f"{org_label} 문서 기준 입찰 참여 시작일은 `{start_value or '-'}`이고, "
                    f"마감일은 `{end_value or '-'}`입니다.\n\n[출처]\n- {source} (CSV)"
                )
                evidence = [
                    {
                        "source": source,
                        "page": None,
                        "text": f"start_date={start_value}, end_date={end_value}",
                        "slot": "value",
                        "score": 1.0,
                    }
                ]
                payload = {
                    "answer": self._format_answer_for_readability(answer),
                    "found": True,
                    "source_type": "csv",
                    "answer_mode": "extractive",
                    "slot_fill_rate": 1.0,
                    "evidence_count": len(evidence),
                    "confidence": 0.94,
                    "evidence": evidence,
                    "csv_short_circuit": True,
                }
                self.conversation.add_exchange(query, payload.get("answer", ""), intent)
                return payload

        payload = self._build_csv_shortcircuit_payload(query, field, row)
        if payload:
            self.conversation.add_exchange(query, payload.get("answer", ""), intent)
            return payload

        # CSV 행은 있으나 값이 비어 있는 경우에도 후속질문 맥락이 끊기지 않도록 명시적으로 반환한다.
        if row and org_name and field in {"open_date", "start_date", "end_date", "project_name", "amount"}:
            field_label = {
                "open_date": "공개 일자",
                "start_date": "입찰 참여 시작일",
                "end_date": "입찰 참여 마감일",
                "project_name": "사업명",
                "amount": "사업비",
            }.get(field, "요청 값")
            source = str(row.get("filename", "")).strip() or "csv"
            answer = (
                f"{org_name} 문서 기준 `{field_label}` 정보는 현재 메타데이터에 명시되어 있지 않습니다.\n\n"
                f"[출처]\n- {source} (CSV)"
            )
            fallback_payload = {
                "answer": self._format_answer_for_readability(answer),
                "found": True,
                "source_type": "csv",
                "answer_mode": "extractive",
                "slot_fill_rate": 0.7,
                "evidence_count": 1,
                "confidence": 0.72,
                "evidence": [
                    {
                        "source": source,
                        "page": None,
                        "text": f"{field_label}: 명시 없음",
                        "slot": "value",
                        "score": 0.7,
                    }
                ],
                "csv_short_circuit": True,
            }
            self.conversation.add_exchange(query, fallback_payload.get("answer", ""), intent)
            return fallback_payload
        return None

    def _is_org_overview_query(self, query: str, intent: QueryIntent, org_name: str) -> bool:
        """기관 기본 정보/소개형 질의 여부를 판별합니다."""
        if not org_name:
            return False
        if intent.query_type in {"ranking", "filter"}:
            return False
        if self._is_comparison_query(query):
            return False
        if self._is_budget_query(query) or self._is_precision_fact_query(query):
            return False

        normalized = unicodedata.normalize("NFKC", (query or "").lower()).strip()
        if not normalized:
            return False

        disallow_tokens = [
            "마감", "기한", "기간", "언제", "얼마", "누가", "제출", "요구사항", "요건",
            "책임", "부담", "문자셋", "인코딩", "복구", "가용성", "평가", "배점",
            "협상", "순위", "top", "가장", "많은", "적은", "비교", "차이", "공통",
        ]
        if any(token in normalized for token in disallow_tokens):
            return False

        overview_tokens = ["소개", "개요", "요약", "프로필", "기본 정보"]
        if any(token in normalized for token in overview_tokens):
            return True
        if re.search(r"(정보\s*(알려줘|알려주세요|줘|요약|소개))", normalized):
            return True

        org_key = self._normalize_text_for_match(org_name)
        query_key = self._normalize_text_for_match(normalized)
        if org_key and query_key.startswith(org_key):
            tail = query_key[len(org_key):]
            if tail in {"", "정보", "소개", "개요", "요약", "안내"}:
                return True
        return False

    def _select_org_metadata_row(self, org_name: str) -> dict[str, Any] | None:
        """기관명으로 CSV 메타데이터 행 1개를 선택합니다."""
        rows = self.csv_metadata_by_org.get(org_name, [])
        if rows:
            return rows[0]
        org_key = self._normalize_text_for_match(org_name)
        if org_key and org_key in self.csv_metadata_by_org_key:
            matches = self.csv_metadata_by_org_key.get(org_key, [])
            if matches:
                return matches[0]
        return None

    def _try_org_overview_short_circuit(
        self,
        query: str,
        intent: QueryIntent,
        org_name: str,
    ) -> dict[str, Any] | None:
        """기관 소개형 질문은 CSV/레지스트리 메타데이터로 즉시 응답합니다."""
        if not self._is_org_overview_query(query, intent, org_name):
            return None

        row = self._select_org_metadata_row(org_name)
        org_info = self.vector_store.org_registry.get(org_name) if org_name else None
        if not row and not org_info:
            return None

        project_name = str((row or {}).get("project_name", "")).strip() or str(getattr(org_info, "project_name", "") or "").strip()
        summary = str((row or {}).get("summary", "")).strip() or str(getattr(org_info, "summary", "") or "").strip()
        open_date = str((row or {}).get("open_date", "")).strip()
        start_date = str((row or {}).get("start_date", "")).strip()
        end_date = str((row or {}).get("end_date", "")).strip()
        source = str((row or {}).get("filename", "")).strip()

        amount_text = ""
        amount_numeric = parse_amount(str((row or {}).get("amount", "") or ""))
        if amount_numeric > 0:
            amount_text = format_amount(amount_numeric)
        elif org_info and getattr(org_info, "amount_numeric", 0) > 0:
            amount_text = format_amount(float(org_info.amount_numeric))

        if summary and len(summary) > 220:
            summary = summary[:220].rstrip() + "..."

        bullet_lines: list[str] = []
        if project_name:
            bullet_lines.append(f"- 사업명: {project_name}")
        if amount_text:
            bullet_lines.append(f"- 사업비: {amount_text}")
        if open_date:
            bullet_lines.append(f"- 공개일: {open_date}")
        if start_date:
            bullet_lines.append(f"- 입찰 시작일: {start_date}")
        if end_date:
            bullet_lines.append(f"- 입찰 마감일: {end_date}")
        if summary:
            bullet_lines.append(f"- 사업 요약: {summary}")

        if not bullet_lines:
            has_pdf = bool(getattr(org_info, "has_pdf", False)) if org_info else False
            has_hwp = bool(getattr(org_info, "has_hwp", False)) if org_info else False
            format_hint = []
            if has_pdf:
                format_hint.append("PDF")
            if has_hwp:
                format_hint.append("HWP")
            if format_hint:
                bullet_lines.append(f"- 보유 문서 형식: {', '.join(format_hint)}")

        if not bullet_lines:
            return None

        source_line = f"- {source} (CSV)" if source else "- 조직 메타데이터(org_registry)"
        answer = (
            f"{org_name} 기본 정보입니다.\n\n"
            f"{chr(10).join(bullet_lines)}\n\n"
            f"[출처]\n{source_line}"
        )
        payload = {
            "answer": self._format_answer_for_readability(answer),
            "found": True,
            "source_type": "csv" if source else "pdf",
            "answer_mode": "extractive",
            "slot_fill_rate": 0.95,
            "evidence_count": 1,
            "confidence": 0.9,
            "evidence": [
                {
                    "source": source or "org_registry",
                    "page": None,
                    "text": bullet_lines[0],
                    "slot": "key_points",
                    "score": 0.9,
                }
            ],
        }
        self.conversation.add_exchange(query, payload.get("answer", ""), intent)
        return payload

    def _register_csv_orgs(self, markdowns: list) -> None:
        """CSV 기관 정보만 등록합니다."""
        for md_data in markdowns:
            org_info = self._create_org_info_from_markdown(md_data)
            self.vector_store.register_org(org_info)

    @staticmethod
    def _convert_budget_unit_to_won(value_text: str, unit_text: str) -> int:
        """금액 문자열(+단위)을 원 단위 정수로 변환합니다."""
        cleaned = str(value_text or "").replace(",", "").strip()
        if not cleaned:
            return 0
        try:
            base = float(cleaned)
        except Exception:
            return 0

        unit = str(unit_text or "").strip().lower()
        if unit in {"억원", "억"}:
            return int(base * 100_000_000)
        if unit in {"백만원"}:
            return int(base * 1_000_000)
        if unit in {"만원", "만"}:
            return int(base * 10_000)
        if unit in {"천원"}:
            return int(base * 1_000)
        return int(base)

    def _extract_budget_candidates_from_line(self, line: str) -> list[int]:
        """문장 한 줄에서 사업비 후보 금액(원 단위)을 추출합니다."""
        if not line:
            return []
        lowered = unicodedata.normalize("NFKC", line.lower())
        budget_keywords = ["사업비", "총사업비", "사업 예산", "예산", "소요예산", "추정가격", "계약금액", "사업 금액"]
        if not any(token in lowered for token in budget_keywords):
            return []

        candidates: list[int] = []
        labeled_pattern = re.compile(
            r"(?:총\s*사업비|사업\s*예산|사업비|예산|소요예산|추정가격|계약금액|사업\s*금액|금액)\s*[:：]?\s*(?:금)?\s*\(?\s*([\d][\d,]*(?:\.\d+)?)\s*(억원|억|백만원|천원|만원|만|원)?",
            re.IGNORECASE,
        )
        for value_text, unit_text in labeled_pattern.findall(line):
            amount = self._convert_budget_unit_to_won(value_text, unit_text)
            if amount >= 1_000_000:
                candidates.append(amount)

        if candidates:
            return candidates

        plain_pattern = re.compile(
            r"(?:금\s*)?([\d][\d,]*(?:\.\d+)?)\s*(억원|억|백만원|천원|만원|만|원)",
            re.IGNORECASE,
        )
        for value_text, unit_text in plain_pattern.findall(line):
            amount = self._convert_budget_unit_to_won(value_text, unit_text)
            if amount >= 1_000_000:
                candidates.append(amount)
        return candidates

    def _ensure_chunk_budget_cache(self) -> None:
        """기존 chunk 문서 메타/본문에서 기관별 사업비 캐시를 구축합니다."""
        if self._chunk_budget_cache_ready:
            return

        cache: dict[str, dict[str, Any]] = {}
        try:
            payload = self.vector_store.collection.get(include=["metadatas", "documents"])
        except Exception:
            self._chunk_budget_cache = {}
            self._chunk_budget_cache_ready = True
            return

        metadatas = payload.get("metadatas", []) or []
        documents = payload.get("documents", []) or []

        for meta, doc in zip(metadatas, documents):
            md = meta if isinstance(meta, dict) else {}
            text = str(doc or "")
            if not md or not text:
                continue

            org_name = self._extract_metadata_org(md)
            if not org_name:
                continue

            source = self._extract_metadata_source(md) or "Unknown"
            page = self._extract_metadata_page(md)
            project_name = str(md.get("project_name") or md.get("document_title") or "").strip()

            best_amount = 0
            best_line = ""
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if len(line) < 4:
                    continue
                amounts = self._extract_budget_candidates_from_line(line)
                if not amounts:
                    continue
                local_max = max(amounts)
                if local_max > best_amount:
                    best_amount = local_max
                    best_line = line[:240]

            if best_amount <= 0:
                continue

            existing = cache.get(org_name)
            if existing and int(existing.get("amount_numeric", 0) or 0) >= best_amount:
                continue

            cache[org_name] = {
                "org_name": org_name,
                "amount_numeric": int(best_amount),
                "source": source,
                "page": page,
                "line": best_line or f"사업비 {best_amount:,}원",
                "project_name": project_name,
            }

        self._chunk_budget_cache = cache
        self._chunk_budget_cache_ready = True

        if cache:
            from src.graph.state import OrgInfo

            for org_name, item in cache.items():
                amount_numeric = int(item.get("amount_numeric", 0) or 0)
                if amount_numeric <= 0:
                    continue
                org_info = OrgInfo(
                    name=org_name,
                    amount=f"{amount_numeric:,}원",
                    project_name=str(item.get("project_name", "")).strip(),
                )
                org_info.amount_numeric = amount_numeric
                self.vector_store.register_org(org_info)

    def _find_chunk_budget_for_org(self, org_name: str) -> dict[str, Any] | None:
        """기관명으로 chunk 기반 사업비 캐시를 조회합니다."""
        if not org_name:
            return None
        self._ensure_chunk_budget_cache()
        if not self._chunk_budget_cache:
            return None

        matched: list[dict[str, Any]] = []
        for cached_org, item in self._chunk_budget_cache.items():
            if self._org_names_loosely_match(cached_org, org_name):
                matched.append(item)
        if not matched:
            return None
        matched.sort(key=lambda x: int(x.get("amount_numeric", 0) or 0), reverse=True)
        return matched[0]

    def _try_chunk_budget_short_circuit(
        self,
        query: str,
        intent: QueryIntent,
        org_name: str,
    ) -> dict[str, Any] | None:
        """CSV 단축 경로 미적중 시 chunk 기반 사업비 응답을 시도합니다."""
        if not org_name or not self._is_budget_query(query):
            return None

        matched = self._find_chunk_budget_for_org(org_name)
        if not matched:
            return None

        amount_numeric = int(matched.get("amount_numeric", 0) or 0)
        if amount_numeric <= 0:
            return None

        source = str(matched.get("source", "Unknown")).strip() or "Unknown"
        page = matched.get("page")
        page_suffix = f" p.{page}" if page else ""
        evidence_line = str(matched.get("line", "")).strip() or f"사업비: {amount_numeric:,}원"
        org_label = str(matched.get("org_name", org_name)).strip() or org_name
        source_type = "pdf" if source.lower().endswith(".pdf") else "hwp"

        answer = (
            f"{org_label} 문서 기준 사업비는 {amount_numeric:,}원입니다.\n\n"
            f"근거 요약\n{evidence_line}\n"
            f"출처\n{source}{page_suffix}"
        )
        payload = {
            "answer": self._format_answer_for_readability(answer),
            "found": True,
            "source_type": source_type,
            "answer_mode": "extractive",
            "slot_fill_rate": 1.0,
            "evidence_count": 1,
            "confidence": 0.9,
            "evidence": [
                {
                    "source": source,
                    "page": page,
                    "text": evidence_line,
                    "slot": "budget",
                    "score": 0.9,
                }
            ],
            "chunk_budget_short_circuit": True,
        }
        self.conversation.add_exchange(query, payload["answer"], intent)
        return payload

    @staticmethod
    def _needs_org_fact_scan(query: str) -> bool:
        """기관 스코프 전체 문서 스캔이 필요한 정밀 사실 질의인지 판별합니다."""
        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        if not normalized:
            return False
        markers = [
            "cpu", "xeon", "ghz", "core", "hci",
            "협상", "적격", "배점", "기술능력", "평가점수", "85%",
            "복구", "장애", "시간 이내",
            "정보보안교육", "보안교육", "월 1회", "월1회",
            "가이드", "guideline", "guide",
            "최소규격", "최대규격", "치수", "가로", "세로", "mm",
            "추진 목표", "추진목표", "사업목적", "목적은",
        ]
        return any(marker in normalized for marker in markers)

    def _collect_org_document_candidates(
        self,
        query: str,
        org_name: str,
        max_docs: int = 120,
    ) -> list[dict[str, Any]]:
        """기관명으로 묶인 청크를 키워드 기준으로 선별합니다."""
        if not org_name:
            return []

        try:
            payload = self.vector_store.collection.get(
                where={"org": org_name},
                include=["metadatas", "documents"],
            )
        except Exception:
            payload = {"metadatas": [], "documents": []}

        metadatas = payload.get("metadatas", []) or []
        documents = payload.get("documents", []) or []
        if not documents:
            # org 메타키가 비어 있는 컬렉션을 위해 검색 결과 기반으로 후보를 복원한다.
            try:
                backfill = self.vector_store.search(
                    f"{org_name} {query}",
                    top_k=max(max_docs * 2, 80),
                    mode="dynamic",
                    hybrid_alpha=0.6,
                    dynamic_hard_threshold=2,
                )
            except Exception:
                backfill = []
            backfill_norm = self._normalize_retrieval_results(backfill)
            backfill_filtered = self._apply_result_filters(backfill_norm, org_name=org_name, doc_types=None)
            for item in backfill_filtered[: max_docs]:
                md = item.get("metadata", {}) or {}
                metadatas.append(md)
                documents.append(item.get("text", ""))
        if not documents:
            return []

        keywords = self._extract_query_keywords(query, max_keywords=14)
        focus_terms = self._extract_focus_terms_for_fact(query, max_terms=8)
        scored: list[tuple[float, dict[str, Any]]] = []

        for meta, doc in zip(metadatas, documents):
            text = str(doc or "").strip()
            if len(text) < 12:
                continue
            md = meta if isinstance(meta, dict) else {}
            text_key = self._normalize_text_for_match(text[:2400])
            score = 0.0
            for keyword in keywords:
                if keyword and keyword in text_key:
                    score += 1.0
            lowered_text = unicodedata.normalize("NFKC", text.lower())
            for term in focus_terms:
                if term and term in lowered_text:
                    score += 1.2
            if re.search(r"\d", text):
                score += 0.2
            if "표" in lowered_text or text.count("|") >= 2:
                score += 0.2
            source = str(md.get("source") or md.get("source_file") or md.get("filename") or "").strip()
            page = md.get("page")
            scored.append(
                (
                    score,
                    {
                        "text": text,
                        "metadata": {
                            **md,
                            "org": org_name,
                            "source": source,
                            "page": page,
                        },
                        "score": score,
                    },
                )
            )

        if not scored:
            return []
        scored.sort(key=lambda item: (item[0], len(item[1].get("text", ""))), reverse=True)
        top = [item for _, item in scored[: max_docs]]
        return top

    def _try_org_document_scan_short_circuit(
        self,
        query: str,
        intent: QueryIntent,
        org_name: str,
    ) -> dict[str, Any] | None:
        """기관 단일 질의의 정밀 사실 질문은 기관 전 청크를 스캔해 즉답을 시도합니다."""
        if not org_name or not self._needs_org_fact_scan(query):
            return None
        if self._is_comparison_query(query):
            return None

        candidates = self._collect_org_document_candidates(query, org_name=org_name, max_docs=140)
        if not candidates:
            return None

        direct_fact = self._extract_direct_fact_from_results(query, candidates, target_org=org_name)
        if not direct_fact:
            return None

        fact_answer, evidence, source_line = direct_fact
        detail = "\n".join([f"- {line}" for line in evidence[:3]])
        answer = (
            f"{org_name} 문서 기준 {fact_answer}\n\n"
            f"[근거]\n{detail}\n\n"
            f"[출처]\n- {source_line}"
        )
        payload = {
            "answer": self._format_answer_for_readability(answer),
            "found": True,
            "source_type": "hwp",
            "answer_mode": "extractive",
            "slot_fill_rate": 1.0,
            "evidence_count": min(len(evidence), 3),
            "confidence": 0.92,
            "evidence": [
                {
                    "source": source_line,
                    "page": None,
                    "text": line,
                    "slot": "value",
                    "score": 0.9,
                }
                for line in evidence[:3]
            ],
            "org_doc_scan_short_circuit": True,
        }
        self.conversation.add_exchange(query, payload["answer"], intent)
        return payload

    def _add_csv_chunks(self, markdowns: list) -> None:
        """CSV 청크를 벡터 DB에 추가합니다."""
        chunks = []
        for md_data in markdowns:
            org_info = self._create_org_info_from_markdown(md_data)
            self.vector_store.register_org(org_info)

            sections = self.vector_store.csv_converter.split_markdown_sections(md_data.markdown)
            valid_sections = self.vector_store.csv_converter.filter_valid_sections(sections)

            for section in valid_sections:
                section_text = f"## {section}"
                base_meta = dict(md_data.metadata or {})
                base_meta["source_origin"] = "csv"
                if section.strip().startswith("원본 문서 내용"):
                    sub_chunks = self._split_text_for_retrieval(section_text, max_chars=1600, overlap=180)
                    for idx, sub in enumerate(sub_chunks, 1):
                        chunks.append({
                            "text": sub,
                            "source": md_data.filename or 'csv',
                            "org": md_data.org_name,
                            "type": "csv",
                            "section": f"원본 문서 내용-{idx}",
                            "metadata": base_meta,
                        })
                    continue

                chunks.append({
                    "text": section_text,
                    "source": md_data.filename or 'csv',
                    "org": md_data.org_name,
                    "type": "csv",
                    "section": section.split("\n", 1)[0].strip(),
                    "metadata": base_meta,
                })

        if chunks:
            self.vector_store.add_documents(chunks)
            print(f"  벡터 DB에 {len(chunks)}개 청크 추가")

    def _hydrate_org_registry_from_existing_chunks(self) -> None:
        """기존 컬렉션 메타데이터를 기반으로 기관 레지스트리를 보강합니다."""
        try:
            org_stats = self._collect_org_stats_compat()
        except Exception:
            return
        if not org_stats:
            return

        from src.graph.state import OrgInfo

        for org_name, flags in org_stats.items():
            existing = self.vector_store.org_registry.get(org_name)
            if existing:
                existing.has_pdf = existing.has_pdf or bool(flags.get("has_pdf"))
                existing.has_hwp = existing.has_hwp or bool(flags.get("has_hwp"))
                continue
            org_info = OrgInfo(
                name=org_name,
                has_pdf=bool(flags.get("has_pdf")),
                has_hwp=bool(flags.get("has_hwp")),
            )
            self.vector_store.register_org(org_info)

    @staticmethod
    def _split_text_for_retrieval(text: str, max_chars: int = 1600, overlap: int = 180) -> list[str]:
        """긴 텍스트를 검색 친화적인 크기로 분할합니다."""
        cleaned = text.strip()
        if len(cleaned) <= max_chars:
            return [cleaned]

        chunks: list[str] = []
        start = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + max_chars)
            chunk = cleaned[start:end]
            chunks.append(chunk)
            if end == len(cleaned):
                break
            start = max(0, end - overlap)
        return chunks

    def _persist_unified_markdown(
        self,
        file_path: Path,
        org_name: str,
        page_chunks: list[dict[str, Any]],
        csv_meta: dict[str, Any],
    ) -> None:
        """CSV 메타데이터 + 원본 추출 결과를 통합 마크다운으로 저장합니다."""
        try:
            safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in file_path.stem)
            out_path = self.unified_markdown_dir / f"{safe_name}.md"

            lines: list[str] = [f"# {org_name}\n"]
            lines.append("## CSV 메타데이터")
            if csv_meta:
                for k, v in csv_meta.items():
                    if v in ("", None):
                        continue
                    lines.append(f"- **{k}**: {v}")
            else:
                lines.append("- 매칭된 CSV 메타데이터 없음")
            lines.append("")

            lines.append("## 원본 문서 정보")
            lines.append(f"- **source_file**: {file_path.name}")
            lines.append(f"- **source_ext**: {file_path.suffix.lower()}")
            lines.append(f"- **extracted_pages**: {len(page_chunks)}")
            lines.append("")

            lines.append("## 원본 문서 추출 내용")
            if not page_chunks:
                lines.append("원본 문서에서 텍스트를 추출하지 못했습니다.")
                lines.append("")
            else:
                for page in page_chunks:
                    page_num = page.get("page", "?")
                    table_count = int(page.get("table_count", 0) or 0)
                    content = (page.get("content") or "").strip()
                    lines.append(f"### 페이지 {page_num} (표 {table_count}개)")
                    if content:
                        lines.append(content)
                    lines.append("")

            out_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            # 저장 실패는 검색 흐름을 막지 않도록 무시
            return

    def _create_org_info_from_markdown(self, md_data) -> Any:
        """마크다운 데이터에서 기관 정보를 생성합니다."""
        from src.graph.state import OrgInfo
        meta = dict(getattr(md_data, "metadata", {}) or {})
        org_info = OrgInfo(
            name=md_data.org_name,
            amount=md_data.amount,
            project_name=md_data.project_name,
            summary=md_data.summary,
            open_date=str(meta.get("open_date", "")),
            file_format=md_data.file_format
        )
        org_info.amount_numeric = parse_amount(md_data.amount)
        return org_info

    def _list_document_files(self, announce_include: bool = False) -> list[Path]:
        """인덱싱 대상 문서 목록을 반환합니다."""
        supported_extensions = ['.pdf', '.hwp', '.hwpx']
        all_files: list[Path] = []
        for ext in supported_extensions:
            all_files.extend(list(self.data_dir.glob(f'*{ext}')))

        include_pattern = os.environ.get("DOC_INCLUDE_PATTERN", "").strip()
        if include_pattern:
            try:
                include_re = re.compile(include_pattern, flags=re.IGNORECASE)
                filtered_files = [path for path in all_files if include_re.search(path.name)]
                if filtered_files:
                    all_files = filtered_files
                    if announce_include:
                        print(f"📌 DOC_INCLUDE_PATTERN 적용: {len(all_files)}개 문서")
            except re.error:
                if announce_include:
                    print(f"⚠️ DOC_INCLUDE_PATTERN 정규식 오류: {include_pattern}")

        return sorted(all_files, key=lambda path: path.name)

    @staticmethod
    def _build_file_signature(file_path: Path) -> dict[str, int]:
        """파일 변경 추적용 서명을 생성합니다."""
        try:
            stat = file_path.stat()
        except OSError:
            return {}
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    def _load_failed_sources_registry(self) -> dict[str, dict[str, Any]]:
        """영구 실패 문서 레지스트리를 로드합니다."""
        path = self.failed_sources_registry_path
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            print(f"⚠️ 실패 레지스트리 로드 실패: {path}")
            return {}

        entries: dict[str, Any]
        if isinstance(payload, dict) and isinstance(payload.get("entries"), dict):
            entries = payload.get("entries", {})
        elif isinstance(payload, dict):
            entries = payload
        else:
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for source, raw in entries.items():
            if not isinstance(source, str):
                continue
            item = raw if isinstance(raw, dict) else {}
            signature = item.get("signature")
            normalized_signature = (
                signature if isinstance(signature, dict) else {}
            )
            fail_count_raw = item.get("fail_count", 1)
            try:
                fail_count = max(1, int(fail_count_raw))
            except (TypeError, ValueError):
                fail_count = 1
            normalized[source] = {
                "reason": str(item.get("reason", "")).strip(),
                "first_failed_at": str(item.get("first_failed_at", "")).strip(),
                "last_failed_at": str(item.get("last_failed_at", "")).strip(),
                "fail_count": fail_count,
                "signature": {
                    "size": int(normalized_signature.get("size", 0) or 0),
                    "mtime_ns": int(normalized_signature.get("mtime_ns", 0) or 0),
                },
            }
        return normalized

    def _save_failed_sources_registry(self) -> None:
        """영구 실패 문서 레지스트리를 저장합니다."""
        try:
            self.failed_sources_registry_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "entries": self.failed_sources_registry,
            }
            self.failed_sources_registry_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"⚠️ 실패 레지스트리 저장 실패: {exc}")

    def _is_source_in_failed_registry(self, file_path: Path) -> bool:
        """해당 파일이 현재 유효한 실패 목록에 있는지 확인합니다."""
        entry = self.failed_sources_registry.get(file_path.name)
        if not entry:
            return False
        saved_signature = entry.get("signature", {}) or {}
        current_signature = self._build_file_signature(file_path)
        if not saved_signature or not current_signature:
            return True
        if saved_signature == current_signature:
            return True

        # 파일이 갱신되면 실패 목록에서 자동 해제하고 재시도합니다.
        self.failed_sources_registry.pop(file_path.name, None)
        self._save_failed_sources_registry()
        print(f"  🔁 {file_path.name}: 파일 변경 감지, 실패 목록 해제")
        return False

    def _mark_source_failed(self, file_path: Path, reason: str) -> None:
        """문서 변환 실패를 영구 실패 목록에 기록합니다."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        current = self.failed_sources_registry.get(file_path.name, {})
        self.failed_sources_registry[file_path.name] = {
            "reason": reason.strip()[:300],
            "first_failed_at": current.get("first_failed_at") or now,
            "last_failed_at": now,
            "fail_count": int(current.get("fail_count", 0) or 0) + 1,
            "signature": self._build_file_signature(file_path),
        }
        self._save_failed_sources_registry()

    def _clear_source_failed(self, file_path: Path) -> None:
        """문서가 정상 처리되면 실패 목록에서 제거합니다."""
        if file_path.name in self.failed_sources_registry:
            self.failed_sources_registry.pop(file_path.name, None)
            self._save_failed_sources_registry()

    def _has_unindexed_document_files(self) -> bool:
        """미인덱싱 문서가 존재하는지 확인합니다."""
        all_files = self._list_document_files()
        if not all_files:
            return False
        indexed_sources = self._get_indexed_sources_compat(doc_types=["pdf", "hwp"])
        for path in all_files:
            if path.name in indexed_sources:
                continue
            if self._is_source_in_failed_registry(path):
                continue
            return True
        return False

    def _load_document_files(self, force_reload: bool = False) -> None:
        """PDF/HWP 파일을 로드하고 변환합니다."""
        all_files = self._list_document_files(announce_include=True)

        if not all_files:
            print("⚠️ PDF/HWP 파일을 찾을 수 없습니다.")
            return

        print(f"\n📄 문서 파일 처리 중: {len(all_files)}개")

        from src.parsers.pdf_loader import PDFMarkdownConverter
        from src.parsers.hwp_loader import HWPMarkdownConverter

        indexed_sources = set()
        if not force_reload:
            indexed_sources = self._get_indexed_sources_compat(doc_types=["pdf", "hwp"])

        added_chunk_count = 0
        skipped_count = 0
        failed_skip_count = 0
        failed_mark_count = 0

        for file_path in all_files:
            try:
                org_name = PDFMarkdownConverter.extract_org_name(file_path.name)
                is_pdf = file_path.suffix.lower() == '.pdf'
                csv_meta = self._lookup_csv_metadata(file_path, org_name)

                from src.graph.state import OrgInfo
                org_info = OrgInfo(
                    name=org_name,
                    project_name=str(csv_meta.get("project_name", "")),
                    summary=str(csv_meta.get("summary", "")),
                    file_format='PDF' if is_pdf else 'HWP',
                    has_pdf=is_pdf,
                    has_hwp=not is_pdf
                )
                csv_amount = parse_amount(str(csv_meta.get("amount", "")))
                if csv_amount > 0:
                    org_info.amount = str(csv_meta.get("amount", ""))
                    org_info.amount_numeric = csv_amount
                self.vector_store.register_org(org_info)

                if not force_reload and file_path.name in indexed_sources:
                    print(f"  ℹ️ {file_path.name}: {org_name} (이미 인덱싱됨)")
                    skipped_count += 1
                    continue

                if not force_reload and self._is_source_in_failed_registry(file_path):
                    fail_reason = str(
                        (self.failed_sources_registry.get(file_path.name) or {}).get("reason", "")
                    ).strip()
                    if fail_reason:
                        print(f"  ⏭️ {file_path.name}: {org_name} (영구 실패 목록: {fail_reason[:80]})")
                    else:
                        print(f"  ⏭️ {file_path.name}: {org_name} (영구 실패 목록)")
                    skipped_count += 1
                    failed_skip_count += 1
                    continue

                print(f"  🔄 {file_path.name}: {org_name} 변환 중...", end="", flush=True)

                if is_pdf:
                    page_chunks = PDFMarkdownConverter().extract_pages(file_path, include_tables=True)
                else:
                    page_chunks = HWPMarkdownConverter().extract_pages(file_path)

                if not page_chunks:
                    print(" ⚠️ 추출 실패")
                    self._mark_source_failed(file_path, "텍스트/페이지 추출 결과 없음")
                    failed_mark_count += 1
                    continue

                full_text = "\n\n".join(chunk.get("content", "") for chunk in page_chunks)
                amount_str, amount_int = extract_amount_from_text(full_text)

                if amount_int > 0:
                    updated_info = OrgInfo(
                        name=org_name,
                        amount=amount_str,
                        project_name=str(csv_meta.get("project_name", "")),
                        summary=str(csv_meta.get("summary", "")),
                        file_format='PDF' if is_pdf else 'HWP',
                        has_pdf=is_pdf,
                        has_hwp=not is_pdf
                    )
                    updated_info.amount_numeric = amount_int
                    self.vector_store.register_org(updated_info)
                    print(f" 💰{amount_str}", end="", flush=True)

                self._persist_unified_markdown(
                    file_path=file_path,
                    org_name=org_name,
                    page_chunks=page_chunks,
                    csv_meta=csv_meta,
                )

                valid_count = 0
                file_chunks = []
                for chunk in page_chunks:
                    chunk_text = (chunk.get("content") or "").strip()
                    if len(chunk_text) < MIN_SECTION_LENGTH:
                        continue
                    page_num = chunk.get("page")
                    table_count = int(chunk.get("table_count", 0) or 0)
                    file_chunks.append({
                        "text": f"## 페이지 {page_num}\n{chunk_text}",
                        "source": file_path.name,
                        "org": org_name,
                        "type": "pdf" if is_pdf else "hwp",
                        "page": int(page_num) if page_num is not None else None,
                        "table_count": table_count,
                        "has_table": table_count > 0,
                        "metadata": {
                            **csv_meta,
                            "source_origin": "original",
                            "original_ext": file_path.suffix.lower().lstrip("."),
                        },
                    })
                    valid_count += 1

                if file_chunks:
                    self.vector_store.add_documents(file_chunks)
                    indexed_sources.add(file_path.name)
                    added_chunk_count += len(file_chunks)
                    self._clear_source_failed(file_path)

                print(f" ✅ ({valid_count} 페이지 청크)")

            except Exception as e:
                print(f"  ❌ {file_path.name}: {e}")
                self._mark_source_failed(file_path, str(e) or e.__class__.__name__)
                failed_mark_count += 1

        if added_chunk_count:
            print(f"  벡터 DB에 {added_chunk_count}개 청크 추가")
        if failed_skip_count:
            print(f"  ⏭️ 영구 실패 목록 스킵: {failed_skip_count}개")
        if failed_mark_count:
            print(f"  🗂️ 신규 실패 기록: {failed_mark_count}개 ({self.failed_sources_registry_path})")
        elif skipped_count == len(all_files):
            print("  ℹ️ 모든 문서가 이미 인덱싱되어 있습니다.")
        elif force_reload:
            print("  ⚠️ 처리할 청크가 없습니다.")

    def answer(self, query: str, top_k: int = 24) -> dict[str, Any]:
        """질문에 답변합니다."""
        answer_started = time.perf_counter()
        perf_stats: dict[str, float | int | bool] = {
            "llm_calls": 0,
            "hybrid_calls": 0,
            "keyword_calls": 0,
            "csv_short_circuit_hit": 0,
            "retrieval_elapsed": 0.0,
            "generation_elapsed": 0.0,
            "hybrid_budget_remaining": RETRIEVAL_MAX_HYBRID_CALLS,
            "budget_exhausted": False,
        }
        query = query.strip()
        if not query:
            return {
                "answer": "질문을 입력해 주세요.",
                "found": False,
                "answer_mode": "generative",
                "slot_fill_rate": 0.0,
                "evidence_count": 0,
                "confidence": 0.0,
                "evidence": [],
            }

        # 1) 질문 의도 파악
        intent = self.query_parser.parse(query)
        if intent.org_name:
            intent.org_name = self.vector_store.normalize_org_name(intent.org_name)
        if getattr(self.query_parser, "last_parse_used_llm", False):
            perf_stats["llm_calls"] = int(perf_stats["llm_calls"]) + 1
        normalized_query = unicodedata.normalize("NFKC", query.lower())
        explicit_org_candidates = self._extract_org_names_from_query(query, limit=2, allow_project_fallback=False)
        fact_style_markers = [
            "얼마", "언제", "기한", "마감", "사양", "cpu", "용량", "치수", "규격",
            "가로", "세로", "몇", "누가", "책임", "부담", "요구사항", "기준",
        ]
        is_fact_style_query = (
            self._is_budget_query(query)
            or self._is_precision_fact_query(query)
            or any(marker in normalized_query for marker in fact_style_markers)
        )
        # 명시 기관/사실형 질문은 랭킹·카테고리 단축 처리에서 제외한다.
        if intent.query_type in {"ranking", "category"} and (explicit_org_candidates or is_fact_style_query):
            intent.query_type = "search"
            intent.confidence = min(intent.confidence, 0.7)
        if intent.query_type == "ranking":
            return self._handle_ranking_query(intent)
        if intent.query_type == "category":
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return self._handle_category_query(intent)

        # 2) 후속질문 컨텍스트 반영
        follow_up_ctx = self.conversation.get_follow_up_context(query)
        explicit_orgs_raw = self._extract_org_names_from_query(query)
        direct_orgs_raw = self._extract_org_names_from_query(query, allow_project_fallback=False)
        explicit_orgs: list[str] = []
        for cand in explicit_orgs_raw:
            resolved = self._resolve_known_org_name(cand) or cand
            self._append_unique_org_name(explicit_orgs, resolved)
        direct_explicit_orgs: list[str] = []
        for cand in direct_orgs_raw:
            resolved = self._resolve_known_org_name(cand) or cand
            self._append_unique_org_name(direct_explicit_orgs, resolved)
        explicit_org = explicit_orgs[0] if explicit_orgs else None
        implicit_follow_up = (
            follow_up_ctx["has_previous"]
            and bool(follow_up_ctx["last_org"])
            and not explicit_orgs
            and self._is_implicit_follow_up_query(query)
        )
        if (follow_up_ctx["is_follow_up"] or implicit_follow_up) and follow_up_ctx["last_org"] and not explicit_orgs:
            org_name = follow_up_ctx["last_org"]
        else:
            org_name = explicit_org or intent.org_name or ""
        if not org_name and direct_explicit_orgs:
            org_name = direct_explicit_orgs[0]
        retrieval_query = query
        if org_name and not explicit_orgs and (follow_up_ctx["is_follow_up"] or implicit_follow_up):
            retrieval_query = f"{org_name} {query}"
        question_plan = self.question_planner.build(query, target_org=org_name)
        is_single_org_budget_query = self._is_budget_query(query) and len(direct_explicit_orgs) <= 1
        is_single_org_non_comparison_query = (
            bool(org_name)
            and len(direct_explicit_orgs) <= 1
            and not self._is_comparison_query(query)
        )
        comparison_like_query = (
            question_plan.query_kind in {"multi_doc", "comparison"}
            or question_plan.is_comparison
            or self._is_comparison_query(query)
            or len(direct_explicit_orgs) >= 2
        )
        if is_single_org_budget_query or is_single_org_non_comparison_query:
            comparison_like_query = False
            question_plan.is_comparison = False
            if question_plan.query_kind in {"multi_doc", "comparison"}:
                question_plan.query_kind = "fact_numeric" if is_single_org_budget_query else "single_doc"
        multi_target_query = comparison_like_query
        coverage_targets = self._resolve_query_target_orgs(
            query,
            explicit_orgs=explicit_orgs,
            min_targets=2 if multi_target_query else 1,
        )
        if not comparison_like_query and coverage_targets:
            coverage_targets = coverage_targets[:1]
        # 비교/다문서 질의는 단일 기관 필터를 해제해 양쪽 문서를 모두 검색한다.
        if multi_target_query and len(coverage_targets) >= 2:
            org_name = ""
        intent.org_name = org_name
        is_single_org_query = bool(org_name) and question_plan.query_kind not in {"multi_doc", "comparison"}

        if is_single_org_query and org_name not in self.vector_store.org_registry and direct_explicit_orgs:
            for candidate in direct_explicit_orgs:
                resolved = self._resolve_known_org_name(candidate) or candidate
                if resolved in self.vector_store.org_registry:
                    org_name = resolved
                    intent.org_name = resolved
                    break
            is_single_org_query = bool(org_name) and question_plan.query_kind not in {"multi_doc", "comparison"}

        if is_single_org_query and org_name not in self.vector_store.org_registry:
            resolved_org = self._resolve_known_org_name(org_name)
            if resolved_org:
                org_name = resolved_org
                intent.org_name = resolved_org
            elif intent.query_type == "org":
                # "OO시스템/OO사업"은 기관명이 아니라 프로젝트명인 경우가 많으므로 전역 검색으로 전환한다.
                if self._looks_like_project_phrase(org_name) and not direct_explicit_orgs:
                    org_name = ""
                    intent.org_name = ""
                    is_single_org_query = False
                else:
                    self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
                    return self._build_org_not_found_payload(org_name)

        csv_payload = self._try_csv_short_circuit(query, intent, org_name=org_name)
        if csv_payload:
            perf_stats["csv_short_circuit_hit"] = int(perf_stats.get("csv_short_circuit_hit", 0)) + 1
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return csv_payload
        org_overview_payload = self._try_org_overview_short_circuit(query, intent, org_name=org_name)
        if org_overview_payload:
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return org_overview_payload
        chunk_budget_payload = self._try_chunk_budget_short_circuit(query, intent, org_name=org_name)
        if chunk_budget_payload:
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return chunk_budget_payload
        org_scan_payload = self._try_org_document_scan_short_circuit(query, intent, org_name=org_name)
        if org_scan_payload:
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return org_scan_payload

        # 3) 검색 (기관 지정 질의는 원본 문서 우선 + 비교 질의는 더 넓게 검색)
        retrieval_started = time.perf_counter()
        is_comparison_query = self._is_comparison_query(query)
        precision_fact_query = self._is_precision_fact_query(query)
        accuracy_mode = self._is_accuracy_mode_enabled()
        prefer_original = self._needs_original_priority(query) or bool(org_name) or is_comparison_query
        retrieval_top_k = max(top_k, 30) if is_comparison_query else top_k
        if question_plan.query_kind in {"multi_doc", "comparison"}:
            retrieval_top_k = max(retrieval_top_k, 30)
        if question_plan.query_kind in {"fact_numeric", "deadline", "owner"}:
            retrieval_top_k = max(retrieval_top_k, 22)
        if accuracy_mode and precision_fact_query:
            retrieval_top_k = max(retrieval_top_k, 36)
        if accuracy_mode and comparison_like_query:
            retrieval_top_k = max(retrieval_top_k, 34)
        if org_name and org_name in self.vector_store.org_registry:
            retrieval = self._retrieve_results(
                retrieval_query,
                org_name=org_name,
                top_k=retrieval_top_k,
                prefer_original=prefer_original,
                target_orgs=coverage_targets if comparison_like_query and len(coverage_targets) >= 2 else None,
                perf_stats=perf_stats,
            )
            if self._should_fallback_to_original(query, retrieval):
                original_only = self._retrieve_results(
                    retrieval_query,
                    org_name=org_name,
                    top_k=max(retrieval_top_k, 30),
                    prefer_original=True,
                    doc_types=["pdf", "hwp"],
                    perf_stats=perf_stats,
                )
                retrieval = self._merge_results(retrieval, original_only, top_k=max(retrieval_top_k, 30))
            if retrieval:
                perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
                self.vector_store.last_search_results = retrieval
                payload = self._answer_with_results(
                    query,
                    retrieval,
                    intent,
                    question_plan,
                    perf_stats=perf_stats,
                    comparison_targets=coverage_targets if comparison_like_query else None,
                )
                self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
                return payload
            if is_single_org_query:
                # 기관 스코프 검색 실패 시 전역 검색 후 기관 필터링으로 1회 보완한다.
                global_retry = self._retrieve_results(
                    retrieval_query,
                    org_name=None,
                    top_k=max(retrieval_top_k, 36),
                    prefer_original=True,
                    perf_stats=perf_stats,
                )
                narrowed_retry = self._filter_results_by_org(global_retry, org_name)
                if not narrowed_retry:
                    org_query = f"{org_name} {query}"
                    global_retry_org = self._retrieve_results(
                        org_query,
                        org_name=None,
                        top_k=max(retrieval_top_k, 48),
                        prefer_original=True,
                        perf_stats=perf_stats,
                    )
                    narrowed_retry = self._filter_results_by_org(global_retry_org, org_name)
                if narrowed_retry:
                    perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
                    self.vector_store.last_search_results = narrowed_retry
                    payload = self._answer_with_results(
                        query,
                        narrowed_retry,
                        intent,
                        question_plan,
                        perf_stats=perf_stats,
                        comparison_targets=coverage_targets if comparison_like_query else None,
                    )
                    self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
                    return payload
                perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
                self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
                return self._build_org_not_found_payload(org_name)

        retrieval = self._retrieve_results(
            retrieval_query,
            org_name=None,
            top_k=retrieval_top_k,
            prefer_original=prefer_original,
            target_orgs=coverage_targets if comparison_like_query and len(coverage_targets) >= 2 else None,
            perf_stats=perf_stats,
        )
        if comparison_like_query and len(coverage_targets) >= 2:
            retrieval = self._ensure_org_coverage(
                query,
                retrieval,
                explicit_orgs=coverage_targets[:3],
                top_k=max(retrieval_top_k + 12, 28),
                prefer_original=prefer_original,
                perf_stats=perf_stats,
            )
        if self._should_fallback_to_original(query, retrieval):
            original_only = self._retrieve_results(
                retrieval_query,
                org_name=None,
                top_k=max(retrieval_top_k, 30),
                prefer_original=True,
                doc_types=["pdf", "hwp"],
                perf_stats=perf_stats,
            )
            retrieval = self._merge_results(retrieval, original_only, top_k=max(retrieval_top_k, 30))
        if is_single_org_query:
            retrieval = self._filter_results_by_org(retrieval, org_name)
            if not retrieval:
                perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
                self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
                return self._build_org_not_found_payload(org_name)
        if retrieval:
            perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
            self.vector_store.last_search_results = retrieval
            payload = self._answer_with_results(
                query,
                retrieval,
                intent,
                question_plan,
                perf_stats=perf_stats,
                comparison_targets=coverage_targets if comparison_like_query else None,
            )
            self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
            return payload

        perf_stats["retrieval_elapsed"] = time.perf_counter() - retrieval_started
        self._log_perf_stats(query, perf_stats, total_elapsed=time.perf_counter() - answer_started)
        return {
            "answer": "관련 정보를 찾을 수 없습니다.",
            "found": False,
            "answer_mode": "extractive",
            "slot_fill_rate": 0.0,
            "evidence_count": 0,
            "confidence": 0.0,
            "evidence": [],
        }

    @staticmethod
    def _log_perf_stats(query: str, perf_stats: dict[str, float | int | bool], total_elapsed: float) -> None:
        """디버그 모드에서 응답 단계별 성능 지표를 출력합니다."""
        if not DEBUG_RETRIEVAL_TIMING:
            return
        print(
            "[PERF] "
            f"query='{query[:60]}' "
            f"hybrid_calls={int(perf_stats.get('hybrid_calls', 0))} "
            f"keyword_calls={int(perf_stats.get('keyword_calls', 0))} "
            f"csv_short_circuit_hit={int(perf_stats.get('csv_short_circuit_hit', 0))} "
            f"llm_calls={int(perf_stats.get('llm_calls', 0))} "
            f"retrieval_elapsed={float(perf_stats.get('retrieval_elapsed', 0.0)):.3f}s "
            f"generation_elapsed={float(perf_stats.get('generation_elapsed', 0.0)):.3f}s "
            f"budget_exhausted={bool(perf_stats.get('budget_exhausted', False))} "
            f"total_elapsed={total_elapsed:.3f}s"
        )

    def _answer_with_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        intent: QueryIntent,
        question_plan: QuestionPlan,
        perf_stats: dict[str, float | int | bool] | None = None,
        comparison_targets: list[str] | None = None,
    ) -> dict[str, Any]:
        """검색 결과를 기반으로 최종 답변을 생성합니다."""
        source_type = self._infer_source_type(results)
        evidence_spans = self._build_evidence_spans(results, question_plan=question_plan, max_items=3)
        query_is_comparison_like = (
            question_plan.is_comparison
            or question_plan.query_kind in {"multi_doc", "comparison"}
            or self._is_comparison_query(query)
            or len(comparison_targets or []) >= 2
        )
        direct_orgs = self._extract_org_names_from_query(query, limit=2, allow_project_fallback=False)
        if self._is_budget_query(query) and len(direct_orgs) <= 1:
            query_is_comparison_like = False
        if intent.org_name and len(direct_orgs) <= 1 and not self._is_comparison_query(query):
            query_is_comparison_like = False
        resolved_targets = comparison_targets or []
        if query_is_comparison_like and not resolved_targets:
            resolved_targets = self._resolve_query_target_orgs(query, min_targets=2)
        is_multi_target = len(resolved_targets) >= 2
        if query_is_comparison_like and is_multi_target:
            if not self._has_comparison_coverage(
                query, results, min_docs_per_org=1, explicit_orgs=resolved_targets[:2]
            ):
                warning = (
                    "비교 답변을 위해 문서 A/B를 모두 검색했지만 "
                    "문서 B 근거 부족으로 단정 비교를 생략합니다."
                )
                self.conversation.add_exchange(query, warning, intent)
                slot_fill_rate = self._estimate_slot_fill_rate(question_plan, warning, evidence_spans)
                confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="extractive")
                return self._build_answer_payload(
                    answer=warning,
                    found=True,
                    source_type=source_type,
                    answer_mode="extractive",
                    slot_fill_rate=slot_fill_rate,
                    confidence=confidence,
                    evidence_spans=evidence_spans,
                )
            comparison_answer = self._build_comparison_answer_from_results(query, results)
            if comparison_answer:
                self.conversation.add_exchange(query, comparison_answer, intent)
                slot_fill_rate = self._estimate_slot_fill_rate(question_plan, comparison_answer, evidence_spans)
                confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="extractive")
                return self._build_answer_payload(
                    answer=comparison_answer,
                    found=True,
                    source_type=source_type,
                    answer_mode="extractive",
                    slot_fill_rate=slot_fill_rate,
                    confidence=confidence,
                    evidence_spans=evidence_spans,
                )
        # 사실형/기한/책임 질의는 생성 전에 추출 우선으로 답변 시도
        if self._should_try_extractive_first(query, question_plan):
            extractive_answer = self._build_non_llm_answer(query, results, intent)
            if (
                extractive_answer
                and not self._looks_uncertain_answer(extractive_answer)
                and (query_is_comparison_like or not self._has_comparison_structure(extractive_answer))
            ):
                self.conversation.add_exchange(query, extractive_answer, intent)
                slot_fill_rate = self._estimate_slot_fill_rate(question_plan, extractive_answer, evidence_spans)
                confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="extractive")
                return self._build_answer_payload(
                    answer=extractive_answer,
                    found=True,
                    source_type=source_type,
                    answer_mode="extractive",
                    slot_fill_rate=slot_fill_rate,
                    confidence=confidence,
                    evidence_spans=evidence_spans,
                )

        if not self.llm:
            # LLM이 없으면 규칙 기반 응답 후 요약 fallback
            answer = self._build_non_llm_answer(query, results, intent)
            if answer:
                self.conversation.add_exchange(query, answer, intent)
                slot_fill_rate = self._estimate_slot_fill_rate(question_plan, answer, evidence_spans)
                confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="extractive")
                return self._build_answer_payload(
                    answer=answer,
                    found=True,
                    source_type=source_type,
                    answer_mode="extractive",
                    slot_fill_rate=slot_fill_rate,
                    confidence=confidence,
                    evidence_spans=evidence_spans,
                )
            summary = self._create_multi_org_summary(results, query)
            self.conversation.add_exchange(query, summary, intent)
            slot_fill_rate = self._estimate_slot_fill_rate(question_plan, summary, evidence_spans)
            confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="generative")
            return self._build_answer_payload(
                answer=summary,
                found=True,
                source_type=source_type,
                answer_mode="generative",
                slot_fill_rate=slot_fill_rate,
                confidence=confidence,
                evidence_spans=evidence_spans,
            )

        context = self._build_context(query, results)
        history = self.conversation.get_context_summary()
        generation_started = time.perf_counter()
        answer = self.answer_generator.generate(query, context, history)
        if perf_stats is not None:
            perf_stats["generation_elapsed"] = perf_stats.get("generation_elapsed", 0.0) + (
                time.perf_counter() - generation_started
            )
            perf_stats["llm_calls"] = int(perf_stats.get("llm_calls", 0)) + 1
        if question_plan.is_comparison and query_is_comparison_like:
            answer = self._enforce_comparison_template(query, answer, results)
        answer_mode = "generative"
        if not query_is_comparison_like and self._has_comparison_structure(answer):
            fallback = self._build_non_llm_answer(query, results, intent)
            if fallback and not self._has_comparison_structure(fallback):
                answer = fallback
                answer_mode = "hybrid"
            else:
                # 비교 질의가 아닌데 A/B 포맷이 생성된 경우 안전한 단일 문서 답변으로 강제한다.
                source_line = self._format_first_source(results)
                org_prefix = f"{intent.org_name} 문서 기준 " if intent.org_name else "문서 기준 "
                answer = (
                    f"{org_prefix}질문 관련 근거를 확인했습니다. 비교 질의가 아니므로 단일 문서 기준으로 답변합니다.\n\n"
                    f"[출처]\n- {source_line}"
                )
                answer_mode = "extractive"
        # LLM이 과도하게 "명시 없음"으로 수렴하면 규칙 기반 근거 답변으로 보완
        if self._looks_uncertain_answer(answer):
            fallback = self._build_non_llm_answer(query, results, intent)
            if (
                fallback
                and not self._looks_uncertain_answer(fallback)
                and (query_is_comparison_like or not self._has_comparison_structure(fallback))
            ):
                answer = fallback
                answer_mode = "hybrid"
        if answer and "오류:" not in answer:
            self.conversation.add_exchange(query, answer, intent)
            slot_fill_rate = self._estimate_slot_fill_rate(question_plan, answer, evidence_spans)
            confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode=answer_mode)
            return self._build_answer_payload(
                answer=answer,
                found=True,
                source_type=source_type,
                answer_mode=answer_mode,
                slot_fill_rate=slot_fill_rate,
                confidence=confidence,
                evidence_spans=evidence_spans,
            )

        # 예외적으로 생성 실패 시 fallback
        summary = self._create_multi_org_summary(results, query)
        self.conversation.add_exchange(query, summary, intent)
        slot_fill_rate = self._estimate_slot_fill_rate(question_plan, summary, evidence_spans)
        confidence = self._estimate_confidence(slot_fill_rate, evidence_spans, answer_mode="generative")
        return self._build_answer_payload(
            answer=summary,
            found=True,
            source_type=source_type,
            answer_mode="generative",
            slot_fill_rate=slot_fill_rate,
            confidence=confidence,
            evidence_spans=evidence_spans,
        )

    def _build_non_llm_answer(
        self,
        query: str,
        results: list[dict[str, Any]],
        intent: QueryIntent,
    ) -> str:
        """LLM 보완용 규칙 기반 답변 생성기."""
        if not results:
            return ""
        if self._is_comparison_query(query):
            return self._build_comparison_answer_from_results(query, results)

        top_orgs = [str((r.get("metadata") or {}).get("org", "")).strip() for r in results[:8]]
        unique_orgs = [o for o in dict.fromkeys(top_orgs) if o]
        single_org = len(unique_orgs) == 1
        target_org = unique_orgs[0] if unique_orgs else (intent.org_name or "")

        q = unicodedata.normalize("NFKC", query.lower())
        is_responsibility_query = any(
            k in q for k in ["저작권", "라이선스", "사용권", "글꼴", "이미지", "부담", "책임", "지적재산"]
        )
        is_security_requirement_query = bool(
            re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q, flags=re.IGNORECASE)
            or any(k in q for k in ["보안", "접근통제", "암호화", "인증", "취약성", "비밀번호"])
        )

        direct_fact = self._extract_direct_fact_from_results(query, results, target_org=target_org)
        if direct_fact:
            fact_answer, evidence, source_line = direct_fact
            detail = "\n".join([f"- {line}" for line in evidence[:2]])
            org_prefix = f"{target_org} 문서 기준 " if target_org else ""
            return (
                f"{org_prefix}{fact_answer}\n\n"
                f"[근거]\n{detail}\n\n"
                f"[출처]\n- {source_line}"
            )

        if self._is_budget_query(query) and not self._has_budget_evidence(results, top_n=max(12, len(results[:12]))):
            source_line = self._format_first_source(results)
            org_prefix = f"{target_org} 문서 기준 " if target_org else "문서 기준 "
            return (
                f"{org_prefix}사업비를 특정할 직접 근거(예산/금액 표기)를 찾지 못했습니다.\n\n"
                f"[출처]\n- {source_line}"
            )

        evidence_limit = 6 if is_security_requirement_query else 3
        evidence = self._extract_evidence_lines(query, results, max_lines=evidence_limit)
        if is_responsibility_query and single_org:
            if not evidence:
                return (
                    f"{target_org} 문서에서 이미지/글꼴 저작권 비용 부담 주체를 직접 명시한 조항을 찾지 못했습니다.\n"
                    "원본 제안요청서의 저작권/지식재산권/산출물 귀속 조항을 확인해 주세요."
                )
            owner_markers = ["책임", "부담", "귀속", "소유권", "제안사", "사업자", "발주기관", "발주처"]
            owner_evidence = [line for line in evidence if any(marker in line for marker in owner_markers)]
            if not owner_evidence:
                return (
                    f"{target_org} 문서에서 이미지/글꼴 저작권 비용 부담 주체를 직접 명시한 조항을 찾지 못했습니다.\n"
                    "원본 제안요청서의 저작권/지식재산권/산출물 귀속 조항을 확인해 주세요."
                )

            owner = self._infer_responsibility_owner(owner_evidence)
            source_line = self._format_first_source(results)
            detail = "\n".join([f"- {line}" for line in owner_evidence])
            return (
                f"{target_org} 문서 기준으로 저작권 비용 부담 주체는 **{owner}**로 해석됩니다.\n\n"
                f"[근거]\n{detail}\n\n"
                f"[출처]\n- {source_line}"
            )

        if is_security_requirement_query and evidence:
            source_line = self._format_first_source(results)
            detail = "\n".join([f"- {line}" for line in evidence[:6]])
            org_prefix = f"{target_org} 문서 기준 " if target_org else ""
            return (
                f"{org_prefix}반드시 적용해야 할 보안 조치는 다음 근거 조항으로 확인됩니다.\n\n"
                f"[근거]\n{detail}\n\n"
                f"[출처]\n- {source_line}"
            )

        if self._is_precision_fact_query(query) and not self._has_precision_anchor_evidence(query, results):
            source_line = self._format_first_source(results)
            org_prefix = f"{target_org} 문서 기준 " if target_org else "문서 기준 "
            return (
                f"{org_prefix}질문의 핵심값을 특정할 직접 근거가 부족해 단정 답변을 생략합니다.\n\n"
                f"[출처]\n- {source_line}"
            )

        if single_org and evidence:
            source_line = self._format_first_source(results)
            detail = "\n".join([f"- {line}" for line in evidence])
            return (
                f"{target_org} 문서에서 질문 관련 조항을 확인했습니다.\n\n"
                f"[근거]\n{detail}\n\n"
                f"[출처]\n- {source_line}"
            )

        return ""

    @staticmethod
    def _format_first_source(results: list[dict[str, Any]]) -> str:
        if not results:
            return "source 없음"
        md = results[0].get("metadata", {}) or {}
        src = md.get("source", "Unknown")
        page = md.get("page")
        return f"{src} p.{page}" if page is not None else str(src)

    @staticmethod
    def _pick_slot_for_evidence(question_plan: QuestionPlan, idx: int) -> str:
        if question_plan.is_comparison:
            if idx == 0:
                return "docA_claim"
            if idx == 1:
                return "docB_claim"
            return "comparison_point"
        if question_plan.query_kind == "owner":
            return "owner"
        if question_plan.query_kind in {"fact_numeric", "deadline"}:
            return "value"
        return "evidence"

    def _build_evidence_spans(
        self,
        results: list[dict[str, Any]],
        question_plan: QuestionPlan,
        max_items: int = 3,
    ) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        for item in results[:max_items]:
            idx = len(spans)
            md = item.get("metadata", {}) or {}
            source = str(md.get("source", "Unknown"))
            page_raw = md.get("page")
            try:
                page = int(page_raw) if page_raw is not None else None
            except (TypeError, ValueError):
                page = None
            text = str(item.get("text", "")).strip().replace("\r", "\n")
            snippet = text[:240]
            score_raw = item.get("score", md.get("score", 0.0))
            try:
                score = float(score_raw) if score_raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            spans.append(
                EvidenceSpan(
                    source=source,
                    page=page,
                    text=snippet,
                    slot=self._pick_slot_for_evidence(question_plan, idx),
                    score=score,
                )
            )
        return spans

    @staticmethod
    def _should_try_extractive_first(query: str, question_plan: QuestionPlan) -> bool:
        if question_plan.is_comparison:
            return True
        if question_plan.query_kind in {"fact_numeric", "deadline", "owner"}:
            return True
        q = unicodedata.normalize("NFKC", query.lower())
        if re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q, flags=re.IGNORECASE):
            return True
        return any(
            token in q
            for token in [
                "얼마", "몇", "단위", "기한", "마감", "언제", "누가", "책임", "부담",
                "문자셋", "utf", "인코딩", "가용성", "운영",
                "복구", "용량", "사업비", "서류", "가이드", "절차", "준수사항", "제재",
                "핵심투입인력", "사업관리자", "배점", "적격",
            ]
        )

    @staticmethod
    def _has_comparison_structure(answer: str) -> bool:
        lowered = unicodedata.normalize("NFKC", (answer or "").lower())
        required = ["a 문서", "b 문서", "공통", "차이"]
        return all(token in lowered for token in required)

    def _enforce_comparison_template(
        self,
        query: str,
        answer: str,
        results: list[dict[str, Any]],
    ) -> str:
        if self._has_comparison_structure(answer):
            return answer
        fallback = self._build_comparison_answer_from_results(query, results)
        return fallback or answer

    def _build_comparison_answer_from_results(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> str:
        if not results:
            return ""

        grouped_by_org: dict[str, list[dict[str, Any]]] = {}
        for item in results[:40]:
            md = item.get("metadata", {}) or {}
            org = str(md.get("org", "")).strip()
            source = str(md.get("source", "Unknown"))
            key = org or source
            grouped_by_org.setdefault(key, []).append(item)

        explicit_orgs = self._resolve_query_target_orgs(query, min_targets=2)
        preferred_orgs: list[str] = []
        for cand in explicit_orgs:
            resolved = self._resolve_known_org_name(cand) or cand
            for existing in grouped_by_org.keys():
                if self._org_names_loosely_match(resolved, existing):
                    if existing not in preferred_orgs:
                        preferred_orgs.append(existing)
                    break

        if len(preferred_orgs) < 2:
            by_volume = sorted(grouped_by_org.items(), key=lambda kv: len(kv[1]), reverse=True)
            for org_key, _items in by_volume:
                if org_key not in preferred_orgs:
                    preferred_orgs.append(org_key)
                if len(preferred_orgs) >= 2:
                    break

        if len(preferred_orgs) < 2 and explicit_orgs:
            for org in explicit_orgs:
                if org not in preferred_orgs:
                    preferred_orgs.append(org)
                if len(preferred_orgs) >= 2:
                    break

        if len(preferred_orgs) < 2 and grouped_by_org:
            first_key = next(iter(grouped_by_org.keys()))
            preferred_orgs = [first_key, "비교 대상 문서"]

        org_a = preferred_orgs[0] if preferred_orgs else "A 문서"
        org_b = preferred_orgs[1] if len(preferred_orgs) > 1 else "B 문서"
        group_a = grouped_by_org.get(org_a, [])
        group_b = grouped_by_org.get(org_b, [])
        if not group_a and grouped_by_org:
            group_a = next(iter(grouped_by_org.values()))
        if not group_b:
            # 비교 대상 근거가 부족한 경우 placeholder를 유지한다.
            group_b = []

        def _line(group: list[dict[str, Any]]) -> str:
            lines = self._extract_evidence_lines(query, group, max_lines=6)
            if not lines:
                return "질문과 직접 일치하는 조항을 찾지 못했습니다."
            return "; ".join(lines[:4])

        claim_a = _line(group_a)
        claim_b = _line(group_b) if group_b else "문서 B 근거 부족(직접 근거 미확보)."

        common = "두 문서 모두 질문 주제와 연관된 조항/의무를 명시합니다."
        keywords = self._extract_query_keywords(query, max_keywords=12)
        shared = [kw for kw in keywords if kw and kw in self._normalize_text_for_match(claim_a) and kw in self._normalize_text_for_match(claim_b)]
        if shared:
            common = f"공통적으로 `{', '.join(shared[:4])}` 관련 요건을 포함합니다."
        difference = f"A 문서는 `{claim_a}` 중심, B 문서는 `{claim_b}` 중심으로 규정 범위가 다릅니다."

        source_a = str((group_a[0].get("metadata", {}) or {}).get("source", "Unknown")) if group_a else "Unknown"
        source_b = str((group_b[0].get("metadata", {}) or {}).get("source", "Unknown")) if group_b else "Unknown"
        page_a = (group_a[0].get("metadata", {}) or {}).get("page") if group_a else None
        page_b = (group_b[0].get("metadata", {}) or {}).get("page") if group_b else None
        src_a = f"{source_a} p.{page_a}" if page_a is not None else source_a
        src_b = f"{source_b} p.{page_b}" if page_b is not None else source_b
        label_a = f"{org_a} | {src_a}" if org_a and org_a != source_a else src_a
        label_b = f"{org_b} | {src_b}" if org_b and org_b != source_b else src_b

        return (
            f"A 문서: {claim_a}\n"
            f"B 문서: {claim_b}\n"
            f"공통: {common}\n"
            f"차이: {difference}\n\n"
            f"[출처]\n"
            f"- A: {label_a}\n"
            f"- B: {label_b}"
        )

    @staticmethod
    def _build_answer_payload(
        answer: str,
        found: bool,
        source_type: str,
        answer_mode: str,
        slot_fill_rate: float,
        confidence: float,
        evidence_spans: list[EvidenceSpan],
    ) -> dict[str, Any]:
        evidence_dicts = [
            {
                "source": span.source,
                "page": span.page,
                "text": span.text,
                "slot": span.slot,
                "score": span.score,
            }
            for span in evidence_spans
        ]
        draft = AnswerDraft(
            final_answer=answer,
            slot_fill_rate=slot_fill_rate,
            confidence=confidence,
            evidence_refs=evidence_spans,
            answer_mode=answer_mode,
        )
        formatted_answer = RAGChatbotV17._format_answer_for_readability(draft.final_answer)
        return {
            "answer": formatted_answer,
            "found": found,
            "source_type": source_type,
            "answer_mode": draft.answer_mode,
            "slot_fill_rate": draft.slot_fill_rate,
            "evidence_count": len(draft.evidence_refs),
            "confidence": draft.confidence,
            "evidence": evidence_dicts,
        }

    @staticmethod
    def _format_answer_for_readability(answer: str) -> str:
        """답변 섹션 제목과 줄바꿈을 정리해 가독성을 높입니다."""
        text = (answer or "").replace("\r\n", "\n").strip()
        if not text:
            return ""

        replacements = {
            "[핵심 답변]": "### 핵심 답변",
            "[근거 요약]": "### 근거 요약",
            "[근거]": "### 근거 요약",
            "[출처]": "### 출처",
        }
        for before, after in replacements.items():
            text = text.replace(before, after)

        # 출처 섹션에 불릿이 누락된 경우 자동 보정
        lines = text.split("\n")
        normalized_lines: list[str] = []
        in_source_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("### "):
                in_source_section = stripped == "### 출처"
                normalized_lines.append(stripped)
                continue
            if in_source_section and stripped and not stripped.startswith("- "):
                normalized_lines.append(f"- {stripped}")
            else:
                normalized_lines.append(line)

        text = "\n".join(normalized_lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _estimate_slot_fill_rate(
        self,
        question_plan: QuestionPlan,
        answer: str,
        evidence_spans: list[EvidenceSpan],
    ) -> float:
        required = question_plan.required_slots or []
        if not required:
            return 1.0 if answer.strip() else 0.0

        lowered = unicodedata.normalize("NFKC", answer.lower())
        filled = 0
        for slot in required:
            if slot in {"value", "unit"}:
                has_number = bool(re.search(r"\d", answer))
                has_unit = any(u in answer for u in ["원", "억", "만", "명", "건", "개", "일", "시간", "MB", "GB", "%", "회"])
                if slot == "value" and has_number:
                    filled += 1
                if slot == "unit" and has_unit:
                    filled += 1
                continue
            if slot == "owner":
                if any(k in lowered for k in ["발주", "제안", "수급", "계약상대", "사업자", "주관기관"]):
                    filled += 1
                continue
            if slot in {"docA_claim", "docB_claim"}:
                has_a = any(k in answer for k in ["A 문서", "문서 A", "첫 번째"])
                has_b = any(k in answer for k in ["B 문서", "문서 B", "두 번째"])
                if slot == "docA_claim" and has_a:
                    filled += 1
                if slot == "docB_claim" and has_b:
                    filled += 1
                continue
            if slot == "comparison_point":
                if any(k in lowered for k in ["차이", "공통", "반면", "각각", "비교"]):
                    filled += 1
                continue
            if slot == "evidence":
                if evidence_spans:
                    filled += 1
                continue
            if slot == "key_points":
                if len(answer.strip()) >= 24:
                    filled += 1
                continue

        return min(1.0, max(0.0, filled / max(1, len(required))))

    @staticmethod
    def _estimate_confidence(
        slot_fill_rate: float,
        evidence_spans: list[EvidenceSpan],
        answer_mode: str,
    ) -> float:
        base = 0.35
        base += slot_fill_rate * 0.45
        base += min(0.2, len(evidence_spans) * 0.06)
        if answer_mode == "extractive":
            base += 0.05
        if answer_mode == "hybrid":
            base += 0.03
        return round(min(1.0, max(0.0, base)), 3)

    def _extract_evidence_lines(
        self,
        query: str,
        results: list[dict[str, Any]],
        max_lines: int = 3,
    ) -> list[str]:
        """질의 키워드와 일치하는 근거 라인을 추출합니다."""
        keywords = self._extract_query_keywords(query, max_keywords=18)
        q_norm = unicodedata.normalize("NFKC", query.lower())
        focus_terms = self._extract_focus_terms_for_fact(query)

        wants_capacity = any(token in q_norm for token in ["용량", "mb", "gb", "kb"])
        wants_unit_quantity = any(token in q_norm for token in ["단위", "수량", "개수", "명", "건", "몇"])
        wants_charset = any(token in q_norm for token in ["문자셋", "인코딩", "utf", "charset"])
        wants_deadline = any(token in q_norm for token in ["복구", "기한", "이내", "시간", "장애", "마감"])
        req_mode = bool(re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q_norm, flags=re.IGNORECASE))
        req_code_patterns: list[re.Pattern[str]] = []
        for code in re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q_norm, flags=re.IGNORECASE):
            alpha = re.sub(r"[^a-z]", "", code.lower())
            digits = re.sub(r"[^0-9]", "", code)
            if not alpha or not digits:
                continue
            req_code_patterns.append(re.compile(rf"{alpha}\s*[-_ ]?\s*0*{digits}", re.IGNORECASE))

        # 요구사항 코드(anchor)가 질의에 있으면 코드 라인과 인접 보안/요건 라인을 우선 확보한다.
        if req_code_patterns:
            anchor_lines: list[str] = []
            anchor_follow_tokens = ["보안", "접근", "권한", "암호", "인증", "취약", "패스워드", "로그", "백업", "요건", "요구"]
            for item in results[:12]:
                text = (item.get("text", "") or "").replace("\r", "\n")
                split_lines = [ln.strip() for ln in text.split("\n")]
                for idx, line in enumerate(split_lines):
                    if not line:
                        continue
                    line_lower = unicodedata.normalize("NFKC", line.lower())
                    if not any(pat.search(line_lower) for pat in req_code_patterns):
                        continue
                    snippet_parts = [line]
                    for j in range(idx + 1, min(len(split_lines), idx + 8)):
                        nxt = split_lines[j].strip()
                        if not nxt or self._is_noise_line(nxt):
                            continue
                        if any(token in nxt for token in anchor_follow_tokens):
                            snippet_parts.append(nxt)
                        if len(" ; ".join(snippet_parts)) >= 180 or len(snippet_parts) >= 3:
                            break
                    anchor_lines.append(" ; ".join(snippet_parts)[:220])
            if anchor_lines:
                uniq_anchor: list[str] = []
                seen_anchor: set[str] = set()
                for line in anchor_lines:
                    if not line or line in seen_anchor:
                        continue
                    seen_anchor.add(line)
                    uniq_anchor.append(line)
                    if len(uniq_anchor) >= max_lines:
                        break
                if uniq_anchor:
                    return uniq_anchor

        focus_markers: list[str] = []
        if any(token in q_norm for token in ["보안", "ser", "접근", "암호화", "인증", "취약", "비밀번호"]):
            focus_markers.extend(["보안", "접근통제", "권한", "암호화", "인증", "패스워드", "취약", "로그", "백업"])
            req_mode = True
        if any(token in q_norm for token in ["윤리", "제재", "담합", "뇌물"]):
            focus_markers.extend(["윤리", "청렴", "담합", "뇌물", "제재", "제한", "위약", "부정당", "고발"])
        if any(token in q_norm for token in ["재고", "거래", "전송", "기록", "판매", "주문", "결제"]):
            focus_markers.extend(["재고", "거래", "전송", "판매", "주문", "결제", "이관", "통계", "조회", "팩스", "문자"])

        numeric_pattern = re.compile(
            r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(원|만원|억원|천원|%|명|건|개|회|시간|분|초|일|주|개월|년|KB|MB|GB|TB)",
            re.IGNORECASE,
        )
        charset_pattern = re.compile(r"(utf[-\s]?8|euc[-\s]?kr|cp949|utf[-\s]?16|ascii)", re.IGNORECASE)
        deadline_pattern = re.compile(r"\d+\s*(시간|일|주|개월)\s*(이내|이상|이하)?", re.IGNORECASE)

        scored_lines: list[tuple[int, str]] = []
        req_anchor_lines: list[tuple[int, str]] = []
        for item in results[:12]:
            text = (item.get("text", "") or "").replace("\r", "\n")
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                line_lower = unicodedata.normalize("NFKC", line.lower())
                code_like_line = bool(re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", line_lower, flags=re.IGNORECASE))
                if (len(line) < 8 and not code_like_line) or self._is_noise_line(line):
                    continue

                line_key = self._normalize_text_for_match(line)
                score = sum(1 for keyword in keywords if keyword in line_key)
                marker_hits = sum(1 for marker in focus_markers if marker in line)
                has_number = bool(numeric_pattern.search(line))
                is_table_row = line.count("|") >= 2
                has_unit_pair = bool(
                    re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(명|건|개|회|mb|gb|kb)", line, re.IGNORECASE)
                )
                focus_hit = any(term in line_lower for term in focus_terms) if focus_terms else False
                req_match = next((pat.search(line_lower) for pat in req_code_patterns if pat.search(line_lower)), None)
                req_code_hit = req_match is not None
                if req_code_hit:
                    score += 12

                if wants_charset:
                    if not charset_pattern.search(line):
                        continue
                    score += 4

                if wants_capacity:
                    if not has_number or not re.search(r"(mb|gb|kb|용량)", line, re.IGNORECASE):
                        continue
                    if focus_terms and not focus_hit and "웹페이지" in q_norm and "웹페이지" not in line:
                        continue
                    score += 3

                if wants_unit_quantity:
                    if not has_number:
                        continue
                    if not (is_table_row or has_unit_pair or any(marker in line for marker in ["단위", "수량"])):
                        continue
                    if focus_terms and not focus_hit:
                        continue
                    if (is_table_row and has_unit_pair) or ("단위" in line and "수량" in line):
                        score += 3

                if wants_deadline and "복구" in q_norm:
                    has_recovery = any(marker in line for marker in ["복구", "장애"])
                    has_deadline_value = bool(deadline_pattern.search(line)) or any(
                        marker in line for marker in ["이내", "시간", "기한", "마감"]
                    )
                    if not (has_recovery and has_deadline_value):
                        continue
                    if focus_terms and not focus_hit:
                        continue
                    score += 3

                if marker_hits > 0:
                    score += marker_hits * 2
                if req_mode and marker_hits <= 0 and score < 2:
                    continue
                if score <= 0 and keywords:
                    continue
                snippet = line[:220]
                if req_code_hit and req_match:
                    # 코드 앵커 질의는 코드 주변 스니펫을 우선 반환해 핵심 근거가 잘리지 않도록 한다.
                    start = max(0, req_match.start() - 90)
                    end = min(len(line), req_match.end() + 130)
                    snippet = line[start:end].strip()
                snippet = snippet[:220]
                scored_lines.append((score, snippet))
                if req_code_hit:
                    req_anchor_lines.append((score, snippet))

        if scored_lines:
            scored_lines.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            req_anchor_lines.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            output: list[str] = []
            seen: set[str] = set()
            if req_mode and req_anchor_lines:
                for _score, line in req_anchor_lines:
                    if line in seen:
                        continue
                    seen.add(line)
                    output.append(line)
                    if len(output) >= min(max_lines, 2):
                        break
            for _score, line in scored_lines:
                if line in seen:
                    continue
                seen.add(line)
                output.append(line)
                if len(output) >= max_lines:
                    break
            if output:
                return output

        # 키워드 매칭 실패 시 의무/요구 표현 중심으로 2차 추출
        lines: list[str] = []
        fallback_markers = [
            "해야", "하여야", "필수", "요구", "제출", "평가", "기준", "책임", "부담",
            "보안", "운영", "이내", "매일", "월", "주", "재고", "거래", "전송", "주문", "결제",
            "윤리", "청렴", "제재", "담합", "뇌물",
        ]
        for item in results[:10]:
            text = (item.get("text", "") or "").replace("\r", "\n")
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if len(line) < 12 or self._is_noise_line(line):
                    continue
                if not any(marker in line for marker in fallback_markers):
                    continue
                lines.append(line[:220])
                if len(lines) >= max_lines:
                    return lines
        return lines

    @staticmethod
    def _normalize_text_for_match(text: str) -> str:
        normalized = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", (text or "").lower()))
        return re.sub(r"[^0-9a-zA-Z가-힣]+", "", normalized)

    @staticmethod
    def _is_noise_line(line: str) -> bool:
        stripped = (line or "").strip()
        if len(stripped) < 6:
            return True
        metadata_markers = [
            "사업명",
            "사 업 명",
            "공고번호",
            "공고 번호",
            "발주기관",
            "발주 기관",
            "입찰마감",
            "입찰 마감",
            "과업명",
            "용역명",
        ]
        compact = stripped.replace(" ", "")
        if any(compact.startswith(marker.replace(" ", "")) for marker in metadata_markers):
            return True
        noise_prefixes = [
            "- **파일명**",
            "- **사업명**",
            "- **공고 번호**",
            "- **공개 일자**",
            "## 기본 정보",
            "## 원본 문서 정보",
            "### 페이지",
            "□ 사업명",
            "○ 사업명",
            "가. 사업명",
            "나. 사업명",
        ]
        if any(stripped.startswith(prefix) for prefix in noise_prefixes):
            return True
        lowered = stripped.lower()
        if lowered.startswith("source:") or "logical page" in lowered:
            return True
        if stripped.startswith("| ---"):
            return True
        # 마크다운 표 구분선(---)은 노이즈로 처리하되, 실제 표 본문 행은 유지한다.
        if re.fullmatch(r"\|?\s*[:\-]+\s*(\|\s*[:\-]+\s*)+\|?", stripped):
            return True
        if stripped.count("|") >= 3:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            non_empty = [c for c in cells if c]
            if non_empty and all(cell in {"-", "--", "---", ":"} for cell in non_empty):
                return True
        if stripped.count("  ") >= 4 and any(token in stripped for token in ["제안서", "제출", "목차"]):
            return True
        return False

    def _extract_query_keywords(self, query: str, max_keywords: int = 10) -> list[str]:
        raw = unicodedata.normalize("NFKC", query.lower())
        tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", raw)
        stopwords = {
            "무엇", "무엇인가", "무엇인가요", "알려줘", "알려주세요", "해주세요", "어떻게", "있나요", "있습니까",
            "인가요", "입니다", "그리고", "또한", "해당", "문서", "질문", "각각", "비교", "관련", "기준",
        }
        keywords: list[str] = []
        priority_keywords: list[str] = []
        for token in tokens:
            if token in stopwords:
                continue
            if token.isdigit():
                continue
            keywords.append(self._normalize_text_for_match(token))

        req_codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", raw, flags=re.IGNORECASE)
        for code in req_codes:
            compact = self._normalize_text_for_match(code)
            if compact:
                priority_keywords.append(compact)
                alpha = re.sub(r"[^a-z]", "", code.lower())
                digits = re.sub(r"[^0-9]", "", code)
                if alpha:
                    priority_keywords.append(alpha)
                if alpha and digits:
                    priority_keywords.append(self._normalize_text_for_match(f"{alpha}{digits}"))

        synonym_map = {
            "마감": ["기한", "제출", "일정"],
            "기한": ["마감", "일정", "이내"],
            "기간": ["착수", "완료", "일정"],
            "언제": ["일자", "날짜", "기한"],
            "수량": ["단위", "개수", "수치"],
            "단위": ["수량", "개수", "용량"],
            "용량": ["mb", "gb", "kb"],
            "문자셋": ["utf", "인코딩", "charset"],
            "인코딩": ["문자셋", "utf", "charset"],
            "책임": ["부담", "주체", "귀속", "소유권"],
            "부담": ["책임", "주체", "귀속"],
            "비교": ["차이", "공통", "각각"],
            "가용성": ["무중단", "운영", "24시간", "중단"],
            "요구사항": ["요건", "기준", "조항"],
            "보안": ["접근통제", "암호화", "인증", "취약점"],
        }
        for token in tokens:
            for synonym in synonym_map.get(token, []):
                keywords.append(self._normalize_text_for_match(synonym))

        uniq: list[str] = []
        seen: set[str] = set()
        for keyword in priority_keywords + keywords:
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            uniq.append(keyword)
            if len(uniq) >= max_keywords:
                break
        return uniq

    @staticmethod
    def _extract_focus_terms_for_fact(query: str, max_terms: int = 8) -> list[str]:
        """수치/문자셋/기한 질의의 핵심 앵커 토큰을 추출합니다."""
        raw = unicodedata.normalize("NFKC", (query or "").lower())
        tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", raw)
        stopwords = {
            "무엇", "무엇인가", "무엇인가요", "알려줘", "알려주세요", "해주세요",
            "문서", "기준", "질문", "관련", "각각", "비교", "그리고", "또한",
            "사업", "정보", "내용", "기능", "값", "얼마", "몇", "단위", "수량",
            "기한", "시간", "이내", "복구기한", "요구사항",
        }
        focus: list[str] = []
        for token in tokens:
            if token in stopwords:
                continue
            if token.isdigit():
                continue
            if token.endswith(("대학교", "대학", "특별시", "광역시", "재단", "공사", "연구원", "센터")):
                continue
            focus.append(token)
            if len(focus) >= max_terms:
                break
        return focus

    def _extract_direct_fact_from_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        target_org: str = "",
    ) -> tuple[str, list[str], str] | None:
        """사실형 질의를 검색 결과의 근거 문장과 범용 패턴으로 추출합니다."""
        if not results:
            return None

        normalized_query = unicodedata.normalize("NFKC", query.lower())
        keywords = self._extract_query_keywords(query, max_keywords=12)
        wants_direct_fact = any(
            token in normalized_query
            for token in [
                "얼마", "수량", "단위", "기한", "주기", "자주", "횟수", "시간", "이내",
                "용량", "mb", "gb", "소유권", "검사", "제출", "저작권", "부담", "책임", "누가", "언제",
                "가용성", "요구사항", "운영",
                "문자셋", "인코딩", "utf",
                "협상", "평가", "배점", "기준", "적격",
                "누구", "핵심투입인력", "사업관리자", "pm", "가이드", "guideline", "guide",
            ]
        )
        if not wants_direct_fact:
            return None

        wants_owner = any(token in normalized_query for token in ["누가", "누구", "책임", "부담", "소유권", "귀속", "저작권"])
        wants_deadline = any(token in normalized_query for token in ["언제", "마감", "기한", "일자", "제출", "이내", "까지"])
        wants_numeric = any(token in normalized_query for token in ["얼마", "몇", "수량", "단위", "횟수", "비율", "퍼센트", "용량", "시간"])
        wants_project_period = "사업기간" in normalized_query or ("기간" in normalized_query and "사업" in normalized_query)
        wants_budget = self._is_budget_query(query)
        wants_capacity = any(token in normalized_query for token in ["용량", "mb", "gb", "kb"])
        wants_unit_quantity = any(token in normalized_query for token in ["수량", "단위", "개수", "명", "건", "몇"])
        wants_charset = any(token in normalized_query for token in ["문자셋", "인코딩", "utf", "charset"])
        wants_recovery_deadline = (
            any(token in normalized_query for token in ["복구", "장애"])
            and any(token in normalized_query for token in ["기한", "이내", "시간"])
        )
        wants_eval_threshold = any(token in normalized_query for token in ["협상", "적격", "배점", "기술능력", "평가점수"])
        wants_education = any(token in normalized_query for token in ["교육", "훈련", "정보보안교육"])
        wants_cpu_spec = any(token in normalized_query for token in ["cpu", "서버", "코어", "ghz", "사양"])
        wants_dimension = any(token in normalized_query for token in ["규격", "치수", "가로", "세로", "도면", "mm"])
        wants_goal = any(token in normalized_query for token in ["추진 목표", "추진목표", "목표는", "목적은"])
        wants_text_value = any(token in normalized_query for token in ["문자셋", "인코딩", "utf", "charset"])
        wants_list_fact = any(token in normalized_query for token in ["서류", "준수사항", "절차", "제재", "증명", "요건"])
        wants_guide = any(token in normalized_query for token in ["가이드", "guideline", "guide"])
        wants_key_personnel = any(
            token in normalized_query for token in ["핵심투입인력", "핵심 인력", "사업관리자", "pm", "누구로 지정"]
        )
        if wants_key_personnel:
            wants_owner = False
        focus_tokens = self._extract_focus_terms_for_fact(query, max_terms=10)
        quoted_anchors = [
            unicodedata.normalize("NFKC", hint.lower())
            for hint in self._extract_project_hints_from_query(query)
            if 2 <= len(hint) <= 24
        ]
        req_codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized_query, flags=re.IGNORECASE)
        wants_requirement = bool(req_codes) or any(token in normalized_query for token in ["요구사항", "요건", "가용성", "운영"])
        focus_terms = [
            token
            for token in ["복구", "장애", "가용성", "무중단", "교육", "보안", "문자셋", "인코딩", "utf", "저작권", "소유권", "귀속", "사업기간", "계약체결일"]
            if token in normalized_query
        ]
        owner_focus_terms = [
            term
            for term in ["저작권", "지식재산", "지적재산", "소유권", "귀속", "비밀정보", "라이선스", "글꼴", "폰트", "이미지"]
            if term in query
        ]
        unit_markers = ["원", "만원", "억원", "%", "명", "건", "개", "회", "시간", "일", "주", "개월", "년", "KB", "MB", "GB", "TB", "GHz", "Core", "mm"]
        numeric_focus_markers = ["이내", "이상", "이하", "최대", "최소", "가용성", "무중단", "주기", "횟수", "용량"]
        deadline_focus_markers = ["마감", "기한", "일자", "제출", "까지", "이내", "착수", "완료", "사업기간", "계약체결일", "개월", "일"]
        requirement_markers = ["요구사항", "요건", "가용성", "무중단", "24시간", "운영", "정상상태", "통상적인 업무시간", "보장"]
        education_markers = ["교육", "정보보안교육", "보안교육", "교육결과", "결과", "확인", "월 1회", "월1회"]
        education_core_markers = ["정보보안교육", "보안교육", "교육", "훈련"]
        budget_markers = ["사업비", "총사업비", "예산", "사업 금액", "사 업 비", "사 업 금 액", "추정가격", "계약금액"]

        numeric_pattern = re.compile(
            r"("
                r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:원|만원|억원|천원|%|명|건|개|회|시간|분|초|일|주|개월|년|KB|MB|GB|TB)"
                r"|"
                r"\d{1,2}:\d{2}"
                r"|"
                r"\d{4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}"
                r"|"
                r"\d{1,2}\s*월\s*\d{1,2}\s*일"
                r"|"
                r"\d+(?:\.\d+)?\s*(?:ghz|core|mm)"
                r")",
                re.IGNORECASE,
        )
        deadline_pattern = re.compile(
            r"("
            r"\d{4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}"
            r"|"
            r"\d{1,2}\s*월\s*\d{1,2}\s*일"
            r"|"
            r"\d{1,2}:\d{2}"
            r"|"
            r"\d+\s*(?:시간|일|주|개월|년)\s*(?:이내|이상|이하)?"
            r")",
            re.IGNORECASE,
        )
        owner_marker_pattern = re.compile(
            r"(책임|부담|귀속|소유권|의무|주체|담당)",
            re.IGNORECASE,
        )
        budget_value_pattern = re.compile(
            r"(금\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:천원|백만원|만원|억원|원)",
            re.IGNORECASE,
        )
        charset_pattern = re.compile(r"(UTF[-\s]?8|EUC[-\s]?KR|CP949|UTF[-\s]?16|ASCII)", re.IGNORECASE)
        owner_subject_pattern = re.compile(
            r"([가-힣A-Za-z0-9()/_\-\s]{2,30})\s*(?:이|가|은|는)?\s*(?:책임|부담|귀속|소유권)",
            re.IGNORECASE,
        )

        candidates: list[tuple[float, str, str]] = []
        fallback_lines: list[tuple[str, str]] = []
        scan_limit = 30 if (wants_text_value or wants_requirement) else 18
        for item in results[:scan_limit]:
            text = (item.get("text", "") or "").replace("\r", "\n")
            md = item.get("metadata", {}) or {}
            source = md.get("source", "Unknown")
            page = md.get("page")
            source_line = f"{source} p.{page}" if page is not None else str(source)

            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if len(line) < 6 or self._is_noise_line(line):
                    continue
                clipped = line[:480]
                fallback_lines.append((clipped, source_line))

                line_key = self._normalize_text_for_match(line)
                score = sum(1 for keyword in keywords if keyword in line_key)
                has_number = bool(numeric_pattern.search(line))
                has_deadline = bool(deadline_pattern.search(line)) or any(marker in line for marker in deadline_focus_markers)
                has_owner = bool(owner_marker_pattern.search(line))
                has_owner_focus = any(term in line for term in owner_focus_terms) if owner_focus_terms else False
                has_focus_term = any(term in line.lower() for term in focus_terms) if focus_terms else False
                has_requirement = any(marker in line for marker in requirement_markers)
                has_education_core = any(marker in line for marker in education_core_markers)
                has_budget_marker = any(marker in line for marker in budget_markers)
                has_budget_value = bool(budget_value_pattern.search(line))
                line_lower = unicodedata.normalize("NFKC", line.lower())
                has_cpu_marker = any(marker in line_lower for marker in ["cpu", "xeon", "intel", "ghz", "core"])
                has_dimension_marker = any(marker in line_lower for marker in ["최소규격", "최대규격", "가로", "세로", "치수", "도면", "mm"])
                focus_hit = any(token in line_lower for token in focus_tokens) if focus_tokens else False
                is_table_row = line.count("|") >= 2
                has_unit_pair = bool(
                    re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(명|건|개|회|mb|gb|kb)", line, re.IGNORECASE)
                )
                has_req_code = False
                for code in req_codes:
                    code_key = self._normalize_text_for_match(code)
                    if code_key and code_key in line_key:
                        has_req_code = True
                        break
                if wants_budget:
                    # 사업비 질의는 금액/예산 라인을 강하게 우선하고 시간값(예: 60분) 과매칭을 배제한다.
                    if not (has_budget_marker or has_budget_value):
                        if score < 2:
                            continue
                    if "분" in line and not has_budget_marker and not has_budget_value:
                        continue
                if wants_owner:
                    # 책임/소유권 질의는 책임 표식이 있는 라인만 우선 채택해 오탐을 줄인다.
                    if not has_owner:
                        if not (owner_focus_terms and has_owner_focus and score >= 2):
                            continue
                    elif owner_focus_terms and not has_owner_focus and score < 2:
                        continue
                if (wants_deadline or wants_numeric) and focus_terms and not has_focus_term and score < 2:
                    # 복구/교육/가용성처럼 질의 핵심 용어가 있는 경우 무관한 숫자 라인을 배제한다.
                    continue
                if wants_requirement and score <= 0 and not has_requirement and not has_req_code:
                    continue
                if wants_education and score < 2 and not has_education_core:
                    continue
                if wants_charset and not charset_pattern.search(line):
                    continue
                if wants_cpu_spec and not has_cpu_marker and score < 2:
                    continue
                if wants_dimension and not has_dimension_marker and score < 2:
                    continue
                if wants_capacity:
                    if not has_number or not re.search(r"(mb|gb|kb|용량)", line, re.IGNORECASE):
                        continue
                    if focus_tokens and not focus_hit and "웹페이지" in normalized_query and "웹페이지" not in line:
                        continue
                if wants_unit_quantity:
                    if not has_number:
                        continue
                    if not (has_unit_pair or is_table_row or "단위" in line or "수량" in line):
                        continue
                    if quoted_anchors and not any(anchor in line_lower for anchor in quoted_anchors):
                        continue
                    if focus_tokens and not focus_hit:
                        continue
                if wants_recovery_deadline:
                    if not any(marker in line for marker in ["복구", "장애"]):
                        continue
                    if not (deadline_pattern.search(line) or any(marker in line for marker in ["이내", "시간", "기한"])):
                        continue
                    if "복구" in normalized_query and "복구" not in line:
                        continue
                    if "시간" in normalized_query and "시간" not in line:
                        continue
                    if "하자보수" in line and "복구" not in line:
                        continue
                    if focus_tokens and not focus_hit:
                        continue
                if wants_project_period:
                    if not any(marker in line for marker in ["사업기간", "계약체결일", "개월", "일", "기간"]):
                        continue
                    if "사업기간" in normalized_query and "사업기간" not in line and "계약체결일" not in line:
                        continue

                boost = 0.0
                if wants_numeric and has_number and (
                    score > 0
                    or any(marker in line for marker in unit_markers)
                    or any(marker in line for marker in numeric_focus_markers)
                ):
                    boost += 2.0
                if wants_text_value and charset_pattern.search(line):
                    boost += 2.4
                if wants_charset and charset_pattern.search(line):
                    boost += 2.8
                if wants_deadline and has_deadline and (
                    score > 0
                    or any(marker in line for marker in deadline_focus_markers)
                ):
                    boost += 2.0
                if wants_project_period and any(marker in line for marker in ["사업기간", "계약체결일", "개월"]):
                    boost += 2.6
                if wants_recovery_deadline and any(marker in line for marker in ["복구", "장애"]):
                    boost += 2.6
                if wants_owner and has_owner and (
                    score > 0
                    or not owner_focus_terms
                    or any(term in line for term in owner_focus_terms)
                ):
                    boost += 2.0
                if wants_requirement and (has_requirement or has_req_code):
                    boost += 2.4
                if wants_requirement and has_requirement and has_number:
                    boost += 0.8
                if wants_education and has_education_core:
                    boost += 2.2
                if wants_budget and (has_budget_marker or has_budget_value):
                    boost += 2.8
                if wants_budget and has_budget_marker and has_budget_value:
                    boost += 1.0
                if wants_capacity and re.search(r"\d+\s*(MB|GB|KB)", line, re.IGNORECASE):
                    boost += 2.2
                if wants_unit_quantity and ((is_table_row and has_unit_pair) or ("단위" in line and "수량" in line)):
                    boost += 2.4
                if wants_cpu_spec and has_cpu_marker:
                    boost += 2.8
                if wants_dimension and has_dimension_marker:
                    boost += 2.6
                if wants_goal and any(marker in line for marker in ["추진목표", "추진 목표", "사업목적", "목표", "목적"]):
                    boost += 2.2

                total = float(score * 1.6) + boost
                if total <= 0:
                    continue
                candidates.append((total, clipped, source_line))

        if candidates:
            candidates.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            ranked = [(line, src) for _, line, src in candidates]
        else:
            if self._is_precision_fact_query(query) and not (wants_guide or wants_key_personnel):
                # 정밀 사실 질의는 저신뢰 fallback 라인으로 임의 답변하지 않는다.
                return None
            seen_pair: set[tuple[str, str]] = set()
            ranked = []
            for line, src in fallback_lines:
                pair = (line, src)
                if pair in seen_pair:
                    continue
                seen_pair.add(pair)
                ranked.append(pair)
                if len(ranked) >= 40:
                    break
            if not ranked:
                return None

        # 중복 제거된 상위 근거 라인 생성
        evidence: list[str] = []
        seen_lines: set[str] = set()
        for line, _src in ranked:
            if line in seen_lines:
                continue
            seen_lines.add(line)
            evidence.append(line)
            if len(evidence) >= 3:
                break
        if not evidence:
            return None

        best_line, best_source = ranked[0]

        if wants_guide:
            guide_lines = [
                line
                for line, _src in ranked
                if any(
                    marker in line.lower()
                    for marker in ["guide to", "guidelines for", "guideline", "guide", "adb", "european commission"]
                )
            ]
            if not guide_lines:
                guide_lines = [
                    line
                    for line, _src in fallback_lines
                    if any(
                        marker in line.lower()
                        for marker in ["guide to", "guidelines for", "guideline", "guide", "adb", "european commission"]
                    )
                ]
            if guide_lines:
                title_patterns = [
                    r"(guidelines?\s+for\s+the\s+economic\s+analysis\s+of\s+projects(?:\s*\(adb\))?)",
                    r"(guide\s+to\s+cost-benefit\s+analysis\s+of\s+investment\s+project(?:\s*\(european\s+commission\))?)",
                ]
                titles: list[str] = []
                for line in guide_lines[:4]:
                    lowered = line.lower()
                    for pattern in title_patterns:
                        for match in re.findall(pattern, lowered, flags=re.IGNORECASE):
                            title = re.sub(r"\s+", " ", match).strip()
                            if title and title not in titles:
                                titles.append(title)
                if titles:
                    normalized_titles = [title[0].upper() + title[1:] if title else title for title in titles]
                    joined = " 및 ".join(normalized_titles[:2])
                    answer = f"문서 기준 참고 가이드는 `{joined}`입니다."
                else:
                    answer = f"문서 기준 참고 가이드 관련 직접 근거는 `{guide_lines[0]}`입니다."
                return (answer, guide_lines[:3], best_source)
            return None

        if wants_key_personnel:
            personnel_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line.lower() for marker in ["핵심투입인력", "핵심 인력", "사업관리자", "pm", "대표사 소속"])
                ),
                "",
            )
            if personnel_line:
                personnel_match = re.search(
                    r"(사업관리자\s*\(?.{0,10}pm\)?.{0,12}1명|pm\s*1명|핵심투입인력.{0,16}1명)",
                    personnel_line,
                    re.IGNORECASE,
                )
                personnel_value = re.sub(r"\s+", " ", personnel_match.group(1)).strip() if personnel_match else ""
                answer = (
                    f"문서 기준 핵심투입인력 지정 기준은 `{personnel_value}`입니다."
                    if personnel_value
                    else f"문서 기준 핵심투입인력 관련 직접 근거는 `{personnel_line}`입니다."
                )
                personnel_evidence = [
                    line
                    for line, _src in ranked
                    if any(marker in line.lower() for marker in ["핵심투입인력", "핵심 인력", "사업관리자", "pm", "대표사 소속"])
                ]
                return (answer, personnel_evidence[:3] if personnel_evidence else [personnel_line], best_source)
            return None

        if wants_cpu_spec:
            cpu_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line.lower() for marker in ["cpu", "xeon", "intel", "ghz", "core"])
                ),
                "",
            )
            if cpu_line:
                spec_match = re.search(
                    r"(\d+\s*[xX]\s*\d+(?:\.\d+)?\s*GHz[^,;\n]*(?:Xeon|Core)[^,;\n]*)",
                    cpu_line,
                    re.IGNORECASE,
                )
                fallback_match = re.search(r"(\d+\s*CPU\s*(?:이상|이하)?)", cpu_line, re.IGNORECASE)
                value = ""
                if spec_match:
                    value = re.sub(r"\s+", " ", spec_match.group(1)).strip()
                elif fallback_match:
                    value = re.sub(r"\s+", " ", fallback_match.group(1)).strip()
                answer = (
                    f"문서 기준 CPU 최소 사양은 `{value}`입니다."
                    if value
                    else f"문서 기준 CPU 사양 관련 직접 근거는 `{cpu_line}`입니다."
                )
                cpu_evidence = [
                    line
                    for line, _src in ranked
                    if any(marker in line.lower() for marker in ["cpu", "xeon", "intel", "ghz", "core"])
                ]
                return (answer, cpu_evidence[:3] if cpu_evidence else [cpu_line], best_source)

        if wants_dimension:
            dim_lines = [
                line
                for line, _src in ranked
                if any(marker in line for marker in ["최소규격", "최대규격", "가로", "세로", "치수", "도면", "mm"])
            ]
            if dim_lines:
                min_line = next((line for line in dim_lines if "최소규격" in line), "")
                max_line = next((line for line in dim_lines if "최대규격" in line), "")
                mm_pattern = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*mm", re.IGNORECASE)
                min_vals = mm_pattern.findall(min_line) if min_line else []
                max_vals = mm_pattern.findall(max_line) if max_line else []
                if min_vals or max_vals:
                    parts: list[str] = []
                    if min_vals:
                        parts.append(f"최소규격: {' / '.join(min_vals[:4])}")
                    if max_vals:
                        parts.append(f"최대규격: {' / '.join(max_vals[:4])}")
                    answer = f"문서 기준 치수는 `{'; '.join(parts)}`입니다."
                else:
                    answer = f"문서 기준 치수 관련 직접 근거는 `{dim_lines[0]}`입니다."
                return (answer, dim_lines[:3], best_source)

        if wants_goal:
            goal_lines: list[str] = []
            seen_goal: set[str] = set()
            for line, _src in ranked:
                if not any(marker in line for marker in ["추진목표", "추진 목표", "사업목적", "목표", "목적"]):
                    continue
                if len(line) < 12:
                    continue
                if line in seen_goal:
                    continue
                seen_goal.add(line)
                goal_lines.append(line)
                if len(goal_lines) >= 3:
                    break
            if goal_lines:
                return ("문서 기준 추진 목표는 다음과 같습니다.", goal_lines, best_source)

        if wants_list_fact:
            list_markers = ["제출", "서류", "증빙", "증명", "준수", "절차", "제재", "위약", "하도급", "공동도급", "사본", "비밀정보"]
            list_lines: list[str] = []
            seen_list: set[str] = set()
            for line, _src in ranked:
                if not any(marker in line for marker in list_markers):
                    continue
                if line in seen_list:
                    continue
                seen_list.add(line)
                list_lines.append(line)
                if len(list_lines) >= 4:
                    break
            if len(list_lines) >= 2:
                answer = f"문서 기준 주요 제출서류/준수사항은 다음 {len(list_lines)}개 항목입니다."
                return (answer, list_lines, best_source)

        if wants_eval_threshold:
            threshold_line = next(
                (
                    line
                    for line, _src in ranked
                    if (
                        re.search(r"85\s*%", line)
                        or ("협상적격" in line and "평가" in line)
                        or ("기술능력" in line and ("배점한도" in line or "이상" in line))
                    )
                ),
                "",
            )
            if threshold_line:
                match = re.search(r"85\s*%", threshold_line)
                value = match.group(0).replace(" ", "") if match else ""
                answer = (
                    f"문서 기준 협상적격자 선정 기준은 `기술능력 평가점수 배점한도의 {value} 이상`입니다."
                    if value
                    else f"문서 기준 협상적격자 선정 관련 직접 근거는 `{threshold_line}`입니다."
                )
                threshold_evidence = [
                    line
                    for line, _src in ranked
                    if re.search(r"85\s*%", line) or "협상적격" in line or "기술능력" in line
                ]
                return (answer, threshold_evidence[:3] if threshold_evidence else [threshold_line], best_source)

        if wants_budget:
            budget_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in budget_markers) and budget_value_pattern.search(line)
                ),
                "",
            )
            if not budget_line:
                budget_line = next((line for line, _src in ranked if budget_value_pattern.search(line)), "")

            if budget_line:
                match = budget_value_pattern.search(budget_line)
                value = re.sub(r"\s+", " ", match.group(0)).strip() if match else ""
                answer = (
                    f"문서 기준 사업비는 `{value}`입니다."
                    if value
                    else f"문서 기준 사업비 관련 직접 근거는 `{budget_line}`입니다."
                )
                budget_evidence = [
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in budget_markers) or budget_value_pattern.search(line)
                ]
                return (answer, budget_evidence[:3] if budget_evidence else [budget_line], best_source)

            # 문서 라인 추출이 실패하면 기관 레지스트리의 금액(수집 메타데이터)으로 보완한다.
            org_info = self.vector_store.org_registry.get(target_org) if target_org else None
            if org_info and org_info.amount_numeric > 0:
                amount_text = format_amount(org_info.amount_numeric)
                meta_value = (org_info.amount or "").strip() or f"{int(org_info.amount_numeric):,}원"
                source_line = self._format_first_source(self._filter_results_by_org(results, target_org))
                answer = f"{target_org} 사업비는 `{amount_text}`입니다."
                evidence = [f"등록된 사업 금액 메타데이터: {meta_value}"]
                return (answer, evidence, source_line)

        if wants_owner:
            owner_line = next(
                (
                    line
                    for line, _src in ranked
                    if owner_marker_pattern.search(line) and (not owner_focus_terms or any(term in line for term in owner_focus_terms))
                ),
                "",
            )
            if not owner_line:
                owner_line = next((line for line, _src in ranked if owner_marker_pattern.search(line)), "")
            if not owner_line:
                return None
            subject = ""
            if any(marker in owner_line for marker in ["주사업자", "사업자", "제안사", "수급자", "계약상대자", "계약상대"]):
                subject = "사업자(제안사/주사업자)"
            elif any(marker in owner_line for marker in ["발주자", "발주기관", "발주처", "주관기관"]):
                subject = "발주자/발주기관"
            match = owner_subject_pattern.search(owner_line)
            if match and not subject:
                subject = re.sub(r"\s+", " ", match.group(1)).strip(" -:")
            invalid_subject = (
                len(subject) < 2
                or len(subject) > 24
                or bool(re.search(r"\d", subject))
                or any(marker in subject for marker in ["퇴직", "기간", "기한", "이내", "월", "일", "시간"])
            )
            if subject:
                if invalid_subject:
                    answer = f"문서 기준 책임/부담 관련 직접 근거는 `{owner_line}`입니다."
                else:
                    answer = f"문서 기준 책임 주체는 `{subject}`로 확인됩니다."
            else:
                answer = f"문서 기준 책임/부담 관련 직접 근거는 `{owner_line}`입니다."
            owner_evidence = [
                line
                for line, _src in ranked
                if owner_marker_pattern.search(line) and (not owner_focus_terms or any(term in line for term in owner_focus_terms))
            ]
            if not owner_evidence:
                owner_evidence = [line for line, _src in ranked if owner_marker_pattern.search(line)]
            if owner_evidence:
                evidence = owner_evidence[:3]
            return (answer, evidence, best_source)

        if wants_text_value:
            charset_line = next((line for line, _src in ranked if charset_pattern.search(line)), "")
            if charset_line:
                match = charset_pattern.search(charset_line)
                value = match.group(1).upper().replace(" ", "") if match else ""
                answer = (
                    f"문서 기준 우선 문자셋은 `{value}`입니다."
                    if value
                    else f"문서 기준 문자셋 관련 직접 근거는 `{charset_line}`입니다."
                )
                charset_evidence = [line for line, _src in ranked if charset_pattern.search(line)]
                if charset_evidence:
                    evidence = charset_evidence[:3]
                return (answer, evidence, best_source)
            keyword_line = next(
                (
                    line for line, _src in ranked
                    if any(marker in line.lower() for marker in ["문자셋", "인코딩", "charset", "utf"])
                ),
                "",
            )
            if keyword_line:
                answer = f"문서 기준 문자셋 관련 직접 근거는 `{keyword_line}`입니다."
                return (answer, [keyword_line], best_source)
            return None

        if wants_capacity:
            capacity_line = next(
                (
                    line
                    for line, _src in ranked
                    if re.search(r"\d+\s*(MB|GB|KB)", line, re.IGNORECASE)
                    and (any(token in line.lower() for token in focus_tokens) or any(marker in line for marker in ["용량", "페이지"]))
                ),
                "",
            )
            if not capacity_line:
                capacity_line = next((line for line, _src in ranked if re.search(r"\d+\s*(MB|GB|KB)", line, re.IGNORECASE)), "")
            if capacity_line:
                match = re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(MB|GB|KB)", capacity_line, re.IGNORECASE)
                value = match.group(0).replace(" ", "") if match else ""
                answer = (
                    f"문서 기준 용량 값은 `{value}`입니다."
                    if value
                    else f"문서 기준 용량 관련 직접 근거는 `{capacity_line}`입니다."
                )
                return (answer, [capacity_line], best_source)
            return None

        if wants_unit_quantity:
            if "직무교육" in normalized_query:
                job_line = next(
                    (
                        line
                        for line, _src in ranked
                        if "직무교육" in line and re.search(r"\d{1,3}(?:,\d{3})*\s*명", line)
                    ),
                    "",
                )
                if job_line:
                    job_match = re.search(r"직무교육[^0-9]{0,80}(\d{1,3}(?:,\d{3})*)\s*명", job_line)
                    if not job_match:
                        job_match = re.search(r"(\d{1,3}(?:,\d{3})*)\s*명[^0-9]{0,30}직무교육", job_line)
                    value = f"{job_match.group(1)}명" if job_match else ""
                    answer = (
                        f"문서 기준 직무교육 대상 인원은 `{value}`입니다."
                        if value
                        else f"문서 기준 직무교육 인원 관련 직접 근거는 `{job_line}`입니다."
                    )
                    return (answer, [job_line], best_source)

            pair_pattern = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(명|건|개|회|MB|GB|KB)", re.IGNORECASE)
            table_line = next(
                (
                    line
                    for line, _src in ranked
                    if line.count("|") >= 2 and pair_pattern.search(line)
                    and (not focus_tokens or any(token in line.lower() for token in focus_tokens))
                ),
                "",
            )
            if not table_line:
                table_line = next((line for line, _src in ranked if pair_pattern.search(line)), "")
            if table_line:
                pair = pair_pattern.search(table_line)
                value = f"{pair.group(1)}{pair.group(2)}" if pair else ""
                answer = (
                    f"문서 기준 단위/수량 값은 `{value}`입니다."
                    if value
                    else f"문서 기준 단위/수량 관련 직접 근거는 `{table_line}`입니다."
                )
                return (answer, [table_line], best_source)
            return None

        if wants_education:
            freq_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in ["정보보안교육", "보안교육", "교육"])
                    and re.search(r"(월|주|일)\s*\d+\s*회|\d+\s*회", line)
                ),
                "",
            )
            if freq_line:
                freq_match = re.search(r"(월|주|일)\s*\d+\s*회|\d+\s*회", freq_line)
                value = re.sub(r"\s+", "", freq_match.group(0)) if freq_match else ""
                answer = (
                    f"문서 기준 정보보안교육 주기는 `{value}`입니다."
                    if value
                    else f"문서 기준 정보보안교육 주기 관련 직접 근거는 `{freq_line}`입니다."
                )
                return (answer, [freq_line], best_source)

        if wants_recovery_deadline:
            recovery_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in ["복구", "장애"])
                    and (deadline_pattern.search(line) or "이내" in line)
                ),
                "",
            )
            if recovery_line:
                match = re.search(r"\d+\s*(시간|일|주|개월)\s*(이내|이상|이하)?", recovery_line, re.IGNORECASE)
                value = match.group(0).replace(" ", "") if match else ""
                answer = (
                    f"문서 기준 복구기한은 `{value}`입니다."
                    if value
                    else f"문서 기준 복구기한 관련 직접 근거는 `{recovery_line}`입니다."
                )
                return (answer, [recovery_line], best_source)
            return None

        if wants_requirement:
            req_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in requirement_markers)
                    and (
                        any(self._normalize_text_for_match(code) in self._normalize_text_for_match(line) for code in req_codes)
                        or "가용성" in line
                        or "무중단" in line
                    )
                ),
                "",
            )
            if not req_line and req_codes:
                req_line = next(
                    (
                        line
                        for line, _src in ranked
                        if any(
                            self._normalize_text_for_match(code) in self._normalize_text_for_match(line)
                            for code in req_codes
                        )
                    ),
                    "",
            )
            if not req_line:
                req_line = next((line for line, _src in ranked if any(marker in line for marker in requirement_markers)), best_line)
            availability_line = next(
                (
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in ["24시간", "무중단", "정상상태", "매일"])
                ),
                "",
            )
            if availability_line and availability_line != req_line:
                answer = f"문서 기준 운영 요구사항은 `{availability_line}` 및 `{req_line}`입니다."
            else:
                answer = f"문서 기준 운영 요구사항은 `{req_line}`입니다."
            requirement_evidence = [
                line
                for line, _src in ranked
                if any(marker in line for marker in requirement_markers)
            ]
            if requirement_evidence:
                evidence = requirement_evidence[:3]
            return (answer, evidence, best_source)

        if wants_deadline:
            if wants_recovery_deadline:
                deadline_line = next(
                    (
                        line
                        for line, _src in ranked
                        if ("복구" in line or "장애" in line)
                        and ("시간" in line or "이내" in line)
                        and deadline_pattern.search(line)
                    ),
                    "",
                )
                if not deadline_line:
                    deadline_line = next(
                        (
                            line
                            for line, _src in ranked
                            if "복구" in line and deadline_pattern.search(line)
                        ),
                        "",
                    )
            elif wants_project_period:
                deadline_line = next(
                    (
                        line
                        for line, _src in ranked
                        if any(marker in line for marker in ["사업기간", "계약체결일"])
                        and deadline_pattern.search(line)
                    ),
                    "",
                )
                if not deadline_line:
                    deadline_line = next(
                        (
                            line
                            for line, _src in ranked
                            if "개월" in line and ("계약" in line or "사업기간" in line)
                        ),
                        "",
                    )
            else:
                deadline_line = ""

            if not deadline_line:
                deadline_line = next(
                    (
                        line
                        for line, _src in ranked
                        if deadline_pattern.search(line) or any(marker in line for marker in deadline_focus_markers)
                    ),
                    best_line,
                )
            match = deadline_pattern.search(deadline_line)
            value = match.group(1).strip() if match else ""
            answer = (
                f"문서 기준 기한/일정 값은 `{value}`입니다."
                if value
                else f"문서 기준 기한/일정 관련 직접 근거는 `{deadline_line}`입니다."
            )
            deadline_evidence = [
                line
                for line, _src in ranked
                if deadline_pattern.search(line) or any(marker in line for marker in deadline_focus_markers)
            ]
            if deadline_evidence:
                evidence = deadline_evidence[:3]
            return (answer, evidence, best_source)

        if wants_numeric:
            if wants_education:
                numeric_line = next(
                    (
                        line
                        for line, _src in ranked
                        if numeric_pattern.search(line)
                        and any(marker in line for marker in education_core_markers)
                    ),
                    "",
                )
            else:
                numeric_line = ""
            if not numeric_line:
                numeric_line = next(
                    (
                        line
                        for line, _src in ranked
                        if numeric_pattern.search(line)
                        and (any(marker in line for marker in unit_markers) or any(marker in line for marker in numeric_focus_markers))
                    ),
                    "",
                )
            if not numeric_line:
                numeric_line = next((line for line, _src in ranked if numeric_pattern.search(line)), best_line)
            match = numeric_pattern.search(numeric_line)
            value = match.group(1).strip() if match else ""
            answer = (
                f"문서 기준 값은 `{value}`입니다."
                if value
                else f"문서의 직접 근거 문구는 `{numeric_line}`입니다."
            )
            if wants_education:
                numeric_evidence = [
                    line
                    for line, _src in ranked
                    if any(marker in line for marker in education_core_markers) and numeric_pattern.search(line)
                ]
            else:
                numeric_evidence = [
                    line
                    for line, _src in ranked
                    if numeric_pattern.search(line)
                    and (any(marker in line for marker in unit_markers) or any(marker in line for marker in numeric_focus_markers))
                ]
            if numeric_evidence:
                evidence = numeric_evidence[:3]
            return (answer, evidence, best_source)

        return (f"문서의 직접 근거 문구는 `{best_line}`입니다.", evidence, best_source)

    @staticmethod
    def _looks_uncertain_answer(answer: str) -> bool:
        """답변이 과도한 보수적 거절 형태인지 판별."""
        if not answer:
            return True
        lowered = answer.lower()
        signals = [
            "문서에 명시되어 있지",
            "찾지 못했",
            "확인되지 않",
            "단정할 수 없",
            "직접 명시한 조항을 찾지 못",
            "명시적 언급이 없",
        ]
        return any(sig in lowered for sig in signals)

    @staticmethod
    def _infer_responsibility_owner(evidence_lines: list[str]) -> str:
        """근거 문구에서 책임 주체를 휴리스틱으로 추론합니다."""
        joined = "\n".join(evidence_lines)
        if any(k in joined for k in ["제안사", "사업자", "수급자", "계약상대자", "용역수행자"]):
            return "사업자(제안사/수급자) 부담"
        if any(k in joined for k in ["발주기관", "발주처", "주관기관", "학교"]):
            return "발주기관 부담"
        if any(k in joined for k in ["공동", "협의", "별도 협의"]):
            return "양측 협의 또는 공동 부담"
        return "문서상 명시된 문구 해석 필요 (단정 불가)"

    def _expand_query_terms(self, query: str) -> list[str]:
        """질문 의미를 보강하는 확장 질의를 생성합니다."""
        expanded = [query]
        q = unicodedata.normalize("NFKC", query.lower())
        if any(k in q for k in ["저작권", "라이선스", "사용권", "폰트", "글꼴", "이미지", "부담", "책임"]):
            expanded.append(f"{query} 저작권 라이선스 사용권 비용 부담 책임")
        if any(k in q for k in ["소유권", "귀속", "비밀정보", "지식재산", "지적재산"]):
            expanded.append(f"{query} 소유권 귀속 비밀정보 지식재산 지적재산")
        if any(k in q for k in ["기간", "마감", "일자", "언제"]):
            expanded.append(f"{query} 입찰 시작일 입찰 마감일 사업 기간")
        if any(k in q for k in ["요구사항", "조건", "자격"]):
            expanded.append(f"{query} 요구사항 조건 자격")
        if any(k in q for k in ["표", "항목", "조항", "근거", "문구", "단위", "수량"]):
            expanded.append(f"{query} 조항 근거 문구 표 항목")
        if any(k in q for k in ["복구", "기한", "시간", "이내", "장애"]):
            expanded.append(f"{query} 이내 복구 시간 가용성")
        if any(k in q for k in ["가용성", "무중단", "운영", "24시간"]):
            expanded.append(f"{query} 가용성 무중단 24시간 운영 요구사항")
        if self._is_budget_query(query):
            expanded.append(f"{query} 사업비 예산 금액 총사업비 부가가치세 포함")
        codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q, flags=re.IGNORECASE)
        for code in codes[:3]:
            expanded.append(f"{query} {code} 요구사항 기준 조항")
        if any(k in q for k in ["문자셋", "인코딩", "utf", "charset"]):
            expanded.append(f"{query} UTF-8 UTF8 EUC-KR CP949 charset 인코딩 우선 적용")
        if codes and any(k in q for k in ["가용성", "운영", "보안", "요구사항", "요건"]):
            expanded.append(f"{query} 운영 요구사항 가용성 무중단 24시간 보장")
        if any(k in q for k in ["용량", "mb", "gb"]):
            expanded.append(f"{query} 용량 MB GB 이내")
        if any(k in q for k in ["주기", "자주", "횟수", "교육"]):
            expanded.append(f"{query} 월 주기 횟수 교육")
        if any(k in q for k in ["윤리", "제재", "담합", "뇌물", "재고", "거래", "전송"]):
            expanded.append(f"{query} 윤리 제재 담합 뇌물 재고 거래 전송 기록 기능")
        if any(k in q for k in ["보안", "ser", "접근", "암호화", "비밀번호"]):
            expanded.append(f"{query} 보안 접근통제 암호화 비밀번호 인증 로그")
        if any(k in q for k in ["가이드", "guideline", "guide"]):
            expanded.append(f"{query} Guidelines Guide")
        if any(k in q for k in ["협상", "평가", "배점", "적격"]):
            expanded.append(f"{query} 협상적격자 기술능력 배점한도 85% 기준")

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in expanded:
            normalized = unicodedata.normalize("NFKC", candidate.strip())
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(candidate.strip())

        cap = self._resolve_expansion_cap(query)
        return deduped[:cap]

    def _resolve_expansion_cap(self, query: str) -> int:
        """질의 유형에 따라 확장 질의 개수 상한을 결정합니다."""
        cap = max(1, RETRIEVAL_EXPANSION_CAP)
        normalized = unicodedata.normalize("NFKC", query.lower())
        has_req_code = bool(re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized, flags=re.IGNORECASE))
        is_security = any(
            token in normalized for token in ["보안", "접근", "암호화", "비밀번호", "취약", "가용성", "무중단"]
        )
        is_comparison = self._is_comparison_query(query)
        if has_req_code or is_security:
            cap = max(cap, 5)
        if is_comparison:
            cap = min(cap, 2)
        if self._is_accuracy_mode_enabled() and self._is_precision_fact_query(query):
            cap = max(cap, 4)
        return cap

    def _has_source_diversity(
        self,
        results: list[dict[str, Any]],
        min_unique_sources: int = 2,
        top_n: int | None = None,
    ) -> bool:
        """상위 결과가 최소 source 다양성을 충족하는지 확인합니다."""
        if not results:
            return False
        candidates = results[:top_n] if top_n else results
        unique_sources = {
            str((item.get("metadata", {}) or {}).get("source", "")).strip()
            for item in candidates
            if str((item.get("metadata", {}) or {}).get("source", "")).strip()
        }
        return len(unique_sources) >= max(1, min_unique_sources)

    def _has_comparison_coverage(
        self,
        query: str,
        results: list[dict[str, Any]],
        min_docs_per_org: int = 2,
        explicit_orgs: list[str] | None = None,
    ) -> bool:
        """비교 질의에서 양측 기관 커버리지가 확보됐는지 확인합니다."""
        if not results:
            return False
        resolved_orgs = self._resolve_query_target_orgs(
            query,
            explicit_orgs=explicit_orgs or [],
            min_targets=2,
        )
        if len(resolved_orgs) < 2:
            return False

        coverage = {org: 0 for org in resolved_orgs[:2]}
        for item in results:
            md = item.get("metadata", {}) or {}
            org = str(md.get("org", "")).strip()
            if not org:
                org = str(md.get("source", "")).strip()
            if not org:
                continue
            for target in coverage:
                if self._org_names_loosely_match(org, target):
                    coverage[target] += 1
        return all(count >= min_docs_per_org for count in coverage.values())

    def _should_stop_retrieval_early(
        self,
        query: str,
        merged: list[dict[str, Any]],
        org_name: str | None,
        top_k: int,
        target_orgs: list[str] | None = None,
    ) -> bool:
        """검색 반복을 조기에 종료할지 판단합니다."""
        normalized = unicodedata.normalize("NFKC", query.lower())
        precision_critical = any(
            token in normalized for token in ["협상", "평가", "배점", "적격", "정보보안교육", "교육결과"]
        )
        if precision_critical:
            return False
        if self._is_precision_fact_query(query) and not self._has_precision_anchor_evidence(
            query,
            merged,
            top_n=max(12, top_k),
        ):
            return False
        is_comparison = self._is_comparison_query(query)
        is_multi_doc_like = any(token in normalized for token in ["및", "동시에", "공통", "차이", "준수사항", "절차", "제출서류"])
        if is_comparison and len(merged) < max(top_k * 2, 24):
            return False
        if is_multi_doc_like and len(merged) < max(top_k + 6, 24):
            return False
        if len(merged) < top_k:
            return False
        if self._is_budget_query(query) and not self._has_budget_evidence(merged, top_n=max(top_k, 12)):
            return False
        comparison_targets = self._resolve_query_target_orgs(query, explicit_orgs=target_orgs or [], min_targets=2)
        is_comparison_like = is_comparison or len(comparison_targets) >= 2 or is_multi_doc_like
        if is_comparison_like and self._has_comparison_coverage(
            query,
            merged,
            min_docs_per_org=1,
            explicit_orgs=comparison_targets[:2],
        ):
            return True
        if org_name:
            # 단일 기관 질의는 같은 source 내 페이지 단위 근거가 핵심이라 1개 source면 충분
            if self._is_budget_query(query):
                return self._has_budget_evidence(merged, top_n=max(top_k, 12))
            return self._has_source_diversity(merged, min_unique_sources=1, top_n=top_k)
        return self._has_source_diversity(merged, min_unique_sources=2, top_n=top_k)

    @staticmethod
    def _should_run_combined_fallback(
        merged: list[dict[str, Any]],
        query: str,
        top_k: int,
    ) -> bool:
        """2패스 검색 이후 통합 3패스 fallback 필요 여부를 판단합니다."""
        normalized = unicodedata.normalize("NFKC", query.lower())
        if any(token in normalized for token in ["협상", "평가", "배점", "적격", "정보보안교육", "교육결과"]):
            return True
        if RAGChatbotV17._is_budget_query(query) and not RAGChatbotV17._has_budget_evidence(
            merged, top_n=max(top_k, 12)
        ):
            return True
        if len(merged) < max(4, top_k // 2):
            return True
        if RAGChatbotV17._is_comparison_query(query):
            return len(merged) < top_k
        return False

    @staticmethod
    def _consume_hybrid_budget(perf_stats: dict[str, float | int | bool] | None) -> bool:
        """하이브리드 검색 호출 예산을 차감하고 호출 가능 여부를 반환합니다."""
        if perf_stats is None:
            return True
        remaining = int(perf_stats.get("hybrid_budget_remaining", RETRIEVAL_MAX_HYBRID_CALLS))
        if remaining <= 0:
            perf_stats["budget_exhausted"] = True
            return False
        perf_stats["hybrid_budget_remaining"] = remaining - 1
        return True

    def _record_hybrid_call_stats(self, perf_stats: dict[str, float | int | bool] | None) -> None:
        """VectorStore 하이브리드 검색 통계를 누적합니다."""
        if perf_stats is None:
            return
        perf_stats["hybrid_calls"] = int(perf_stats.get("hybrid_calls", 0)) + 1
        hybrid_meta = getattr(self.vector_store, "last_hybrid_stats", {}) or {}
        if hybrid_meta.get("keyword_used"):
            perf_stats["keyword_calls"] = int(perf_stats.get("keyword_calls", 0)) + 1

    def _run_retrieval_call(
        self,
        q: str,
        request_k: int,
        org_name: str | None,
        types: list[str],
        perf_stats: dict[str, float | int | bool] | None,
    ) -> list[dict[str, Any]]:
        """예산을 고려해 단일 검색 호출을 실행합니다."""
        search_hybrid_fn = getattr(self.vector_store, "search_hybrid", None)
        if callable(search_hybrid_fn):
            if not self._consume_hybrid_budget(perf_stats):
                return []
            results = search_hybrid_fn(
                q,
                top_k=request_k,
                org_name=org_name,
                doc_types=types,
            )
            self._record_hybrid_call_stats(perf_stats)
            return self._normalize_retrieval_results(results)

        search_fn = getattr(self.vector_store, "search")
        kwargs: dict[str, Any] = {}
        supports_org_filter = False
        supports_type_filter = False
        try:
            params = inspect.signature(search_fn).parameters
        except Exception:
            params = {}

        if "org_name" in params:
            kwargs["org_name"] = org_name
            supports_org_filter = True
        if "doc_types" in params:
            kwargs["doc_types"] = types
            supports_type_filter = True
        if "mode" in params:
            kwargs["mode"] = "dynamic"
        if "hybrid_alpha" in params:
            kwargs["hybrid_alpha"] = 0.6
        if "dynamic_hard_threshold" in params:
            kwargs["dynamic_hard_threshold"] = 2

        try:
            results = search_fn(q, top_k=request_k, **kwargs)
        except TypeError:
            results = search_fn(q, top_k=request_k)

        normalized = self._normalize_retrieval_results(results)
        if supports_org_filter and org_name and not normalized:
            # 백엔드 org 필터가 엄격 문자열 매칭일 때(정규화 차이) 공집합이 될 수 있어 재시도한다.
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("org_name", None)
            try:
                retry_results = search_fn(q, top_k=request_k, **retry_kwargs)
            except TypeError:
                retry_results = search_fn(q, top_k=request_k)
            retry_normalized = self._normalize_retrieval_results(retry_results)
            retry_filtered = self._apply_result_filters(retry_normalized, org_name=org_name, doc_types=types)
            if retry_filtered:
                return retry_filtered

        if supports_org_filter and supports_type_filter:
            return normalized
        return self._apply_result_filters(normalized, org_name=org_name, doc_types=types)

    def _retrieve_results(
        self,
        query: str,
        org_name: str | None,
        top_k: int,
        prefer_original: bool = False,
        doc_types: list[str] | None = None,
        target_orgs: list[str] | None = None,
        perf_stats: dict[str, float | int | bool] | None = None,
    ) -> list[dict[str, Any]]:
        """확장 질의 기반으로 검색 결과를 수집/병합합니다."""
        debug_timing = DEBUG_RETRIEVAL_TIMING
        started = time.perf_counter()
        merged: list[dict[str, Any]] = []
        primary_types = list(doc_types) if doc_types else ["pdf", "hwp"]
        pass_limit = max(1, RETRIEVAL_SEARCH_PASSES)
        per_call_k = max(8, int(top_k * 0.8))
        q_norm = unicodedata.normalize("NFKC", query.lower())
        precision_fact_query = self._is_precision_fact_query(query)
        high_recall_query = bool(re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q_norm, flags=re.IGNORECASE)) or any(
            token in q_norm
            for token in [
                "문자셋", "인코딩", "utf", "charset", "가용성", "무중단", "비교", "각각", "공통",
                "협상", "평가", "배점", "적격", "정보보안교육", "교육결과",
            ]
        )
        multiplier = max(0.5, RETRIEVAL_HIGH_RECALL_K_MULTIPLIER)
        early_stopped = False
        resolved_targets = self._resolve_query_target_orgs(query, explicit_orgs=target_orgs or [], min_targets=2)
        comparison_like = (
            org_name is None
            and (self._is_comparison_query(query) or len(resolved_targets) >= 2)
        )
        if self._is_accuracy_mode_enabled() and (precision_fact_query or comparison_like):
            pass_limit = max(pass_limit, 2)
        pass_limit = min(pass_limit, 3)
        max_global_expansions = 1 if comparison_like else 999

        for expanded_idx, q in enumerate(self._expand_query_terms(query), start=1):
            if expanded_idx > max_global_expansions:
                break
            for pass_idx in range(pass_limit):
                request_k = max(per_call_k, top_k // 2)
                if high_recall_query:
                    request_k = max(request_k, int(top_k * multiplier))
                if pass_idx > 0:
                    request_k = max(request_k, int(request_k * (1 + (0.35 * pass_idx))))

                call_types = list(primary_types)
                if pass_idx > 0 and not doc_types and precision_fact_query:
                    call_types = ["pdf", "hwp", "csv"]

                step_started = time.perf_counter()
                results = self._run_retrieval_call(
                    q,
                    request_k=request_k,
                    org_name=org_name,
                    types=call_types,
                    perf_stats=perf_stats,
                )
                if not results and perf_stats and perf_stats.get("budget_exhausted"):
                    break
                merged = self._merge_results(merged, results, top_k=top_k * 2)
                if debug_timing:
                    elapsed = time.perf_counter() - step_started
                    print(
                        f"[RETRIEVE] exp={expanded_idx} pass={pass_idx + 1}/{pass_limit} "
                        f"types={call_types} k={request_k} elapsed={elapsed:.3f}s merged={len(merged)}"
                    )
                if self._should_stop_retrieval_early(
                    query,
                    merged,
                    org_name=org_name,
                    top_k=top_k,
                    target_orgs=resolved_targets,
                ):
                    early_stopped = True
                    break
                if perf_stats and perf_stats.get("budget_exhausted"):
                    break
            if early_stopped or (perf_stats and perf_stats.get("budget_exhausted")):
                break

        # CSV 보강 패스는 조건 충족 시에만 단일 호출로 수행
        if (
            not doc_types
            and not early_stopped
            and (
                len(merged) < max(4, top_k // 2)
                or not self._has_source_diversity(merged, min_unique_sources=2, top_n=top_k)
            )
        ):
            csv_started = time.perf_counter()
            csv_k = max(8, top_k // 2)
            csv_results = self._run_retrieval_call(
                query,
                request_k=csv_k,
                org_name=org_name,
                types=["csv"],
                perf_stats=perf_stats,
            )
            if csv_results:
                merged = self._merge_results(merged, csv_results, top_k=top_k * 2)
            if debug_timing:
                elapsed = time.perf_counter() - csv_started
                print(f"[RETRIEVE] csv pass types=['csv'] k={csv_k} elapsed={elapsed:.3f}s merged={len(merged)}")

        if perf_stats and perf_stats.get("budget_exhausted"):
            early_stopped = True

        if (
            not doc_types
            and not early_stopped
            and (
                self._should_run_combined_fallback(merged, query=query, top_k=top_k)
                or (precision_fact_query and not self._has_precision_anchor_evidence(query, merged, top_n=max(top_k, 14)))
            )
            and (not comparison_like or len(merged) < max(6, top_k // 2))
        ):
            fallback_started = time.perf_counter()
            precision_query = any(token in q_norm for token in ["협상", "평가", "배점", "적격", "정보보안교육", "교육결과"])
            if precision_query:
                fallback_boost = 2.0
            elif high_recall_query:
                fallback_boost = 1.4
            else:
                fallback_boost = 1.2
            fallback_k = max(top_k, int(top_k * max(multiplier, fallback_boost)))
            fallback_results = self._run_retrieval_call(
                query,
                request_k=fallback_k,
                org_name=org_name,
                types=["pdf", "hwp", "csv"],
                perf_stats=perf_stats,
            )
            merged = self._merge_results(merged, fallback_results, top_k=top_k * 2)
            if debug_timing:
                elapsed = time.perf_counter() - fallback_started
                print(
                    f"[RETRIEVE] fallback pass types=['pdf', 'hwp', 'csv'] "
                    f"k={fallback_k} elapsed={elapsed:.3f}s merged={len(merged)}"
                )

        reranked = self._rerank_results(query, merged, org_name=org_name, prefer_original=prefer_original)
        if self._is_comparison_query(query):
            reranked = self._diversify_comparison_results(reranked, top_window=max(10, top_k))
        if debug_timing:
            total = time.perf_counter() - started
            budget_exhausted = bool(perf_stats and perf_stats.get("budget_exhausted"))
            print(
                f"[RETRIEVE] total elapsed={total:.3f}s merged={len(merged)} "
                f"reranked={len(reranked)} early_stop={early_stopped} budget_exhausted={budget_exhausted}"
            )
        return reranked[:top_k]

    @staticmethod
    def _diversify_comparison_results(results: list[dict[str, Any]], top_window: int = 10) -> list[dict[str, Any]]:
        """비교 질의에서 상위 구간의 기관 편중을 완화합니다."""
        if len(results) <= 2:
            return results

        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            org = str((item.get("metadata", {}) or {}).get("org", "")).strip()
            key = org or str((item.get("metadata", {}) or {}).get("source", "")).strip()
            buckets.setdefault(key, []).append(item)

        if len(buckets) < 2:
            return results

        top_orgs = sorted(
            buckets.keys(),
            key=lambda k: len(buckets[k]),
            reverse=True,
        )[:2]
        selected: list[dict[str, Any]] = []
        used_ids: set[int] = set()
        round_limit = min(max(2, top_window), len(results))
        while len(selected) < round_limit:
            progressed = False
            for org in top_orgs:
                while buckets[org]:
                    candidate = buckets[org].pop(0)
                    cid = id(candidate)
                    if cid in used_ids:
                        continue
                    selected.append(candidate)
                    used_ids.add(cid)
                    progressed = True
                    break
                if len(selected) >= round_limit:
                    break
            if not progressed:
                break

        for item in results:
            cid = id(item)
            if cid in used_ids:
                continue
            selected.append(item)
            used_ids.add(cid)
        return selected

    def _rerank_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        org_name: str | None,
        prefer_original: bool,
    ) -> list[dict[str, Any]]:
        """질문 키워드/기관 일치도를 기준으로 검색 결과를 재정렬합니다."""
        if not results:
            return []

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for idx, item in enumerate(results):
            score = self._score_result(query, item, org_name=org_name, prefer_original=prefer_original)
            scored.append((score, idx, item))

        scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        return [item for _, _, item in scored]

    def _score_result(
        self,
        query: str,
        item: dict[str, Any],
        org_name: str | None,
        prefer_original: bool,
    ) -> float:
        md = item.get("metadata", {}) or {}
        text = str(item.get("text", "") or "")
        source = str(md.get("source", "") or "")
        doc_type = str(md.get("type", "") or "")
        org = str(md.get("org", "") or "")

        text_key = self._normalize_text_for_match(text)
        source_key = self._normalize_text_for_match(source)
        org_key = self._normalize_text_for_match(org)
        org_query_key = self._normalize_text_for_match(org_name or "")
        query_key = self._normalize_text_for_match(query)
        keywords = self._extract_query_keywords(query)

        score = 0.0
        if prefer_original:
            score += 1.2 if doc_type in {"pdf", "hwp"} else -2.0
        if org_query_key and org_key and org_query_key == org_key:
            score += 5.0
        elif org_query_key and org_key and org_query_key in org_key:
            score += 3.0

        for keyword in keywords:
            if keyword in text_key:
                score += 1.4
            if keyword in source_key:
                score += 0.8

        q_norm = unicodedata.normalize("NFKC", query.lower())
        req_codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q_norm, flags=re.IGNORECASE)
        has_req_code_match = False
        for code in req_codes:
            code_key = self._normalize_text_for_match(code)
            if not code_key:
                continue
            if code_key in text_key:
                score += 2.4
                has_req_code_match = True
            if code_key in source_key:
                score += 1.0

        if query_key and query_key in text_key:
            score += 1.0
        if md.get("page") is not None:
            score += 1.1
        if re.search(r"\d", text):
            score += 0.2

        if any(token in q_norm for token in ["얼마", "수량", "단위", "기한", "마감", "언제", "시간", "용량"]):
            if re.search(r"\d+\s*(원|억|만|명|건|개|일|시간|분|mb|gb|kb|%)", text, re.IGNORECASE):
                score += 1.4
            if any(marker in text for marker in ["이내", "마감", "기한", "주기", "횟수"]):
                score += 0.7
            focus_terms = self._extract_focus_terms_for_fact(query, max_terms=6)
            if focus_terms and re.search(r"\d", text):
                lowered_text = unicodedata.normalize("NFKC", text.lower())
                if not any(term in lowered_text for term in focus_terms):
                    score -= 1.4
        if any(token in q_norm for token in ["용량", "mb", "gb", "kb"]):
            if re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(mb|gb|kb)", text, re.IGNORECASE):
                score += 3.0
            if "웹페이지" in q_norm and "웹페이지" in text:
                score += 2.5
            if "웹페이지" in q_norm and "웹페이지" not in text and re.search(r"\d", text):
                score -= 1.2

        if self._is_budget_query(query):
            budget_markers = ["사업비", "총사업비", "예산", "사업 금액", "사 업 비", "금액", "부가가치세"]
            has_budget_marker = any(marker in text for marker in budget_markers)
            has_budget_value = bool(
                re.search(
                    r"(금\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(천원|백만원|만원|억원|원)",
                    text,
                    re.IGNORECASE,
                )
            )
            if has_budget_marker:
                score += 2.6
            if has_budget_value:
                score += 2.1
            if has_budget_marker and has_budget_value:
                score += 1.0
            if re.search(r"\d+\s*(분|시간|초)", text) and not has_budget_value:
                score -= 1.5

        if any(token in q_norm for token in ["누가", "책임", "부담", "소유권", "귀속"]):
            if any(marker in text for marker in ["제안사", "사업자", "수급자", "발주기관", "발주처", "주관기관", "귀속", "소유권"]):
                score += 1.5
        if any(token in q_norm for token in ["가용성", "무중단", "운영"]):
            if any(marker in text for marker in ["가용성", "무중단", "24시간", "연중", "중단", "운영"]):
                score += 1.5
        if any(token in q_norm for token in ["문자셋", "인코딩", "utf", "charset"]):
            if re.search(r"(utf[-\s]?8|euc[-\s]?kr|cp949|utf[-\s]?16|ascii)", text, re.IGNORECASE):
                score += 2.0
            if any(marker in text for marker in ["우선 적용", "기본 문자셋", "신규시스템"]):
                score += 1.0

        req_codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q_norm, flags=re.IGNORECASE)
        if req_codes:
            req_markers = ["요구사항", "요건", "운영", "가용성", "무중단", "24시간", "보장", "접근제어", "암호화", "취약성"]
            if any(marker in text for marker in req_markers):
                score += 1.6
            normalized_text = self._normalize_text_for_match(text)
            for code in req_codes:
                code_key = self._normalize_text_for_match(code)
                if code_key and code_key in normalized_text:
                    score += 2.8
                    has_req_code_match = True
            if has_req_code_match:
                score += 1.2
            elif any(marker in text for marker in ["일반사항", "보안총칙", "기밀", "비밀유지", "총칙"]):
                score -= 2.0

        if self._is_comparison_query(query):
            if doc_type in {"pdf", "hwp"}:
                score += 0.6
            if any(marker in text for marker in ["비교", "차이", "각각", "공통", "반면"]):
                score += 0.5

        if any(token in q_norm for token in ["협상", "적격", "배점", "기술능력", "평가점수"]):
            if any(marker in text for marker in ["협상적격", "배점한도", "기술능력평가", "기술능력 평가"]):
                score += 2.2
            if re.search(r"85\s*%", text):
                score += 3.2

        return score

    @staticmethod
    def _result_key(item: dict[str, Any]) -> tuple[str, str, int | None, str, str]:
        md = item.get("metadata", {}) or {}
        return (
            str(md.get("source", "")),
            str(md.get("org", "")),
            md.get("page"),
            str(md.get("type", "")),
            str(md.get("section", "")),
        )

    def _merge_results(
        self,
        base: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """중복 제거하며 검색 결과를 병합합니다."""
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int | None, str, str]] = set()
        for item in [*base, *incoming]:
            key = self._result_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= top_k:
                break
        return merged

    @staticmethod
    def _needs_original_priority(query: str) -> bool:
        """원본 문서 기반 검색을 우선해야 하는 질의인지 판단합니다."""
        q = query.lower()
        keywords = [
            "사업비", "총사업비", "예산", "금액", "부가가치세",
            "저작권", "라이선스", "사용권", "책임", "부담", "지적재산", "이미지", "글꼴",
            "요구사항", "평가기준", "제안요청", "과업", "조항", "문구", "근거", "표",
            "단위", "수량", "주기", "횟수", "자주", "기한", "복구", "용량", "가이드",
        ]
        return any(k in q for k in keywords)

    @staticmethod
    def _is_budget_query(query: str) -> bool:
        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        hard_markers = ["사업비", "총사업비", "사 업 비", "사업 금액", "부가가치세"]
        if any(marker in normalized for marker in hard_markers):
            return True

        if "금액" in normalized and any(token in normalized for token in ["얼마", "금액은", "금액이", "예산"]):
            return True
        if "예산" in normalized:
            if re.search(r"예산\s*(은|는|이|가|규모|금액|얼마)", normalized):
                return True
            if "얼마" in normalized and "예산회계" not in normalized:
                return True
        return False

    @staticmethod
    def _is_accuracy_mode_enabled() -> bool:
        """정확도 우선 모드 활성 여부를 반환합니다."""
        mode = unicodedata.normalize("NFKC", str(ANSWER_QUALITY_MODE or "").strip().lower())
        return mode in {"accurate", "quality", "high_accuracy", "high-accuracy"}

    @staticmethod
    def _is_precision_fact_query(query: str) -> bool:
        """숫자/단위/문자셋/복구기한/요구사항 코드 등 정밀 사실 질의 여부."""
        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        if re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized, flags=re.IGNORECASE):
            return True
        precision_tokens = [
            "복구", "장애", "문자셋", "인코딩", "utf", "charset",
            "용량", "mb", "gb", "kb", "단위", "수량",
            "직무교육", "핵심투입인력", "핵심 인력", "사업관리자", "pm",
            "가이드", "guideline", "guide",
            "가용성", "무중단", "요구사항", "요건",
        ]
        return any(token in normalized for token in precision_tokens)

    def _has_precision_anchor_evidence(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_n: int = 12,
    ) -> bool:
        """정밀 사실 질의에서 핵심 앵커 근거(코드/단위/기한/문자셋 등)가 확보됐는지 판별합니다."""
        if not results:
            return False
        normalized = unicodedata.normalize("NFKC", (query or "").lower())
        codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized, flags=re.IGNORECASE)
        code_keys = [self._normalize_text_for_match(code) for code in codes if code]

        for item in results[: max(1, top_n)]:
            text = str(item.get("text", "") or "")
            if not text:
                continue
            lowered = unicodedata.normalize("NFKC", text.lower())
            text_key = self._normalize_text_for_match(lowered)

            if code_keys and any(code_key and code_key in text_key for code_key in code_keys):
                return True
            if any(token in normalized for token in ["문자셋", "인코딩", "utf", "charset"]) and re.search(
                r"(utf[-\s]?8|euc[-\s]?kr|cp949|utf[-\s]?16|ascii)", text, re.IGNORECASE
            ):
                return True
            if any(token in normalized for token in ["복구", "장애"]) and re.search(
                r"(복구|장애).{0,28}\d+\s*(시간|일|주|개월)\s*(이내|이상|이하)?",
                text,
                re.IGNORECASE,
            ):
                return True
            if any(token in normalized for token in ["용량", "mb", "gb", "kb"]) and re.search(
                r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(mb|gb|kb)",
                text,
                re.IGNORECASE,
            ):
                return True
            if any(token in normalized for token in ["수량", "단위", "직무교육"]) and re.search(
                r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(명|건|개|회|mb|gb|kb)",
                text,
                re.IGNORECASE,
            ):
                return True
            if any(token in normalized for token in ["핵심투입인력", "핵심 인력", "사업관리자", "pm"]):
                if any(token in lowered for token in ["핵심투입인력", "핵심 인력", "사업관리자", "pm"]):
                    return True
            if any(token in normalized for token in ["가이드", "guideline", "guide"]):
                if any(token in lowered for token in ["guideline", "guide to", "guidelines for", "adb", "european commission"]):
                    return True
        return False

    @staticmethod
    def _has_budget_evidence(results: list[dict[str, Any]], top_n: int = 12) -> bool:
        if not results:
            return False
        budget_markers = ["사업비", "총사업비", "예산", "사업 금액", "사 업 비", "금액"]
        budget_value_pattern = re.compile(
            r"(금\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:천원|백만원|만원|억원|원)",
            re.IGNORECASE,
        )
        for item in results[: max(1, top_n)]:
            text = str(item.get("text", "") or "")
            if not text:
                continue
            if any(marker in text for marker in budget_markers) and budget_value_pattern.search(text):
                return True
        return False

    @staticmethod
    def _is_comparison_query(query: str) -> bool:
        """다문서 비교형 질의 여부를 판별합니다."""
        q = unicodedata.normalize("NFKC", query.lower())
        strong_markers = ["비교", "차이", "공통", "모두 고려", "동시에", "두 문서", "서로 다른", "어떻게 다른", "a 문서", "b 문서"]
        if any(marker in q for marker in strong_markers):
            return True
        if "각각" in q and any(marker in q for marker in ["각 문서", "기관별", "두 문서", "a 문서", "b 문서"]):
            return True
        return False

    @staticmethod
    def _is_implicit_follow_up_query(query: str) -> bool:
        """주어 생략형 후속 질문(예: '마감일은?', '사업명은?')을 판별합니다."""
        q = unicodedata.normalize("NFKC", (query or "").lower()).strip()
        if not q:
            return False

        # 새로운 탐색 질의(카테고리/랭킹/범위검색)는 후속질문으로 간주하지 않는다.
        fresh_query_markers = [
            "가장",
            "top",
            "순위",
            "랭킹",
            "기관 찾아",
            "관련 사업",
            "어떤 것이",
            "추천",
            "목록",
        ]
        if any(marker in q for marker in fresh_query_markers):
            return False

        follow_up_slots = [
            "마감일",
            "마감",
            "사업명",
            "사업비",
            "예산",
            "금액",
            "기한",
            "기간",
            "일정",
            "제출",
            "요건",
            "요구사항",
            "담당",
            "연락처",
            "주소",
            "위치",
            "언제",
            "얼마",
            "누가",
        ]
        if any(slot in q for slot in follow_up_slots):
            return True

        # 짧은 의문문은 직전 문맥을 잇는 경우가 많다.
        return len(q) <= 12 and q.endswith(("?", "요", "줘", "봐", "가요", "인가요"))

    @staticmethod
    def _looks_like_project_phrase(text: str) -> bool:
        """기관명이 아니라 사업/문서명으로 보이는 문구인지 판별합니다."""
        normalized = unicodedata.normalize("NFKC", (text or "").lower())
        if not normalized:
            return False
        project_markers = [
            "시스템", "사업", "구축", "고도화", "용역", "재구축", "개선",
            "포털", "플랫폼", "조사", "연계", "기능",
        ]
        return any(marker in normalized for marker in project_markers)

    def _should_fallback_to_original(self, query: str, results: list[dict[str, Any]]) -> bool:
        """CSV에만 치우친 결과면 원본 문서 재검색을 강제합니다."""
        if not results:
            return True
        if not self._needs_original_priority(query):
            return False
        has_original = any(
            self._infer_metadata_doc_type(item.get("metadata", {}) or {}) in {"pdf", "hwp"}
            for item in results[:8]
        )
        return not has_original

    def _build_context(self, query: str, results: list[dict[str, Any]]) -> str:
        """LLM 입력용 컨텍스트를 구성합니다."""
        history = self.conversation.get_context_summary()
        context_parts: list[str] = []
        if history:
            context_parts.append(f"# 이전 대화\n{history}")

        is_comparison = self._is_comparison_query(query)
        context_top_n = CONTEXT_TOP_RESULTS + 2 if is_comparison else CONTEXT_TOP_RESULTS
        context_max_chars = CONTEXT_MAX_CHARS + 200 if is_comparison else CONTEXT_MAX_CHARS

        for r in results[: max(1, context_top_n)]:
            md = r.get("metadata", {}) or {}
            source = md.get("source", "Unknown")
            org = md.get("org", "")
            page = md.get("page")
            source_label = f"{source} p.{page}" if page is not None else source
            project_name = md.get("project_name") or md.get("사업명") or ""
            notice_num = md.get("notice_num") or ""
            raw_text = r.get("text", "") or ""
            text = self._extract_relevant_excerpt(query, raw_text, max_chars=context_max_chars)
            meta_header = f"[{org} - {source_label}]"
            if project_name:
                meta_header += f" | project={project_name}"
            if notice_num:
                meta_header += f" | notice={notice_num}"
            context_parts.append(f"{meta_header}\n{text}")

        return "\n\n---\n\n".join(context_parts)

    def _extract_relevant_excerpt(self, query: str, text: str, max_chars: int | None = None) -> str:
        """질문 키워드와 관련된 문장을 우선 추출해 컨텍스트 품질을 높입니다."""
        if max_chars is None:
            max_chars = CONTEXT_MAX_CHARS
        cleaned = (text or "").replace("\r", "\n")
        if len(cleaned) <= max_chars:
            return cleaned

        keywords = self._extract_query_keywords(query)
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        if not lines:
            return cleaned[:max_chars]

        scored: list[tuple[int, str]] = []
        for line in lines:
            key = self._normalize_text_for_match(line)
            score = sum(1 for keyword in keywords if keyword in key)
            if re.search(r"\d", line):
                score += 1
            if score > 0:
                scored.append((score, line))

        excerpt_lines: list[str] = []
        if scored:
            scored.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            seen: set[str] = set()
            for _score, line in scored:
                if line in seen:
                    continue
                seen.add(line)
                excerpt_lines.append(line)
                if sum(len(l) + 1 for l in excerpt_lines) >= max_chars:
                    break
        else:
            excerpt_lines = lines[: min(10, len(lines))]

        excerpt = "\n".join(excerpt_lines).strip()
        return excerpt[:max_chars] if excerpt else cleaned[:max_chars]

    @staticmethod
    def _infer_source_type(results: list[dict[str, Any]]) -> str:
        """결과에서 대표 소스 타입을 반환합니다."""
        if not results:
            return "csv"
        first = results[0].get("metadata", {}) or {}
        return str(first.get("type", "csv"))

    def _handle_ranking_query(self, intent: QueryIntent) -> dict[str, Any]:
        """랭킹 질문을 처리합니다. (사업비 순 TOP N)"""
        import re

        # N 값 추출 (기본값 5)
        # 패턴: "3곳", "TOP5", "3개", "TOP 5" 등
        n_match = re.search(r'(\d+)\s*(?:곳|개|위)|TOP\s*(\d+)|TOP\s*(\d+)', intent.raw_query, re.IGNORECASE)
        if n_match:
            top_n = int(n_match.group(1) or n_match.group(2) or n_match.group(3))
        else:
            top_n = 5

        # 오름차순/내림차순 결정
        reverse = intent.rank_order != "asc"  # 기본은 내림차순 (많은 순)

        # 사업비 기준 정렬
        sorted_orgs = sorted(
            [o for o in self.vector_store.org_registry.values() if o.amount_numeric > 0],
            key=lambda x: x.amount_numeric,
            reverse=reverse
        )
        if not sorted_orgs:
            self._ensure_chunk_budget_cache()
            sorted_orgs = sorted(
                [o for o in self.vector_store.org_registry.values() if o.amount_numeric > 0],
                key=lambda x: x.amount_numeric,
                reverse=reverse,
            )

        # 상위 N개 선택
        top_orgs = sorted_orgs[:top_n]

        if not top_orgs:
            return {
                "answer": "사업비 정보가 있는 기관을 찾을 수 없습니다.",
                "found": False,
                "answer_mode": "extractive",
                "slot_fill_rate": 0.0,
                "evidence_count": 0,
                "confidence": 0.0,
                "evidence": [],
            }

        # 테이블 생성
        org_rows = []
        for org in top_orgs:
            project = org.project_name[:25] + "..." if org.project_name and len(org.project_name) > 25 else (org.project_name or "-")
            amount = format_amount(org.amount_numeric)
            rank_desc = "높은" if reverse else "낮은"
            org_rows.append(f"| {org.name} | {amount} | {project} |")

        header = f"📊 **사업비가 {rank_desc} {len(top_orgs)}개 기관**\n\n"
        header += "| 기관명 | 사업비 | 사업명 |\n"
        header += "|--------|--------|--------|\n"
        answer = header + "\n".join(org_rows)

        # 대화 기록 추가
        self.conversation.add_exchange(intent.raw_query, answer, intent)

        return {
            "answer": answer,
            "found": True,
            "source_type": "csv" if any(o.file_format.lower() == "csv" for o in top_orgs if o.file_format) else "pdf",
            "answer_mode": "extractive",
            "slot_fill_rate": 1.0,
            "evidence_count": 0,
            "confidence": 0.9,
            "evidence": [],
        }

    def _handle_category_query(self, intent: QueryIntent) -> dict[str, Any]:
        """카테고리 질문을 org_registry/CSV 메타데이터 기반으로 즉시 처리합니다."""
        query = intent.raw_query or ""
        category_keywords: dict[str, list[str]] = {
            "IT": ["it", "정보시스템", "시스템", "플랫폼", "디지털", "ai", "데이터", "통합"],
            "교육": ["교육", "학사", "대학", "학생", "교과", "학업", "연구", "학교"],
        }
        active_categories = intent.categories or []
        token_candidates: list[str] = []
        for cat in active_categories:
            token_candidates.extend(category_keywords.get(cat, []))
        token_candidates.extend(self._extract_query_keywords(query, max_keywords=10))

        token_keys: list[str] = []
        seen_tokens: set[str] = set()
        for token in token_candidates:
            norm = self._normalize_text_for_match(token)
            if not norm or norm in seen_tokens:
                continue
            seen_tokens.add(norm)
            token_keys.append(norm)

        ranked_rows: list[tuple[int, float, str, str, str]] = []
        for org_name, org_info in self.vector_store.org_registry.items():
            candidate_fields = [
                str(org_name),
                str(getattr(org_info, "project_name", "") or ""),
                str(getattr(org_info, "summary", "") or ""),
            ]
            for meta in self.csv_metadata_by_org.get(org_name, [])[:2]:
                candidate_fields.extend(
                    [
                        str(meta.get("project_name", "") or ""),
                        str(meta.get("summary", "") or ""),
                    ]
                )
            joined = " ".join(field for field in candidate_fields if field).strip()
            if not joined:
                continue
            joined_key = self._normalize_text_for_match(joined)
            if not joined_key:
                continue
            score = sum(1 for token in token_keys if token and token in joined_key)
            if score <= 0:
                continue
            project = str(getattr(org_info, "project_name", "") or "").strip() or "-"
            amount_numeric = float(getattr(org_info, "amount_numeric", 0) or 0)
            amount = format_amount(amount_numeric) if amount_numeric > 0 else "-"
            ranked_rows.append((score, amount_numeric, org_name, project, amount))

        if not ranked_rows:
            answer = "조건에 맞는 기관/사업을 찾지 못했습니다. 키워드를 더 구체화해 주세요."
            self.conversation.add_exchange(query, answer, intent)
            return {
                "answer": answer,
                "found": False,
                "source_type": "csv",
                "answer_mode": "extractive",
                "slot_fill_rate": 0.0,
                "evidence_count": 0,
                "confidence": 0.2,
                "evidence": [],
            }

        ranked_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        top_rows = ranked_rows[:10]
        header_label = ",".join(active_categories) if active_categories else "검색"
        answer_lines = [
            f"🔎 **{header_label} 관련 상위 {len(top_rows)}개 기관/사업**",
            "",
            "| 기관명 | 사업명 | 사업비 |",
            "|--------|--------|--------|",
        ]
        for _score, _amount_num, org_name, project, amount in top_rows:
            answer_lines.append(f"| {org_name} | {project} | {amount} |")
        answer = "\n".join(answer_lines)
        self.conversation.add_exchange(query, answer, intent)
        return {
            "answer": answer,
            "found": True,
            "source_type": "csv",
            "answer_mode": "extractive",
            "slot_fill_rate": 1.0,
            "evidence_count": 0,
            "confidence": 0.85,
            "evidence": [],
        }

    @staticmethod
    def _org_names_loosely_match(left: str, right: str) -> bool:
        if not left or not right:
            return False
        left_norm = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", left.lower()))
        right_norm = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", right.lower()))
        left_key = re.sub(r"[^0-9a-zA-Z가-힣]+", "", left_norm)
        right_key = re.sub(r"[^0-9a-zA-Z가-힣]+", "", right_norm)
        if not left_key or not right_key:
            return False
        return left_key == right_key or left_key in right_key or right_key in left_key

    def _filter_results_by_org(self, results: list[dict[str, Any]], target_org: str) -> list[dict[str, Any]]:
        """검색 결과를 특정 기관 기준으로 필터링합니다."""
        if not results or not target_org:
            return []
        filtered: list[dict[str, Any]] = []
        target_key = self._normalize_text_for_match(target_org)
        for item in results:
            md = item.get("metadata", {}) or {}
            org = str(md.get("org", "")).strip()
            if org and self._org_names_loosely_match(org, target_org):
                filtered.append(item)
                continue
            source = str(md.get("source") or item.get("source") or "").strip()
            source_key = self._normalize_text_for_match(source)
            if target_key and source_key and target_key in source_key:
                filtered.append(item)
        return filtered

    @staticmethod
    def _build_org_not_found_payload(org_name: str) -> dict[str, Any]:
        return {
            "answer": (
                f"제공된 문서에서 `{org_name}` 관련 정보를 찾지 못했습니다.\n"
                "해당 기관 문서가 인덱싱되어 있는지 확인해 주세요."
            ),
            "found": False,
            "answer_mode": "extractive",
            "slot_fill_rate": 0.0,
            "evidence_count": 0,
            "confidence": 0.0,
            "evidence": [],
        }

    def _resolve_known_org_name(self, candidate: str) -> str | None:
        """질문에서 추출된 기관명을 등록된 기관명으로 보정합니다."""
        if not candidate:
            return None
        if candidate in self.vector_store.org_registry:
            return candidate

        for org in self.vector_store.org_registry.keys():
            if self._org_names_loosely_match(candidate, org):
                return org

        cand_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", candidate.lower())))
        best_org = None
        best_overlap = 0
        for org in self.vector_store.org_registry.keys():
            org_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", org.lower())))
            overlap = len(cand_tokens.intersection(org_tokens))
            if overlap > best_overlap:
                best_overlap = overlap
                best_org = org
        if best_org and best_overlap >= 2:
            return best_org
        return None

    def _append_unique_org_name(self, org_names: list[str], candidate: str) -> None:
        """기관명 리스트에 유사 중복(유니코드 변형 포함) 없이 추가합니다."""
        if not candidate:
            return
        for existing in org_names:
            if self._org_names_loosely_match(existing, candidate):
                return
        org_names.append(candidate)

    def _resolve_query_target_orgs(
        self,
        query: str,
        explicit_orgs: list[str] | None = None,
        min_targets: int = 2,
    ) -> list[str]:
        """질문에서 비교/다문서 대상 기관을 복원합니다."""
        merged: list[str] = []
        for cand in explicit_orgs or []:
            resolved = self._resolve_known_org_name(cand) or cand
            self._append_unique_org_name(merged, resolved)

        if len(merged) < max(1, min_targets):
            for cand in self._extract_org_names_from_query(query, limit=max(5, min_targets + 2)):
                resolved = self._resolve_known_org_name(cand) or cand
                self._append_unique_org_name(merged, resolved)
                if len(merged) >= max(1, min_targets):
                    break
        return merged

    @staticmethod
    def _normalize_legal_name_tokens(value: str) -> str:
        """법인 표기를 정규화해 비교 가능성을 높입니다."""
        normalized = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", value or ""))
        replaced = (
            normalized.replace("㈜", "주식회사")
            .replace("（", "(")
            .replace("）", ")")
            .replace("「", "\"")
            .replace("」", "\"")
            .replace("『", "\"")
            .replace("』", "\"")
        )
        replaced = re.sub(r"\(\s*주\s*\)", "주식회사", replaced)
        replaced = re.sub(r"\(\s*사\s*\)", "사단법인", replaced)
        replaced = re.sub(r"\(\s*재\s*\)", "재단법인", replaced)
        return replaced

    def _extract_project_hints_from_query(self, query: str) -> list[str]:
        """질문의 따옴표/괄호 구간에서 프로젝트명 힌트를 추출합니다."""
        if not query:
            return []
        normalized = self._normalize_legal_name_tokens(query)
        patterns = [
            r"\"([^\"]{2,120})\"",
            r"'([^']{2,120})'",
            r"\(([^()]{2,120})\)",
            r"\[([^\[\]]{2,120})\]",
            r"<([^<>]{2,120})>",
        ]
        hints: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, normalized):
                hint = re.sub(r"\s+", " ", str(match).strip())
                if len(hint) < 3:
                    continue
                if hint not in hints:
                    hints.append(hint)
        if not hints:
            phrase_hits = re.findall(
                r"([0-9a-zA-Z가-힣·ㆍ&\-\s]{5,80}(?:사업|시스템|플랫폼|구축|고도화|통합))",
                normalized,
            )
            for phrase in phrase_hits:
                hint = re.sub(r"\s+", " ", phrase).strip()
                if hint and hint not in hints:
                    hints.append(hint)
        return hints[:6]

    def _ensure_org_coverage(
        self,
        query: str,
        results: list[dict[str, Any]],
        explicit_orgs: list[str],
        top_k: int,
        prefer_original: bool,
        min_docs_per_org: int = 2,
        perf_stats: dict[str, float | int | bool] | None = None,
    ) -> list[dict[str, Any]]:
        """다문서/비교 질의에서 지정 기관 커버리지를 강제 보완합니다."""
        if not explicit_orgs:
            return results

        merged = list(results)
        coverage: dict[str, int] = {}
        normalized_targets: list[str] = []
        for org in explicit_orgs:
            resolved = self._resolve_known_org_name(org)
            if not resolved:
                continue
            normalized_targets.append(resolved)
            coverage[resolved] = 0

        for item in merged[: max(30, top_k)]:
            md = item.get("metadata", {}) or {}
            org = str(md.get("org", "")).strip()
            for target in normalized_targets:
                if self._org_names_loosely_match(org, target):
                    coverage[target] += 1

        for target in normalized_targets:
            if perf_stats and perf_stats.get("budget_exhausted"):
                break
            # 비교/다문서 질의는 기관별 스코프 검색을 최소 1회 강제한다.
            scoped = self._retrieve_results(
                query,
                org_name=target,
                top_k=max(6, top_k // 4),
                prefer_original=prefer_original,
                doc_types=["pdf", "hwp"],
                perf_stats=perf_stats,
            )
            merged = self._merge_results(merged, scoped, top_k=max(top_k, 40))
            if scoped:
                for item in scoped:
                    org = str((item.get("metadata", {}) or {}).get("org", "")).strip()
                    if org and self._org_names_loosely_match(org, target):
                        coverage[target] = coverage.get(target, 0) + 1

            # 최소 커버리지 미달 시에만 해당 기관 재검색한다(전역 확장 검색으로 가지 않음).
            if coverage.get(target, 0) < min_docs_per_org and not (perf_stats and perf_stats.get("budget_exhausted")):
                scoped_retry = self._retrieve_results(
                    query,
                    org_name=target,
                    top_k=max(8, top_k // 3),
                    prefer_original=True,
                    doc_types=["pdf", "hwp"],
                    perf_stats=perf_stats,
                )
                merged = self._merge_results(merged, scoped_retry, top_k=max(top_k, 40))

        return merged

    def _extract_org_names_from_query(
        self,
        query: str,
        limit: int = 5,
        allow_project_fallback: bool = True,
    ) -> list[str]:
        """질문에서 기관명 후보를 길이 순으로 추출합니다."""
        if not query:
            return []

        def _strip_legal_prefix(name: str) -> str:
            normalized = self._normalize_legal_name_tokens(name)
            return re.sub(
                r"^(사단법인|재단법인|주식회사|\(주\)|\(사\)|\(재\)|유한회사|합자회사|\s)+",
                "",
                normalized,
            ).strip()

        # 별칭 정규화 후 매칭
        # 질문 전체에 alias 정규화를 적용하면
        # "서울시립대학교" 같은 고유명사가 "서울특별시..."로 왜곡될 수 있다.
        # 따라서 원문 질문을 그대로 정규화해 기관 후보를 찾는다.
        normalized_query = self._normalize_legal_name_tokens(query)
        query_key = self._normalize_text_for_match(normalized_query)
        query_key_relaxed = self._normalize_text_for_match(_strip_legal_prefix(normalized_query))
        query_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", normalized_query.lower()))
        project_hints = self._extract_project_hints_from_query(normalized_query)

        # 1) 원문 기반 포함 매칭
        candidates: list[tuple[int, str]] = []
        query_lower = unicodedata.normalize("NFKC", normalized_query.lower())
        for org_name in self.vector_store.org_registry.keys():
            normalized_org_name = self._normalize_legal_name_tokens(org_name)
            org_lower = unicodedata.normalize("NFKC", normalized_org_name.lower())
            if org_lower and org_lower in query_lower:
                candidates.append((1000 + len(org_name), org_name))
            elif normalized_org_name in normalized_query or normalized_query in normalized_org_name:
                candidates.append((len(org_name), org_name))

        # 2) 공백/특수문자 제거한 정규화 매칭
        for org_name in self.vector_store.org_registry.keys():
            org_key = self._normalize_text_for_match(self._normalize_legal_name_tokens(org_name))
            if not org_key or not query_key:
                continue
            if org_key in query_key or query_key in org_key:
                candidates.append((len(org_key), org_name))

        # 3) 법인 접두어 제거 후 느슨한 정규화 매칭
        for org_name in self.vector_store.org_registry.keys():
            relaxed = _strip_legal_prefix(org_name)
            relaxed_key = self._normalize_text_for_match(relaxed)
            if not relaxed_key or not query_key_relaxed:
                continue
            if relaxed_key in query_key_relaxed or query_key_relaxed in relaxed_key:
                candidates.append((len(relaxed_key), org_name))

        # 4) 토큰 겹침 기반 유사 매칭 (긴 기관명/괄호 표기 보정)
        if query_tokens:
            for org_name in self.vector_store.org_registry.keys():
                org_tokens = set(
                    re.findall(
                        r"[0-9a-zA-Z가-힣]{2,}",
                        self._normalize_legal_name_tokens(org_name.lower()),
                    )
                )
                overlap = len(org_tokens.intersection(query_tokens))
                if overlap >= 2:
                    score = overlap * 100 + len(org_name)
                    candidates.append((score, org_name))

        # 5) 기관명 직접 매칭 실패 시 프로젝트명/소스명을 힌트로 기관 후보를 복원한다.
        candidate_org_count = len({org for _, org in candidates})
        if allow_project_fallback and candidate_org_count < 2 and project_hints:
            for org_name, org_info in self.vector_store.org_registry.items():
                candidate_texts: list[str] = []
                if org_info.project_name:
                    candidate_texts.append(str(org_info.project_name))
                for meta in self.csv_metadata_by_org.get(org_name, [])[:2]:
                    filename = str(meta.get("filename", "")).strip()
                    stem = str(meta.get("file_stem", "")).strip()
                    if filename:
                        candidate_texts.append(filename)
                    if stem:
                        candidate_texts.append(stem)

                best_score = 0
                for hint in project_hints:
                    hint_norm = self._normalize_text_for_match(hint)
                    hint_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", hint.lower())))
                    for candidate_text in candidate_texts:
                        cand_norm = self._normalize_text_for_match(candidate_text)
                        if not cand_norm:
                            continue
                        if hint_norm and (hint_norm in cand_norm or cand_norm in hint_norm):
                            best_score = max(best_score, 450 + min(len(cand_norm), len(hint_norm)))
                            continue
                        cand_tokens = set(
                            re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", candidate_text.lower()))
                        )
                        overlap = len(hint_tokens.intersection(cand_tokens))
                        if overlap >= 2:
                            best_score = max(best_score, overlap * 120 + len(cand_norm))
                if best_score > 0:
                    candidates.append((best_score, org_name))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[0], reverse=True)
        ordered: list[str] = []
        for _, org in candidates:
            resolved = self._resolve_known_org_name(org) or org
            self._append_unique_org_name(ordered, resolved)
            if len(ordered) >= limit:
                break
        return ordered

    def _extract_org_name_from_query(self, query: str) -> str | None:
        """질문에서 기관명을 단일값으로 추출합니다(호환용)."""
        orgs = self._extract_org_names_from_query(query, limit=1)
        return orgs[0] if orgs else None

    def _create_multi_org_summary(self, results: list, query: str) -> str:
        """여러 기관의 요약 답변을 생성합니다 - 입찰 요약 형식."""
        seen_orgs = set()
        org_rows = []

        for r in results[:15]:
            org_name = r['metadata'].get('org', '')
            if org_name and org_name not in seen_orgs:
                seen_orgs.add(org_name)

                org_info = self.vector_store.org_registry.get(org_name)
                if org_info:
                    # 입찰 요약 형식: 기관명 | 사업비 | 사업명
                    project = org_info.project_name[:20] + "..." if org_info.project_name and len(org_info.project_name) > 20 else (org_info.project_name or "-")
                    amount = format_amount(org_info.amount_numeric) if org_info.amount_numeric > 0 else "-"
                    org_rows.append(f"| {org_info.name} | {amount} | {project} |")

        if org_rows:
            # 테이블 헤더
            header = f"📊 **검색된 {len(org_rows)}개 사업** (입찰 요약)\n\n"
            header += "| 기관명 | 사업비 | 사업명 |\n"
            header += "|--------|--------|--------|\n"
            return header + "\n".join(org_rows[:10])

        return "📋 관련 사업을 찾았습니다. 구체적인 기관명을 물어보시면 상세 조건을 안내해 드립니다."


# ============================================================================
# 메인 함수
# ============================================================================

def main() -> None:
    """메인 진입점 함수."""
    chatbot = RAGChatbotV17()

    print("\n" + "=" * 60)
    print("입찰메이트 RFP 챗봇 v17 (마크다운 통합 데이터베이스)")
    print("=" * 60)
    print("구현된 기능:")
    print("  - CSV/HWP/PDF 모든 데이터를 마크다운으로 변환")
    print("  - 통합 벡터 DB에서 단일 검색")
    print("  - 간결한 RFP 중심 답변")
    print("=" * 60)

    while True:
        try:
            query = input("\n[입찰메이트 v17] > ").strip()
            if not query:
                continue
            if query.lower() in ['quit', 'exit', 'q']:
                break

            result = chatbot.answer(query)
            print(f"\n답변: {result['answer']}")

        except KeyboardInterrupt:
            break
        except EOFError:
            break
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    main()
