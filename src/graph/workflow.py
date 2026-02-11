#!/usr/bin/env python3
"""입찰메이트 v17 - 메인 워크플로우."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

# OpenAI
from openai import OpenAI
from dotenv import load_dotenv

# 설정
sys.path.insert(0, 'src')
from src.utils.config import *
from src.utils.helpers import *
from src.prompts.templates import MARKDOWN_TEMPLATE

# 데이터베이스와 파서는 import 방식을 사용
load_dotenv()

# ============================================================================
# RAG 챗봇 (RAG Chatbot)
# ============================================================================

class RAGChatbotV17:
    """입찰메이트 RFP 챗봇 v17 메인 클래스."""

    def __init__(self, data_dir: str = "../data", db_path: str | None = None) -> None:
        script_dir = Path(__file__).parent.parent.parent.resolve()
        if Path(data_dir).is_absolute():
            self.data_dir = Path(data_dir).resolve()
        else:
            self.data_dir = (script_dir / data_dir).resolve()

        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        
        # 나중에 각 모듈에서 import
        from src.graph.nodes import RFPAnswerGenerator, QueryIntentParser
        from src.retrievers.vectorstore import VectorStore
        from src.graph.state import ConversationContext
        
        self.answer_generator = RFPAnswerGenerator(self.client)
        self.vector_store = VectorStore(db_path=db_path or f"{self.data_dir}/chroma_db_v17")
        self.query_parser = QueryIntentParser(self.client)
        self.conversation = ConversationContext(max_history=5)

        self._load_documents()

    def _load_documents(self) -> None:
        """모든 문서를 로드하고 변환합니다."""
        is_initial_load = self.vector_store.count == 0

        self._load_csv_files(verbose=is_initial_load)

        if is_initial_load:
            print("=" * 60)
            print("입찰메이트 v17 - 마크다운 통합 데이터베이스 구축")
            print("=" * 60)
            self._load_document_files(force_reload=True)
            print("=" * 60)
            print(f"총 {len(self.vector_store.org_registry)}개 기관 등록 완료")
            print(f"벡터 DB 청크 수: {self.vector_store.count}")
            print("=" * 60)

    def _load_csv_files(self, verbose: bool = False) -> None:
        """CSV 파일을 로드하고 변환합니다."""
        csv_files = (
            list(self.data_dir.glob("data_list*.csv")) +
            list(self.data_dir.glob("*data*.csv")) +
            list(self.data_dir.glob("*data_list*.csv"))
        )

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

        self._register_csv_orgs(markdowns)

        if verbose:
            self._add_csv_chunks(markdowns)

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
                chunks.append({
                    "text": f"## {section}",
                    "source": md_data.filename or 'csv',
                    "org": md_data.org_name,
                    "type": "csv"
                })

        if chunks:
            self.vector_store.add_documents(chunks)
            print(f"  벡터 DB에 {len(chunks)}개 청크 추가")

    def _create_org_info_from_markdown(self, md_data) -> Any:
        """마크다운 데이터에서 기관 정보를 생성합니다."""
        from src.graph.state import OrgInfo
        org_info = OrgInfo(
            name=md_data.org_name,
            amount=md_data.amount,
            project_name=md_data.project_name,
            summary=md_data.summary,
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

                from src.graph.state import OrgInfo
                org_info = OrgInfo(
                    name=org_name,
                    file_format='PDF' if is_pdf else 'HWP',
                    has_pdf=is_pdf,
                    has_hwp=not is_pdf
                )
                self.vector_store.register_org(org_info)

                if existing_count > 0 and not force_reload:
                    print(f"  ℹ️ {file_path.name}: {org_name} (기관 정보만 등록)")
                    continue

                print(f"  🔄 {file_path.name}: {org_name} 변환 중...", end="", flush=True)

                if is_pdf:
                    markdown = PDFMarkdownConverter().convert(file_path, org_name)
                else:
                    markdown = HWPMarkdownConverter().convert(file_path, org_name)

                amount_str, amount_int = extract_amount_from_text(markdown)

                if amount_int > 0:
                    updated_info = OrgInfo(
                        name=org_name,
                        amount=amount_str,
                        file_format='PDF' if is_pdf else 'HWP',
                        has_pdf=is_pdf,
                        has_hwp=not is_pdf
                    )
                    updated_info.amount_numeric = amount_int
                    self.vector_store.register_org(updated_info)
                    print(f" 💰{amount_str}", end="", flush=True)

                sections = PDFMarkdownConverter.split_markdown_sections(markdown)
                valid_sections = PDFMarkdownConverter.filter_valid_sections(sections)

                for section in valid_sections:
                    all_chunks.append({
                        "text": f"## {section}",
                        "source": file_path.name,
                        "org": org_name,
                        "type": "pdf" if is_pdf else "hwp"
                    })

                print(f" ✅ ({len(valid_sections)} 섹션)")

            except Exception as e:
                print(f"  ❌ {file_path.name}: {e}")

        if all_chunks:
            self.vector_store.add_documents(all_chunks)
            print(f"  벡터 DB에 {len(all_chunks)}개 청크 추가")
        elif existing_count == 0:
            print("  ⚠️ 처리할 청크가 없습니다.")

    def answer(self, query: str) -> dict[str, Any]:
        """질문에 답변합니다."""
        from src.graph.state import QueryIntent
        
        follow_up_context = self.conversation.get_follow_up_context(query)
        enhanced_query = query

        if follow_up_context["is_follow_up"] and follow_up_context["last_org"]:
            enhanced_query = f"{follow_up_context['last_org']} {query}"

        intent = self.query_parser.parse(enhanced_query)

        if (intent.query_type == "org" and not intent.org_name and
                follow_up_context["last_org"]):
            intent.org_name = follow_up_context["last_org"]

        result = None

        if intent.query_type == "org" and intent.org_name:
            from src.retrievers.vectorstore import VectorStore
            org = self.vector_store.org_registry.get(intent.org_name)
            if org:
                result = self._handle_org_question(org)

        if result is None:
            result = self._fallback_search(query)

        self.conversation.add_exchange(
            query=query,
            answer=result.get("answer", ""),
            intent=intent
        )

        return result

    def _handle_org_question(self, org) -> dict[str, Any]:
        """기관 질문을 처리합니다."""
        lines = [f"## {org.name}"]

        if org.project_name:
            lines.append(f"**사업명**: {org.project_name}")
        if org.amount_numeric > 0:
            lines.append(f"**사업비**: {format_amount(org.amount_numeric)}")
        if org.open_date:
            lines.append(f"**공개일**: {org.open_date}")
        if org.summary:
            summary_text = org.summary[:300] + "..." if len(org.summary) > 300 else org.summary
            lines.append(f"**사업개요**: {summary_text}")

        return {
            "answer": "\n".join(lines),
            "found": True,
            "source_type": "pdf" if org.has_pdf else ("hwp" if org.has_hwp else "csv")
        }

    def _fallback_search(self, query: str) -> dict[str, Any]:
        """기본 검색을 수행합니다."""
        results = self.vector_store.search(query, top_k=10)
        
        if not results:
            return {
                "answer": "관련 정보를 찾을 수 없습니다.",
                "found": False,
                "source_type": "unknown"
            }

        final_answer = self._create_multi_org_summary(results, query)

        if len(final_answer) < 100 and self.client:
            from src.graph.nodes import RFPAnswerGenerator
            context = "\n\n---\n\n".join([
                f"[{r['metadata'].get('source', 'Unknown')}]\n{r['text'][:800]}"
                for r in results[:5]
            ])
            llm_answer = self.answer_generator.generate(query, context)
            if llm_answer and "오류:" not in llm_answer and len(llm_answer) > 50:
                final_answer = llm_answer

        source_type = results[0]['metadata'].get('type', 'csv') if results else 'csv'
        return {
            "answer": final_answer,
            "found": True,
            "source_type": source_type
        }

    def _create_multi_org_summary(self, results: list, query: str) -> str:
        """여러 기관의 요약 답변을 생성합니다."""
        seen_orgs = set()
        org_summaries = []

        for r in results[:15]:
            org_name = r['metadata'].get('org', '')
            if org_name and org_name not in seen_orgs:
                seen_orgs.add(org_name)

                org_info = self.vector_store.org_registry.get(org_name)
                if org_info:
                    summary_parts = [f"### {org_info.name}"]
                    if org_info.project_name:
                        summary_parts.append(f"- **사업명**: {org_info.project_name}")
                    if org_info.amount_numeric > 0:
                        summary_parts.append(f"- **사업비**: {format_amount(org_info.amount_numeric)}")
                    org_summaries.append("\n".join(summary_parts))

        if org_summaries:
            header = f"## 검색된 기관 ({len(org_summaries)}개)\n\n"
            return header + "\n\n---\n\n".join(org_summaries[:5])

        return "## 검색 결과\n\n관련 문서를 찾았습니다. 상세 정보를 위해 기관명을 구체적으로 물어보세요."


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
