#!/usr/bin/env python3
"""입찰메이트 v17 - 메인 워크플로우."""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

# LangChain (LangSmith 트레이싱)
from langchain_openai import ChatOpenAI

# 설정
sys.path.insert(0, 'src')
from src.utils.config import *
from src.utils.helpers import *
from src.graph.state import QueryIntent

# 데이터베이스와 파서는 import 방식을 사용
from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# LangSmith 트레이싱 활성화
# ============================================================================
import os
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

class RAGChatbotV17:
    """입찰메이트 RFP 챗봇 v17 메인 클래스."""

    def __init__(self, data_dir: str = None, db_path: str | None = None) -> None:
        # data_dir이 None이면 기본값 사용
        if data_dir is None:
            data_dir = "data"

        script_dir = Path(__file__).parent.parent.parent.resolve()
        if Path(data_dir).is_absolute():
            self.data_dir = Path(data_dir).resolve()
        else:
            self.data_dir = (script_dir / data_dir).resolve()

        # data_dir이 디렉토리면 files 하위를 검색
        if self.data_dir.is_dir() and (self.data_dir / "files").is_dir():
            self.data_dir = (self.data_dir / "files").resolve()

        # LangChain ChatOpenAI 초기화 (LangSmith 트레이싱 자동)
        self.llm = None
        if OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=REASONING_MODEL,
                temperature=0.2,
            )

        # 나중에 각 모듈에서 import
        from src.graph.nodes import RFPAnswerGenerator, QueryIntentParser
        from src.retrievers.vectorstore import VectorStore
        from src.graph.state import ConversationContext

        self.answer_generator = RFPAnswerGenerator(self.llm)
        self.vector_store = VectorStore(db_path=db_path or f"{self.data_dir}/chroma_db_v17")
        self.query_parser = QueryIntentParser(self.llm)
        self.conversation = ConversationContext(max_history=5)
        self.csv_metadata_by_filename: dict[str, dict[str, Any]] = {}
        self.csv_metadata_by_stem: dict[str, dict[str, Any]] = {}
        self.csv_metadata_by_org: dict[str, list[dict[str, Any]]] = {}
        self.unified_markdown_dir = (self.data_dir.parent / "processed_runtime" / "markdown").resolve()
        self.unified_markdown_dir.mkdir(parents=True, exist_ok=True)

        self._load_documents()

    def _load_documents(self) -> None:
        """모든 문서를 로드하고 변환합니다."""
        is_initial_load = self.vector_store.count == 0
        self._load_csv_files(verbose=is_initial_load, add_chunks=is_initial_load)

        chunk_counts = self.vector_store.count_chunks_by_type()
        has_csv_chunks = chunk_counts.get("csv", 0) > 0
        has_doc_chunks = (chunk_counts.get("pdf", 0) + chunk_counts.get("hwp", 0)) > 0

        if not has_csv_chunks:
            print("ℹ️ CSV 청크가 없어 CSV 재인덱싱을 수행합니다.")
            self._load_csv_files(verbose=True, add_chunks=True)
            chunk_counts = self.vector_store.count_chunks_by_type()
            has_doc_chunks = (chunk_counts.get("pdf", 0) + chunk_counts.get("hwp", 0)) > 0

        should_load_docs = is_initial_load or not has_doc_chunks
        if should_load_docs:
            print("=" * 60)
            print("입찰메이트 v17 - 마크다운 통합 데이터베이스 구축")
            print("=" * 60)
            self._load_document_files(force_reload=not has_doc_chunks)
            print("=" * 60)
            print(f"총 {len(self.vector_store.org_registry)}개 기관 등록 완료")
            print(f"벡터 DB 청크 수: {self.vector_store.count}")
            print("=" * 60)

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

        for md_data in markdowns:
            meta = dict(md_data.metadata or {})
            filename = str(meta.get("filename") or md_data.filename or "").strip()
            stem = Path(filename).stem.lower() if filename else ""
            org_name = str(meta.get("org_name") or md_data.org_name or "").strip()

            normalized = {
                **meta,
                "filename": filename,
                "file_stem": stem,
                "org_name": org_name,
            }
            if filename:
                self.csv_metadata_by_filename[filename.lower()] = normalized
            if stem:
                self.csv_metadata_by_stem[stem] = normalized
            if org_name:
                self.csv_metadata_by_org.setdefault(org_name, []).append(normalized)

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

    def _register_csv_orgs(self, markdowns: list) -> None:
        """CSV 기관 정보만 등록합니다."""
        for md_data in markdowns:
            org_info = self._create_org_info_from_markdown(md_data)
            self.vector_store.register_org(org_info)

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

    def _load_document_files(self, force_reload: bool = False) -> None:
        """PDF/HWP 파일을 로드하고 변환합니다."""
        supported_extensions = ['.pdf', '.hwp', '.hwpx']
        all_files = []
        for ext in supported_extensions:
            all_files.extend(list(self.data_dir.glob(f'*{ext}')))

        if not all_files:
            print("⚠️ PDF/HWP 파일을 찾을 수 없습니다.")
            return

        print(f"\n📄 문서 파일 처리 중: {len(all_files)}개")

        from src.parsers.pdf_loader import PDFMarkdownConverter
        from src.parsers.hwp_loader import HWPMarkdownConverter
        
        existing_count = self.vector_store.count
        all_chunks = []

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

                if existing_count > 0 and not force_reload:
                    print(f"  ℹ️ {file_path.name}: {org_name} (기관 정보만 등록)")
                    continue

                print(f"  🔄 {file_path.name}: {org_name} 변환 중...", end="", flush=True)

                if is_pdf:
                    page_chunks = PDFMarkdownConverter().extract_pages(file_path, include_tables=True)
                else:
                    page_chunks = HWPMarkdownConverter().extract_pages(file_path)

                if not page_chunks:
                    print(" ⚠️ 추출 실패")
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
                for chunk in page_chunks:
                    chunk_text = (chunk.get("content") or "").strip()
                    if len(chunk_text) < MIN_SECTION_LENGTH:
                        continue
                    page_num = chunk.get("page")
                    table_count = int(chunk.get("table_count", 0) or 0)
                    all_chunks.append({
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

                print(f" ✅ ({valid_count} 페이지 청크)")

            except Exception as e:
                print(f"  ❌ {file_path.name}: {e}")

        if all_chunks:
            self.vector_store.add_documents(all_chunks)
            print(f"  벡터 DB에 {len(all_chunks)}개 청크 추가")
        elif existing_count == 0:
            print("  ⚠️ 처리할 청크가 없습니다.")

    def answer(self, query: str, top_k: int = 24) -> dict[str, Any]:
        """질문에 답변합니다."""
        query = query.strip()
        if not query:
            return {"answer": "질문을 입력해 주세요.", "found": False}

        # 1) 질문 의도 파악
        intent = self.query_parser.parse(query)
        if intent.query_type == "ranking":
            return self._handle_ranking_query(intent)

        # 2) 후속질문 컨텍스트 반영
        follow_up_ctx = self.conversation.get_follow_up_context(query)
        explicit_org = self._extract_org_name_from_query(query)
        if follow_up_ctx["is_follow_up"] and follow_up_ctx["last_org"] and not explicit_org:
            org_name = follow_up_ctx["last_org"]
        else:
            org_name = explicit_org or intent.org_name or ""
        intent.org_name = org_name

        # 3) 검색 (기관 지정 질의는 org 필터 우선, 원본 문서 fallback 포함)
        prefer_original = self._needs_original_priority(query)
        if org_name and org_name in self.vector_store.org_registry:
            retrieval = self._retrieve_results(
                query,
                org_name=org_name,
                top_k=top_k,
                prefer_original=prefer_original,
            )
            if self._should_fallback_to_original(query, retrieval):
                original_only = self._retrieve_results(
                    query,
                    org_name=org_name,
                    top_k=max(top_k, 28),
                    prefer_original=True,
                    doc_types=["pdf", "hwp"],
                )
                retrieval = self._merge_results(retrieval, original_only, top_k=max(top_k, 28))
            if retrieval:
                self.vector_store.last_search_results = retrieval
                return self._answer_with_results(query, retrieval, intent)

        retrieval = self._retrieve_results(
            query,
            org_name=None,
            top_k=top_k,
            prefer_original=prefer_original,
        )
        if self._should_fallback_to_original(query, retrieval):
            original_only = self._retrieve_results(
                query,
                org_name=None,
                top_k=max(top_k, 28),
                prefer_original=True,
                doc_types=["pdf", "hwp"],
            )
            retrieval = self._merge_results(retrieval, original_only, top_k=max(top_k, 28))
        if retrieval:
            self.vector_store.last_search_results = retrieval
            return self._answer_with_results(query, retrieval, intent)

        return {"answer": "관련 정보를 찾을 수 없습니다.", "found": False}

    def _answer_with_results(self, query: str, results: list[dict[str, Any]], intent: QueryIntent) -> dict[str, Any]:
        """검색 결과를 기반으로 최종 답변을 생성합니다."""
        source_type = self._infer_source_type(results)

        if not self.llm:
            # LLM이 없으면 규칙 기반 응답 후 요약 fallback
            answer = self._build_non_llm_answer(query, results, intent)
            if answer:
                self.conversation.add_exchange(query, answer, intent)
                return {"answer": answer, "found": True, "source_type": source_type}
            summary = self._create_multi_org_summary(results, query)
            self.conversation.add_exchange(query, summary, intent)
            return {"answer": summary, "found": True, "source_type": source_type}

        context = self._build_context(results)
        history = self.conversation.get_context_summary()
        answer = self.answer_generator.generate(query, context, history)
        if answer and "오류:" not in answer:
            self.conversation.add_exchange(query, answer, intent)
            return {"answer": answer, "found": True, "source_type": source_type}

        # 예외적으로 생성 실패 시 fallback
        summary = self._create_multi_org_summary(results, query)
        self.conversation.add_exchange(query, summary, intent)
        return {"answer": summary, "found": True, "source_type": source_type}

    def _build_non_llm_answer(
        self,
        query: str,
        results: list[dict[str, Any]],
        intent: QueryIntent,
    ) -> str:
        """LLM 없이도 단일기관 질의를 답변하기 위한 규칙 기반 생성기."""
        if not results:
            return ""

        top_orgs = [str((r.get("metadata") or {}).get("org", "")).strip() for r in results[:8]]
        unique_orgs = [o for o in dict.fromkeys(top_orgs) if o]
        single_org = len(unique_orgs) == 1
        target_org = unique_orgs[0] if unique_orgs else (intent.org_name or "")

        q = query.lower()
        is_responsibility_query = any(
            k in q for k in ["저작권", "라이선스", "사용권", "글꼴", "이미지", "부담", "책임", "지적재산"]
        )

        evidence = self._extract_evidence_lines(query, results, max_lines=3)
        if is_responsibility_query and single_org:
            if not evidence:
                return (
                    f"{target_org} 문서에서 이미지/글꼴 저작권 비용 부담 주체를 직접 명시한 조항을 찾지 못했습니다.\n"
                    "원본 제안요청서의 저작권/지식재산권/산출물 귀속 조항을 확인해 주세요."
                )

            owner = self._infer_responsibility_owner(evidence)
            source_line = self._format_first_source(results)
            detail = "\n".join([f"- {line}" for line in evidence])
            return (
                f"{target_org} 문서 기준으로 저작권 비용 부담 주체는 **{owner}**로 해석됩니다.\n\n"
                f"[근거]\n{detail}\n\n"
                f"[출처]\n- {source_line}"
            )

        if single_org and evidence:
            source_line = self._format_first_source(results)
            detail = "\n".join([f"- {line}" for line in evidence])
            return f"{target_org} 관련 문서 근거를 찾았습니다.\n\n[근거]\n{detail}\n\n[출처]\n- {source_line}"

        return ""

    @staticmethod
    def _format_first_source(results: list[dict[str, Any]]) -> str:
        if not results:
            return "source 없음"
        md = results[0].get("metadata", {}) or {}
        src = md.get("source", "Unknown")
        page = md.get("page")
        return f"{src} p.{page}" if page is not None else str(src)

    def _extract_evidence_lines(
        self,
        query: str,
        results: list[dict[str, Any]],
        max_lines: int = 3,
    ) -> list[str]:
        """질의 키워드와 일치하는 근거 라인을 추출합니다."""
        q = query.lower()
        keywords = [k for k in ["저작권", "라이선스", "사용권", "글꼴", "이미지", "부담", "책임", "지적재산"] if k in q]
        if not keywords:
            keywords = [k for k in ["사업비", "기간", "마감", "요구", "제출", "평가"] if k in q]

        lines: list[str] = []
        for item in results[:10]:
            text = (item.get("text", "") or "").replace("\r", "\n")
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if len(line) < 8:
                    continue
                if keywords:
                    if not any(k in line for k in keywords):
                        continue
                lines.append(line[:220])
                if len(lines) >= max_lines:
                    return lines
        return lines

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
        q = query.lower()
        if any(k in q for k in ["저작권", "라이선스", "사용권", "폰트", "글꼴", "이미지", "부담", "책임"]):
            expanded.append(f"{query} 저작권 라이선스 사용권 비용 부담 책임")
        if any(k in q for k in ["기간", "마감", "일자", "언제"]):
            expanded.append(f"{query} 입찰 시작일 입찰 마감일 사업 기간")
        if any(k in q for k in ["요구사항", "조건", "자격"]):
            expanded.append(f"{query} 요구사항 조건 자격")
        if any(k in q for k in ["표", "항목", "조항", "근거", "문구"]):
            expanded.append(f"{query} 조항 근거 문구 표 항목")
        return expanded

    def _retrieve_results(
        self,
        query: str,
        org_name: str | None,
        top_k: int,
        prefer_original: bool = False,
        doc_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """확장 질의 기반으로 검색 결과를 수집/병합합니다."""
        merged: list[dict[str, Any]] = []
        search_orders: list[list[str]]
        if doc_types:
            search_orders = [doc_types]
        elif prefer_original:
            search_orders = [["pdf", "hwp"], ["csv"]]
        else:
            search_orders = [["csv"], ["pdf", "hwp"], ["pdf", "hwp", "csv"]]

        per_call_k = max(4, top_k // max(1, len(search_orders)))
        for q in self._expand_query_terms(query):
            for types in search_orders:
                results = self.vector_store.search(
                    q,
                    top_k=max(per_call_k, top_k // 3),
                    org_name=org_name,
                    doc_types=types,
                )
                merged = self._merge_results(merged, results, top_k=top_k * 2)

        return merged[:top_k]

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
            "저작권", "라이선스", "사용권", "책임", "부담", "지적재산", "이미지", "글꼴",
            "요구사항", "평가기준", "제안요청", "과업", "조항", "문구", "근거", "표",
        ]
        return any(k in q for k in keywords)

    def _should_fallback_to_original(self, query: str, results: list[dict[str, Any]]) -> bool:
        """CSV에만 치우친 결과면 원본 문서 재검색을 강제합니다."""
        if not results:
            return True
        if not self._needs_original_priority(query):
            return False
        has_original = any(
            (item.get("metadata", {}) or {}).get("type") in {"pdf", "hwp"}
            for item in results[:8]
        )
        return not has_original

    def _build_context(self, results: list[dict[str, Any]]) -> str:
        """LLM 입력용 컨텍스트를 구성합니다."""
        history = self.conversation.get_context_summary()
        context_parts: list[str] = []
        if history:
            context_parts.append(f"# 이전 대화\n{history}")

        for r in results[:12]:
            md = r.get("metadata", {}) or {}
            source = md.get("source", "Unknown")
            org = md.get("org", "")
            page = md.get("page")
            source_label = f"{source} p.{page}" if page is not None else source
            project_name = md.get("project_name") or md.get("사업명") or ""
            notice_num = md.get("notice_num") or ""
            text = (r.get("text", "") or "")[:2400]
            meta_header = f"[{org} - {source_label}]"
            if project_name:
                meta_header += f" | project={project_name}"
            if notice_num:
                meta_header += f" | notice={notice_num}"
            context_parts.append(f"{meta_header}\n{text}")

        return "\n\n---\n\n".join(context_parts)

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

        # 상위 N개 선택
        top_orgs = sorted_orgs[:top_n]

        if not top_orgs:
            return {"answer": "사업비 정보가 있는 기관을 찾을 수 없습니다.", "found": False}

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

        return {"answer": answer, "found": True, "source_type": "csv"}

    def _extract_org_name_from_query(self, query: str) -> str | None:
        """질문에서 기관명을 추출합니다."""
        # 별칭 정규화 후 매칭
        normalized_query = self.vector_store.normalize_org_name(query)

        # 등록된 기관명 목록과 매칭
        for org_name in self.vector_store.org_registry.keys():
            # 완전 일치 또는 포함 확인 (별칭 처리 포함)
            if org_name in normalized_query or normalized_query in org_name:
                return org_name
        return None

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
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    main()
