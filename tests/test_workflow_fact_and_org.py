from __future__ import annotations

from src.graph.state import OrgInfo
from src.graph.workflow import RAGChatbotV17


class _DummyVectorStore:
    def __init__(self) -> None:
        self.org_registry: dict[str, OrgInfo] = {}

    @staticmethod
    def normalize_org_name(org_name: str) -> str:
        return org_name


def _make_bot() -> RAGChatbotV17:
    bot = RAGChatbotV17.__new__(RAGChatbotV17)
    bot.vector_store = _DummyVectorStore()
    bot.csv_metadata_by_org = {}
    return bot


def _sample_result(text: str, source: str = "sample.pdf", page: int = 1) -> dict:
    return {"text": text, "metadata": {"source": source, "page": page, "org": "테스트기관", "type": "pdf"}}


def test_extract_orgs_with_project_hint_fallback() -> None:
    bot = _make_bot()
    bot.vector_store.org_registry = {
        "고려대학교": OrgInfo(name="고려대학교", project_name="차세대 포털·학사 정보시스템 구축사업"),
        "서울특별시": OrgInfo(name="서울특별시", project_name="2024년 지도정보 플랫폼 및 전문활용 연계 시스템 고도화 용역"),
    }
    bot.csv_metadata_by_org = {
        "서울특별시": [
            {
                "filename": "서울특별시_2024년 지도정보 플랫폼 및 전문활용 연계 시스템 고도화 용.pdf",
                "file_stem": "서울특별시_2024년 지도정보 플랫폼 및 전문활용 연계 시스템 고도화 용",
            }
        ]
    }

    query = '고려대학교와 "2024년 지도정보 플랫폼 및 전문활용 연계 시스템 고도화 용역" 문서 비교'
    targets = bot._resolve_query_target_orgs(query, min_targets=2)

    assert "고려대학교" in targets
    assert "서울특별시" in targets


def test_extract_fact_capacity_mb() -> None:
    bot = _make_bot()
    query = "웹페이지 용량은 몇 MB인가요?"
    results = [
        _sample_result("웹페이지 첨부 파일 용량은 3MB 이하로 제한한다.", page=8),
        _sample_result("보존기간은 7년으로 한다.", page=22),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "3MB" in fact[0]


def test_extract_fact_charset_utf8() -> None:
    bot = _make_bot()
    query = "문자셋은 무엇이며 UTF 기준이 있나요?"
    results = [
        _sample_result("신규 시스템의 기본 문자셋은 UTF-8을 우선 적용한다.", page=12),
        _sample_result("운영기간은 3년이다.", page=30),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "UTF-8" in fact[0]


def test_extract_fact_recovery_deadline() -> None:
    bot = _make_bot()
    query = "장애 발생 시 복구기한은?"
    results = [
        _sample_result("장애 발생 시 12시간 이내 복구를 완료해야 한다.", page=17),
        _sample_result("자료 제출은 1일 전까지 가능하다.", page=9),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "12시간" in fact[0]


def test_extract_fact_unit_and_quantity_from_table_line() -> None:
    bot = _make_bot()
    query = "직무교육 단위 및 수량은?"
    results = [
        _sample_result("| 항목 | 수량 |\n| 직무교육 | 11,000명 |", page=4),
        _sample_result("일반 보존기간 7년", page=19),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "11,000명" in fact[0]


def test_extract_fact_guide_titles() -> None:
    bot = _make_bot()
    query = "경제적 타당성 분석 시 참고해야 할 가이드는 무엇인가?"
    results = [
        _sample_result(
            "Guidelines for the Economic Analysis of Projects (ADB) 및 "
            "Guide to Cost-Benefit Analysis of Investment Project (European Commission)을 따른다.",
            page=6,
        ),
        _sample_result("기술지원 범위는 별도 협의한다.", page=9),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "Guidelines for the economic analysis of projects" in fact[0]
    assert "Guide to cost-benefit analysis of investment project" in fact[0]


def test_extract_fact_key_personnel_assignment() -> None:
    bot = _make_bot()
    query = "핵심투입인력은 누구로 지정되어야 하나요?"
    results = [
        _sample_result("핵심투입인력은 사업관리자(PM) 1명으로 지정하며 대표사 소속이어야 한다.", page=11),
        _sample_result("사업 기간은 12개월로 한다.", page=3),
    ]
    fact = bot._extract_direct_fact_from_results(query, results)
    assert fact is not None
    assert "PM" in fact[0] or "사업관리자" in fact[0]
