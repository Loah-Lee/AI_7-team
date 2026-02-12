#!/usr/bin/env python3
"""대화 기능 테스트 스크립트"""

import sys
sys.path.insert(0, 'src')

from src.graph.state import QueryIntent, QueryIntentParser, ConversationContext


def test_query_parser():
    """질문 파서 테스트"""
    print("=" * 60)
    print("질문 파서 테스트")
    print("=" * 60)

    parser = QueryIntentParser(client=None)

    test_queries = [
        "고려대학교 사업비는?",
        "사업비가 가장 많은 3곳은?",
        "5억에서 10억 사이",
        "10억 이상인 사업은?",
        "IT 관련 사업은?",
        "그거 언제야?",
    ]

    for query in test_queries:
        intent = parser.parse(query)
        min_str = f"{intent.amount_min:,}원" if intent.amount_min else "없음"
        max_str = f"{intent.amount_max:,}원" if intent.amount_max else "없음"
        print(f"\n질문: {query}")
        print(f"  유형: {intent.query_type}")
        print(f"  기관: {intent.org_name or '-'}")
        print(f"  금액: {min_str} ~ {max_str}")
        print(f"  신뢰도: {intent.confidence:.2f}")


def test_conversation_context():
    """대화 컨텍스트 테스트"""
    print("\n" + "=" * 60)
    print("대화 컨텍스트 테스트")
    print("=" * 60)

    conv = ConversationContext(max_history=3)

    conversations = [
        ("고려대학교 사업비는?", "약 141.1억 원입니다."),
        ("언제까지야?", "2024년 12월 31일까지입니다."),
        ("그거 사업명은?", "스마트캠퍼스 구축입니다."),
    ]

    for query, answer in conversations:
        print(f"\nQ: {query}")
        print(f"A: {answer}")

        context = conv.get_follow_up_context(query)
        print(f"  후속 질문: {context['is_follow_up']}")
        print(f"  마지막 기관: {context['last_org'] or '-'}")

        conv.add_exchange(query, answer)


if __name__ == "__main__":
    test_query_parser()
    test_conversation_context()

    print("\n" + "=" * 60)
    print("테스트 완료!")
    print("=" * 60)
