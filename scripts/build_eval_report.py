#!/usr/bin/env python3
"""입찰메이트 v17 - 평가 결과 HTML 리포트 생성 스크립트."""

from __future__ import annotations

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
            <div class="subtitle">RFP 문서 기반 지능형 질의응답 시스템</div>
            <div class="timestamp">생성일: {timestamp}</div>
        </div>

        <div class="metrics">
            <div class="metric-card">
                <div class="label">정확성 (Correctness)</div>
                <div class="value score">{avg_correctness:.2f}/5</div>
            </div>
            <div class="metric-card">
                <div class="label">커버리지 (Coverage)</div>
                <div class="value">{avg_coverage:.2f}/5</div>
            </div>
            <div class="metric-card">
                <div class="label">충실성 (Faithfulness)</div>
                <div class="value">{avg_faithfulness:.2f}/5</div>
            </div>
            <div class="metric-card">
                <div class="label">검색 관련성 (Context)</div>
                <div class="value">{avg_context_relevance:.2f}/5</div>
            </div>
            <div class="metric-card">
                <div class="label">평균 응답 시간</div>
                <div class="value">{avg_response_time:.2f}s</div>
            </div>
            <div class="metric-card">
                <div class="label">전체 질문 수</div>
                <div class="value">{total_questions}</div>
            </div>
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
                const scoreText = badge.textContent.match(/[0-5]/);
                if (scoreText) {{
                    const score = parseInt(scoreText[0]);
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


def build_result_card(result: dict[str, Any], idx: int) -> str:
    """결과 카드 HTML을 생성합니다."""
    correctness = result.get('correctness', 0)
    card_class = 'correct' if correctness >= 4 else ('partial' if correctness >= 2 else 'incorrect')

    query_type = result.get('query_type', 'single_doc')
    query_type_label = {
        'single_doc': '단일 문서',
        'multi_doc': '다중 문서',
        'comparison': '비교'
    }.get(query_type, query_type)

    html = f"""
        <div class="result-card {card_class}">
            <div class="result-header">
                <div>
                    <span class="result-id">#{idx + 1} {result['id']}</span>
                    <span class="result-type">{query_type_label}</span>
                </div>
            </div>
            <div class="result-question">{result['question']}</div>
            <div class="result-scores">
                <span class="score-badge correctness">정확성: {result.get('correctness', 0)}/5</span>
                <span class="score-badge coverage">커버리지: {result.get('coverage', 0)}/5</span>
                <span class="score-badge faithfulness">충실성: {result.get('faithfulness', 0)}/5</span>
                <span class="score-badge context">검색: {result.get('context_relevance', 0)}/5</span>
            </div>
            <div class="answer-section">
                <div class="answer-label">기대 답변:</div>
                <div class="answer-content expected">{result['expected_answer'][:300]}{'...' if len(result['expected_answer']) > 300 else ''}</div>
            </div>
            <div class="answer-section">
                <div class="answer-label">생성된 답변:</div>
                <div class="answer-content generated">{result.get('generated_answer', '')[:300]}{'...' if len(result.get('generated_answer', '')) > 300 else ''}</div>
            </div>
            <div class="response-time">
                응답 시간: {result.get('response_time', 0):.2f}초
                {f" | 정답 문서: {result['ground_truth'].get('source', 'N/A')}" if result.get('ground_truth') else ""}
            </div>
        </div>
    """
    return html


def build_html_report(eval_result: dict[str, Any]) -> str:
    """HTML 리포트를 생성합니다."""
    metrics = eval_result.get('metrics', {})
    results = eval_result.get('results', [])

    # 메트릭 추출
    avg_correctness = metrics.get('avg_correctness', 0)
    avg_coverage = metrics.get('avg_coverage', 0)
    avg_faithfulness = metrics.get('avg_faithfulness', 0)
    avg_context_relevance = metrics.get('avg_context_relevance', 0)
    avg_response_time = metrics.get('avg_response_time', 0)
    total_questions = metrics.get('total_questions', len(results))
    recall_source = metrics.get('recall_at_k_source', 0)
    recall_page = metrics.get('recall_at_k_page', 0)
    mrr_source = metrics.get('mrr_source', 0)
    mrr_page = metrics.get('mrr_page', 0)

    # 결과 카드 생성
    result_cards = '\n'.join([build_result_card(r, i) for i, r in enumerate(results)])

    # 메인 점수 색상 계산
    main_score_color = get_score_color(avg_correctness)

    # 진행률 계산
    recall_source_pct = recall_source * 100
    recall_page_pct = recall_page * 100
    mrr_source_pct = mrr_source * 100
    mrr_page_pct = mrr_page * 100

    # HTML 생성
    html = HTML_TEMPLATE.format(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        avg_correctness=avg_correctness,
        avg_coverage=avg_coverage,
        avg_faithfulness=avg_faithfulness,
        avg_context_relevance=avg_context_relevance,
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
        result_cards=result_cards,
        main_score=avg_correctness,
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
