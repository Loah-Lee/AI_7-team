from __future__ import annotations

from src.graph.state import OrgInfo, QueryIntent, QuestionPlan
from src.graph.workflow import RAGChatbotV17


class _DummyVectorStore:
    def __init__(self) -> None:
        self.org_registry: dict[str, OrgInfo] = {
            "고려대학교": OrgInfo(name="고려대학교"),
            "서울특별시": OrgInfo(name="서울특별시"),
        }

    @staticmethod
    def normalize_org_name(org_name: str) -> str:
        return org_name


class _DummyParser:
    last_parse_used_llm = False

    @staticmethod
    def parse(query: str) -> QueryIntent:
        org_name = ""
        if "고려대학교" in query:
            org_name = "고려대학교"
        elif "서울특별시" in query:
            org_name = "서울특별시"
        return QueryIntent(query_type="search", org_name=org_name, raw_query=query)


class _DummyPlanner:
    @staticmethod
    def build(query: str, target_org: str = "") -> QuestionPlan:
        return QuestionPlan(query_kind="single_doc", is_comparison=("비교" in query), target_org=target_org)


class _DummyConversation:
    def __init__(self) -> None:
        self.history: list[dict[str, str]] = []

    @staticmethod
    def get_follow_up_context(query: str) -> dict[str, object]:
        return {
            "has_previous": False,
            "last_org": None,
            "last_query_type": None,
            "is_follow_up": False,
        }

    def add_exchange(self, query: str, answer: str, intent: QueryIntent | None = None) -> None:
        self.history.append({"query": query, "answer": answer})


def _build_bot() -> RAGChatbotV17:
    bot = RAGChatbotV17.__new__(RAGChatbotV17)
    bot.vector_store = _DummyVectorStore()
    bot.query_parser = _DummyParser()
    bot.question_planner = _DummyPlanner()
    bot.conversation = _DummyConversation()
    bot.csv_question_field_map = {
        "amount": ("사업비", "예산"),
        "notice_num": ("공고번호", "공고 번호"),
        "open_date": ("공개 일자",),
        "start_date": ("입찰 참여 시작", "입찰 시작"),
        "end_date": ("입찰 참여 마감", "입찰 마감", "마감일"),
        "org_name": ("발주 기관",),
        "project_name": ("사업명",),
        "summary": ("사업 요약",),
        "filename": ("파일명",),
    }

    primary = {
        "filename": "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
        "org_name": "고려대학교",
        "org_key": bot._normalize_text_for_match("고려대학교"),
        "notice_num": "202401010001",
        "amount": "금 3,120,000천원",
        "project_name": "차세대 포털·학사 정보시스템 구축사업",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "summary": "학사/포털 시스템 구축",
    }
    seoul = {
        "filename": "서울특별시_지도정보_고도화.pdf",
        "org_name": "서울특별시",
        "org_key": bot._normalize_text_for_match("서울특별시"),
        "notice_num": "202402020002",
        "amount": "금 493,763천원",
        "project_name": "지도정보 플랫폼 고도화",
        "start_date": "2024-02-01",
        "end_date": "2024-02-28",
        "summary": "지도정보 연계 시스템 고도화",
    }

    bot.csv_metadata_by_filename = {
        primary["filename"].lower(): primary,
        seoul["filename"].lower(): seoul,
    }
    bot.csv_metadata_by_stem = {}
    bot.csv_metadata_by_org = {
        "고려대학교": [primary],
        "서울특별시": [seoul],
    }
    bot.csv_metadata_by_org_key = {
        primary["org_key"]: [primary],
        seoul["org_key"]: [seoul],
    }
    bot.csv_metadata_by_notice_num = {
        primary["notice_num"]: primary,
        seoul["notice_num"]: seoul,
    }

    return bot


def test_answer_amount_shortcircuits_to_csv_without_db_retrieval() -> None:
    bot = _build_bot()
    calls = {"retrieve": 0}

    def _retrieve_guard(*args, **kwargs):
        calls["retrieve"] += 1
        raise AssertionError("CSV 단축 질의에서 DB 검색이 호출되면 안 됩니다.")

    bot._retrieve_results = _retrieve_guard

    payload = bot.answer("고려대학교 사업비는 얼마인가요?")

    assert payload.get("csv_short_circuit") is True
    assert payload.get("source_type") == "csv"
    assert "사업비" in payload.get("answer", "")
    assert calls["retrieve"] == 0


def test_answer_notice_number_shortcircuits_to_csv() -> None:
    bot = _build_bot()
    bot._retrieve_results = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("공고번호 질의는 CSV 즉답이어야 합니다.")
    )

    payload = bot.answer("202401010001 공고번호 알려줘")

    assert payload.get("csv_short_circuit") is True
    assert payload.get("source_type") == "csv"
    assert "202401010001" in payload.get("answer", "")


def test_answer_bid_end_date_shortcircuits_to_csv() -> None:
    bot = _build_bot()
    bot._retrieve_results = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("마감일 질의는 CSV 즉답이어야 합니다.")
    )

    payload = bot.answer("고려대학교 입찰 마감일은?")

    assert payload.get("csv_short_circuit") is True
    assert payload.get("source_type") == "csv"
    assert "2024-01-31" in payload.get("answer", "")


def test_comparison_query_bypasses_csv_shortcircuit_and_enters_db_path() -> None:
    bot = _build_bot()
    calls = {"retrieve": 0}

    def _retrieve_stub(*args, **kwargs):
        calls["retrieve"] += 1
        return []

    bot._retrieve_results = _retrieve_stub
    bot._should_fallback_to_original = lambda *args, **kwargs: False
    bot._ensure_org_coverage = lambda query, retrieval, **kwargs: retrieval

    payload = bot.answer("고려대학교와 서울특별시 사업비 비교")

    assert payload.get("csv_short_circuit") is not True
    assert calls["retrieve"] > 0
    assert payload.get("found") is False


def test_recovery_deadline_query_with_budget_system_name_does_not_shortcircuit_csv_amount() -> None:
    bot = _build_bot()
    calls = {"retrieve": 0}

    def _retrieve_stub(*args, **kwargs):
        calls["retrieve"] += 1
        return []

    bot._retrieve_results = _retrieve_stub
    bot._should_fallback_to_original = lambda *args, **kwargs: False
    bot._ensure_org_coverage = lambda query, retrieval, **kwargs: retrieval

    payload = bot.answer(
        "한국농수산식품유통공사 농산물가격안정기금 정부예산회계연계시스템에서 장애 발생 시 데이터 복구 기한은?"
    )

    assert payload.get("csv_short_circuit") is not True
    assert calls["retrieve"] > 0
