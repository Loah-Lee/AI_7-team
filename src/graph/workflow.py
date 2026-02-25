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
            self._load_csv_files(force_reload=True)
            print("=" * 60)
            print(f"총 {len(self.vector_store.org_registry)}개 기관 등록 완료")
            print(f"벡터 DB 청크 수: {self.vector_store.count}")
            print("=" * 60)

    def _load_csv_files(self, verbose: bool = False) -> None:
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

    def answer(self, query: str) -> dict[str, Any]:
        """질문에 답변합니다."""
        # 기관명 먼저 추출 (자격요건, 제출서류 등 특정 기관 질문)
        org_name = self._extract_org_name_from_query(query)

        if org_name and org_name in self.vector_store.org_registry:
            # 특정 기관에 대한 질문 - 해당 기관 문서만 검색
            results = self.vector_store.search(f"{org_name} {query}", top_k=20)
        else:
            # 일반 검색
            results = self.vector_store.search(query, top_k=30)

        if not results:
            return {
                "answer": "관련 정보를 찾을 수 없습니다.",
                "found": False
            }

        # LLM로 답변 생성
        if self.client:
            context_parts = []
            for r in results[:20]:
                source = r['metadata'].get('source', 'Unknown')
                org = r['metadata'].get('org', '')
                text = r.get('text', '')
                context_parts.append(f"[{org} - {source}]\n{text[:8000]}")

            context = "\n\n---\n\n".join(context_parts)
            answer = self.answer_generator.generate(query, context)

            if answer and "오류:" not in answer:
                return {"answer": answer, "found": True}

        # 기관 요약 반환
        summary = self._create_multi_org_summary(results, query)
        return {"answer": summary, "found": True}

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

    def _create_multi_org_summary(self, results: list, query: str) -> dict[str, Any]:
        """여러 기관의 요약 답변을 생성합니다 - 입찰 요약 형식."""
        seen_orgs = set()
        org_rows = []

        for r in results[:15]:
            org_name = r['metadata'].get('institution', '')
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
