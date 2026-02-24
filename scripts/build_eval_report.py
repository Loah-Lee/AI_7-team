#!/usr/bin/env python3
"""입찰메이트 v17 - 평가 결과 HTML 리포트 생성 스크립트."""

from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# HTML 템플릿
# ============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>입찰메이트 v17 - 평가 리포트</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 1rem;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
        }}

        .header .subtitle {{
            font-size: 1.1rem;
            opacity: 0.9;
        }}

        .header .timestamp {{
            margin-top: 1rem;
            font-size: 0.9rem;
            opacity: 0.8;
        }}

        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            padding: 2rem;
            background: #f8f9fa;
        }}

        .metric-card {{
            background: white;
            padding: 1.5rem;
            border-radius: 0.75rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            text-align: center;
        }}

        .metric-card .label {{
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 0.5rem;
        }}

        .metric-card .value {{
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
        }}

        .metric-card .value.score {{
            color: {main_score_color};
        }}

        .section {{
            padding: 2rem;
        }}

        .section-title {{
            font-size: 1.5rem;
            margin-bottom: 1.5rem;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 0.5rem;
        }}

        .result-card {{
            background: #f8f9fa;
            border-radius: 0.75rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            border-left: 4px solid #667eea;
        }}

        .result-card.correct {{
            border-left-color: #10b981;
        }}

        .result-card.partial {{
            border-left-color: #f59e0b;
        }}

        .result-card.incorrect {{
            border-left-color: #ef4444;
        }}

        .result-card.no-judge {{
            border-left-color: #9ca3af;
        }}

        .result-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}

        .result-id {{
            font-weight: bold;
            color: #667eea;
        }}

        .result-type {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.75rem;
            font-weight: bold;
            background: #e0e7ff;
            color: #4338ca;
        }}

        .result-question {{
            font-size: 1.1rem;
            font-weight: 500;
            margin-bottom: 1rem;
            color: #1f2937;
        }}

        .result-scores {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}

        .score-badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.75rem;
            border-radius: 0.5rem;
            font-size: 0.85rem;
            font-weight: bold;
        }}

        .score-badge.correctness {{
            background: #f3f4f6;
            color: #374151;
        }}

        .score-badge.coverage {{
            background: #f3f4f6;
            color: #374151;
        }}

        .score-badge.faithfulness {{
            background: #f3f4f6;
            color: #374151;
        }}

        .score-badge.context {{
            background: #f3f4f6;
            color: #374151;
        }}

        .answer-section {{
            margin-top: 1rem;
        }}

        .answer-label {{
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 0.25rem;
            font-weight: 500;
        }}

        .answer-content {{
            background: white;
            padding: 1rem;
            border-radius: 0.5rem;
            color: #374151;
            line-height: 1.6;
        }}

        .answer-content.expected {{
            border-left: 3px solid #10b981;
        }}

        .answer-content.generated {{
            border-left: 3px solid #3b82f6;
        }}

        .response-time {{
            font-size: 0.85rem;
            color: #6b7280;
            margin-top: 0.5rem;
        }}

        .chart-container {{
            height: 200px;
            margin: 1rem 0;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }}

        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }}

        th {{
            background: #f3f4f6;
            font-weight: 600;
            color: #374151;
        }}

        tr:hover {{
            background: #f9fafb;
        }}

        .progress-bar {{
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 0.5rem;
        }}

        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.3s ease;
        }}

        .footer {{
            text-align: center;
            padding: 1.5rem;
            background: #f8f9fa;
            color: #6b7280;
            font-size: 0.9rem;
        }}

        .summary-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }}

        .stat-item {{
            text-align: center;
            padding: 1rem;
            background: white;
            border-radius: 0.5rem;
        }}

        .stat-value {{
            font-size: 1.5rem;
            font-weight: bold;
            color: #667eea;
        }}

        .stat-label {{
            font-size: 0.8rem;
            color: #6b7280;
            margin-top: 0.25rem;
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>입찰메이트 v17 - 평가 리포트</h1>
            <div class="subtitle">RFP 문서 기반 지능형 질의응답 시스템 ({report_mode_label})</div>
            <div class="timestamp">생성일: {timestamp}</div>
        </div>

        <div class="metrics">
            <div class="metric-card">
                <div class="label">정확성 (Correctness)</div>
                <div class="value score">{avg_correctness_display}</div>
            </div>
            <div class="metric-card">
                <div class="label">커버리지 (Coverage)</div>
                <div class="value">{avg_coverage_display}</div>
            </div>
            <div class="metric-card">
                <div class="label">충실성 (Faithfulness)</div>
                <div class="value">{avg_faithfulness_display}</div>
            </div>
            <div class="metric-card">
                <div class="label">검색 관련성 (Context)</div>
                <div class="value">{avg_context_relevance_display}</div>
            </div>
            <div class="metric-card">
                <div class="label">평균 응답 시간</div>
                <div class="value">{avg_response_time:.2f}s</div>
            </div>
            <div class="metric-card">
                <div class="label">전체 질문 수</div>
                <div class="value">{total_questions}</div>
            </div>
            {extra_metric_cards}
        </div>

        <div class="section">
            <h2 class="section-title">검색 메트릭</h2>
            <table>
                <thead>
                    <tr>
                        <th>지표</th>
                        <th>값</th>
                        <th>진행률</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Recall@K (Source)</td>
                        <td>{recall_source:.4f}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {recall_source_pct}%"></div>
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td>Recall@K (Page)</td>
                        <td>{recall_page:.4f}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {recall_page_pct}%"></div>
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td>MRR (Source)</td>
                        <td>{mrr_source:.4f}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {mrr_source_pct}%"></div>
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td>MRR (Page)</td>
                        <td>{mrr_page:.4f}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {mrr_page_pct}%"></div>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2 class="section-title">질문별 결과</h2>
            {result_cards}
        </div>

        <div class="footer">
            <p>입찰메이트 v17 | 7팀 | <a href="https://github.com/Loah-Lee/AI_7-team">GitHub</a></p>
        </div>
    </div>

    <script>
        // 동적 색상 적용
        function getScoreColor(score) {{
            if (score >= 4) return '#10b981';
            if (score >= 3) return '#f59e0b';
            return '#ef4444';
        }}

        function getScoreBackground(score) {{
            if (score >= 4) return '#d1fae5';
            if (score >= 3) return '#fef3c7';
            return '#fee2e2';
        }}

        // 페이지 로드 후 점수 색상 적용
        document.addEventListener('DOMContentLoaded', function() {{
            document.querySelectorAll('.score-badge').forEach(badge => {{
                const scoreText = badge.textContent.match(/([0-5](?:\\.\\d+)?)/);
                if (scoreText) {{
                    const score = parseFloat(scoreText[0]);
                    badge.style.background = getScoreBackground(score);
                    badge.style.color = getScoreColor(score);
                }}
            }});
        }});
    </script>
</body>
</html>
"""


def get_score_color(score: float) -> str:
    """점수에 따른 색상을 반환합니다."""
    if score >= 4:
        return '#10b981'
    if score >= 3:
        return '#f59e0b'
    return '#ef4444'


def get_score_background(score: float) -> str:
    """점수에 따른 배경색을 반환합니다."""
    if score >= 4:
        return '#d1fae5'
    if score >= 3:
        return '#fef3c7'
    return '#fee2e2'


def _to_float(value: Any) -> float | None:
    """값을 float으로 변환합니다. 변환할 수 없으면 None을 반환합니다."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    """문자열 값을 안전하게 정제합니다."""
    if value is None:
        return ''
    return str(value).replace('\x00', '')


def _safe_text(value: Any) -> str:
    """HTML에 넣기 안전한 문자열로 변환합니다."""
    return html_lib.escape(_clean_text(value))


def _safe_preview(value: Any, limit: int = 300) -> str:
    """미리보기 문자열을 길이 제한 + HTML escape 처리합니다."""
    text = _clean_text(value)
    if len(text) > limit:
        text = f'{text[:limit]}...'
    return html_lib.escape(text)


def _format_judge_score(value: float | None) -> str:
    """Judge 점수 포맷을 반환합니다."""
    if value is None:
        return 'N/A'
    return f'{value:.2f}/5'


def _build_extra_metric_cards(metrics: dict[str, Any]) -> str:
    """상단 추가 메트릭 카드를 생성합니다."""
    p50 = _to_float(metrics.get('p50_response_time'))
    p90 = _to_float(metrics.get('p90_response_time'))
    avg_slot_fill_rate = _to_float(metrics.get('avg_slot_fill_rate'))
    avg_confidence = _to_float(metrics.get('avg_confidence'))
    mode_distribution = metrics.get('answer_mode_distribution')

    if isinstance(mode_distribution, dict) and mode_distribution:
        mode_text = ', '.join(
            f'{_safe_text(mode)}:{_safe_text(count)}'
            for mode, count in sorted(mode_distribution.items())
        )
    else:
        mode_text = 'N/A'

    cards = [
        (
            '응답시간 P50',
            f'{p50:.2f}s' if p50 is not None else 'N/A',
        ),
        (
            '응답시간 P90',
            f'{p90:.2f}s' if p90 is not None else 'N/A',
        ),
        (
            '평균 Slot Fill',
            f'{avg_slot_fill_rate:.3f}' if avg_slot_fill_rate is not None else 'N/A',
        ),
        (
            '평균 Confidence',
            f'{avg_confidence:.3f}' if avg_confidence is not None else 'N/A',
        ),
        (
            'Answer Mode',
            mode_text,
        ),
    ]

    return '\n'.join(
        f"""
            <div class="metric-card">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
            </div>
        """
        for label, value in cards
    )


def build_result_card(result: dict[str, Any], idx: int, has_judge: bool) -> str:
    """결과 카드 HTML을 생성합니다."""
    correctness = _to_float(result.get('correctness')) if has_judge else None
    if correctness is None:
        card_class = 'no-judge'
    else:
        card_class = 'correct' if correctness >= 4 else ('partial' if correctness >= 2 else 'incorrect')

    query_type = result.get('query_type', 'single_doc')
    query_type_label = {
        'single_doc': '단일 문서',
        'multi_doc': '다중 문서',
        'comparison': '비교'
    }.get(query_type, query_type)
    query_type_label = _safe_text(query_type_label)

    result_id = _safe_text(result.get('id', f'item_{idx + 1}'))
    question = _safe_text(result.get('question', ''))
    expected_answer = _safe_preview(result.get('expected_answer', ''))
    generated_answer = _safe_preview(result.get('generated_answer', ''))

    coverage_score = _to_float(result.get('coverage')) if has_judge else None
    faithfulness_score = _to_float(result.get('faithfulness')) if has_judge else None
    context_score = _to_float(result.get('context_relevance')) if has_judge else None

    response_time = _to_float(result.get('response_time')) or 0.0

    ground_truth = result.get('ground_truth')
    ground_truth_text = ''
    if isinstance(ground_truth, dict):
        source = _clean_text(ground_truth.get('source', '')).strip()
        if source:
            ground_truth_text = f' | 정답 문서: {html_lib.escape(source)}'

    html = f"""
        <div class="result-card {card_class}">
            <div class="result-header">
                <div>
                    <span class="result-id">#{idx + 1} {result_id}</span>
                    <span class="result-type">{query_type_label}</span>
                </div>
            </div>
            <div class="result-question">{question}</div>
            <div class="result-scores">
                <span class="score-badge correctness">정확성: {_format_judge_score(correctness)}</span>
                <span class="score-badge coverage">커버리지: {_format_judge_score(coverage_score)}</span>
                <span class="score-badge faithfulness">충실성: {_format_judge_score(faithfulness_score)}</span>
                <span class="score-badge context">검색: {_format_judge_score(context_score)}</span>
            </div>
            <div class="answer-section">
                <div class="answer-label">기대 답변:</div>
                <div class="answer-content expected">{expected_answer}</div>
            </div>
            <div class="answer-section">
                <div class="answer-label">생성된 답변:</div>
                <div class="answer-content generated">{generated_answer}</div>
            </div>
            <div class="response-time">
                응답 시간: {response_time:.2f}초
                {ground_truth_text}
            </div>
        </div>
    """
    return html


def build_html_report(eval_result: dict[str, Any]) -> str:
    """HTML 리포트를 생성합니다."""
    metrics = eval_result.get('metrics', {})
    results = eval_result.get('results', [])

    has_judge = (
        any(
            key in metrics
            for key in ('avg_correctness', 'avg_coverage', 'avg_faithfulness', 'avg_context_relevance')
        )
        or any('correctness' in result for result in results)
    )

    # 메트릭 추출
    avg_correctness = _to_float(metrics.get('avg_correctness')) if has_judge else None
    avg_coverage = _to_float(metrics.get('avg_coverage')) if has_judge else None
    avg_faithfulness = _to_float(metrics.get('avg_faithfulness')) if has_judge else None
    avg_context_relevance = _to_float(metrics.get('avg_context_relevance')) if has_judge else None
    avg_response_time = _to_float(metrics.get('avg_response_time')) or 0.0
    total_questions = metrics.get('total_questions', len(results))
    recall_source = _to_float(metrics.get('recall_at_k_source')) or 0.0
    recall_page = _to_float(metrics.get('recall_at_k_page')) or 0.0
    mrr_source = _to_float(metrics.get('mrr_source')) or 0.0
    mrr_page = _to_float(metrics.get('mrr_page')) or 0.0

    # 결과 카드 생성
    result_cards = '\n'.join([build_result_card(r, i, has_judge=has_judge) for i, r in enumerate(results)])

    # 메인 점수 색상 계산
    main_score_color = get_score_color(avg_correctness) if avg_correctness is not None else '#6b7280'

    # 진행률 계산
    recall_source_pct = max(0.0, min(100.0, recall_source * 100))
    recall_page_pct = max(0.0, min(100.0, recall_page * 100))
    mrr_source_pct = max(0.0, min(100.0, mrr_source * 100))
    mrr_page_pct = max(0.0, min(100.0, mrr_page * 100))

    extra_metric_cards = _build_extra_metric_cards(metrics)
    report_mode_label = 'Judge 포함 평가' if has_judge else 'No-Judge 평가(검색/성능 중심)'

    # HTML 생성
    html = HTML_TEMPLATE.format(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        report_mode_label=report_mode_label,
        avg_correctness_display=_format_judge_score(avg_correctness),
        avg_coverage_display=_format_judge_score(avg_coverage),
        avg_faithfulness_display=_format_judge_score(avg_faithfulness),
        avg_context_relevance_display=_format_judge_score(avg_context_relevance),
        avg_response_time=avg_response_time,
        total_questions=total_questions,
        recall_source=recall_source,
        recall_page=recall_page,
        mrr_source=mrr_source,
        mrr_page=mrr_page,
        recall_source_pct=recall_source_pct,
        recall_page_pct=recall_page_pct,
        mrr_source_pct=mrr_source_pct,
        mrr_page_pct=mrr_page_pct,
        extra_metric_cards=extra_metric_cards,
        result_cards=result_cards,
        main_score_color=main_score_color
    )

    return html


def main() -> None:
    """메인 진입점 함수."""
    import argparse

    parser = argparse.ArgumentParser(description='평가 결과 HTML 리포트 생성')
    parser.add_argument('--input', default='eval/eval_results.json', help='평가 결과 JSON 경로')
    parser.add_argument('--output', default='eval/eval_report.html', help='출력 HTML 경로')

    args = parser.parse_args()

    # JSON 결과 로드
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"오류: {args.input} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        eval_result = json.load(f)

    # HTML 생성
    html = build_html_report(eval_result)

    # 저장
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"HTML 리포트 생성 완료: {output_path}")


if __name__ == "__main__":
    main()
