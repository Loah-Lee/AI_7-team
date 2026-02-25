"""eval_results JSON → 단일 HTML 대시보드 생성.

실행: uv run python scripts/build_eval_report.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]


def _get_eval_dir() -> Path:
    """평가 결과 디렉토리 경로를 반환한다. 환경변수 우선, 없으면 eval_resources (fallback: eval)."""
    if custom_dir := os.getenv("EVAL_DIR"):
        return project_root / custom_dir

    eval_resources = project_root / "eval_resources"
    eval_legacy = project_root / "eval"

    if eval_resources.exists():
        return eval_resources
    elif eval_legacy.exists():
        print(f"[WARNING] 'eval/' 폴더가 감지되었습니다. 'eval_resources/'로 이름을 변경하는 것을 권장합니다.")
        return eval_legacy
    else:
        return eval_resources


def build_html(results: dict) -> str:
    S = results["summary"]
    pq = results["per_query"]

    # JSON 데이터를 inline으로 삽입
    inline_data = json.dumps(pq, ensure_ascii=False)

    # 레이턴시 평균 (Python 계산 → 정적 HTML로 임베드)
    _stages = ["analyze_query", "retrieve", "extract_evidence", "generate"]
    _stage_ko = {
        "analyze_query": "질의분석 (analyze)",
        "retrieve": "문서검색 (retrieve)",
        "extract_evidence": "근거추출 (extract_evidence)",
        "generate": "답변생성 (generate)",
    }
    _with_lat = [q for q in pq if q.get("latencies")]
    _n = len(_with_lat)
    _avg = {k: sum(q["latencies"].get(k, 0) for q in _with_lat) / _n if _n else 0 for k in _stages}
    _total = sum(_avg.values())

    def _bar(ratio: float, color: str = "#3b82f6") -> str:
        w = max(2, round(ratio * 120))
        return f'<span style="display:inline-block;width:{w}px;height:6px;border-radius:3px;background:{color};opacity:0.7;vertical-align:middle;margin-left:6px"></span>'

    _colors = {"analyze_query": "#3b82f6", "retrieve": "#06b6d4", "extract_evidence": "#a855f7", "generate": "#22c55e"}
    _lat_rows = "".join(
        f'<tr><td style="color:#d1d5db">{_stage_ko[k]}</td>'
        f'<td style="font-weight:700;color:#f3f4f6">{_avg[k]:.2f}s</td>'
        f'<td style="color:#6b7280">{_avg[k] / _total * 100:.0f}%{_bar(_avg[k] / _total, _colors[k])}</td></tr>'
        for k in _stages
    ) if _total > 0 else "<tr><td colspan='3' style='color:#6b7280'>데이터 없음</td></tr>"
    _lat_tooltip = (
        f'<div class="tt-title">평균 레이턴시 · 단계별 분해</div>'
        f'<div class="tt-desc">전체 파이프라인 평균 소요 시간 ({_n}개 질문 기준)</div>'
        f'<table class="tt-table"><tr><th>단계</th><th>평균</th><th>비중</th></tr>{_lat_rows}</table>'
        f'<div style="margin-top:0.5rem;font-size:0.74rem;color:#6b7280">합계: <strong style="color:#f3f4f6">{_total:.1f}s</strong></div>'
    )
    _lat_value = f"{_total:.1f}s"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BiddingMate RAG 평가 리포트</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"><\/script>
<style>
  :root {{
    --bg: #0a0a0a; --surface: #141414; --surface2: #1e1e1e;
    --border: #2a2a2a; --text: #e5e5e5; --text2: #a1a1a1;
    --accent: #3b82f6; --green: #22c55e; --yellow: #eab308;
    --red: #ef4444; --purple: #a855f7; --cyan: #06b6d4;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem 1.5rem; }}

  .header {{ text-align: center; margin-bottom: 3rem; }}
  .header h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; }}
  .header .subtitle {{ color: var(--text2); font-size: 0.9rem; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin: 0.5rem 0.25rem; }}
  .badge-blue {{ background: rgba(59,130,246,0.15); color: var(--accent); }}
  .badge-green {{ background: rgba(34,197,94,0.15); color: var(--green); }}
  .badge-purple {{ background: rgba(168,85,247,0.15); color: var(--purple); }}

  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2.5rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; text-align: center; position: relative; cursor: default; }}
  .card:hover {{ border-color: #3a3a3a; }}
  .tooltip-box {{
    display: none; position: absolute; top: calc(100% + 10px); left: 50%; transform: translateX(-50%);
    background: #111827; border: 1px solid #374151; border-radius: 10px; padding: 1rem;
    min-width: 300px; max-width: 380px; z-index: 999;
    box-shadow: 0 12px 40px rgba(0,0,0,0.7); font-size: 0.78rem; line-height: 1.6; text-align: left; white-space: normal;
  }}
  .card:hover .tooltip-box {{ display: block; }}
  .tooltip-box .tt-title {{ font-size: 0.88rem; font-weight: 700; color: #f3f4f6; margin-bottom: 0.4rem; }}
  .tooltip-box .tt-desc {{ color: #93c5fd; font-style: italic; margin-bottom: 0.6rem; border-left: 2px solid #3b82f6; padding-left: 0.5rem; }}
  .tooltip-box .tt-kv {{ color: #9ca3af; margin-bottom: 0.25rem; font-size: 0.76rem; }}
  .tooltip-box .tt-kv strong {{ color: #d1d5db; }}
  .tooltip-box .tt-formula {{ font-family: monospace; background: #1f2937; border-radius: 4px; padding: 0.2rem 0.4rem; color: #6ee7b7; font-size: 0.74rem; display: inline-block; margin-top: 0.3rem; }}
  .tt-table {{ width: 100%; border-collapse: collapse; margin-top: 0.6rem; font-size: 0.74rem; }}
  .tt-table th {{ color: #6b7280; font-weight: 600; padding: 0.2rem 0.5rem; border-bottom: 1px solid #374151; text-align: left; }}
  .tt-table td {{ padding: 0.25rem 0.5rem; color: #9ca3af; border-bottom: 1px solid #1f2937; }}
  .tt-table td:first-child {{ font-weight: 700; color: #e5e7eb; min-width: 2rem; text-align: center; }}
  .card .label {{ font-size: 0.75rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
  .card .value {{ font-size: 2rem; font-weight: 700; }}
  .card .max {{ font-size: 0.85rem; color: var(--text2); }}

  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2.5rem; }}
  .chart-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }}
  .chart-box h3 {{ font-size: 0.9rem; color: var(--text2); margin-bottom: 1rem; }}

  .insights {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 2.5rem; }}
  .insights h2 {{ font-size: 1.1rem; margin-bottom: 1rem; }}
  .insight-item {{ display: flex; gap: 0.75rem; margin-bottom: 0.75rem; padding: 0.75rem; background: var(--surface2); border-radius: 8px; }}
  .insight-icon {{ font-size: 1.2rem; flex-shrink: 0; }}
  .insight-text {{ font-size: 0.85rem; }}
  .insight-text strong {{ color: var(--text); }}
  .insight-text span {{ color: var(--text2); }}

  .table-section {{ margin-bottom: 2.5rem; }}
  .table-section h2 {{ font-size: 1.1rem; margin-bottom: 1rem; }}

  /* Query Cards */
  .query-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 1rem; overflow: hidden; }}
  .query-header {{ display: flex; align-items: center; gap: 1rem; padding: 1rem 1.25rem; cursor: pointer; user-select: none; }}
  .query-header:hover {{ background: var(--surface2); }}
  .query-id {{ font-weight: 700; font-size: 0.85rem; min-width: 3rem; color: var(--accent); }}
  .query-q {{ flex: 1; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .query-scores {{ display: flex; gap: 0.5rem; flex-shrink: 0; }}
  .query-chevron {{ color: var(--text2); transition: transform 0.2s; font-size: 0.8rem; }}
  .query-card.open .query-chevron {{ transform: rotate(90deg); }}

  .query-body {{ display: none; padding: 0 1.25rem 1.25rem; border-top: 1px solid var(--border); }}
  .query-card.open .query-body {{ display: block; padding-top: 1.25rem; }}

  .answer-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }}
  .answer-box {{ background: var(--surface2); border-radius: 8px; padding: 1rem; }}
  .answer-box .box-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text2); margin-bottom: 0.5rem; font-weight: 600; }}
  .answer-box .box-content {{ font-size: 0.82rem; line-height: 1.7; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; }}
  .answer-box.expected .box-label {{ color: var(--green); }}
  .answer-box.generated .box-label {{ color: var(--accent); }}

  .judge-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.75rem; }}
  .judge-item {{ background: var(--surface2); border-radius: 8px; padding: 0.75rem; }}
  .judge-item .j-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }}
  .judge-item .j-label {{ font-size: 0.75rem; font-weight: 600; color: var(--text2); text-transform: uppercase; }}
  .judge-item .j-reason {{ font-size: 0.78rem; color: var(--text2); line-height: 1.5; }}

  .meta-row {{ display: flex; gap: 1.5rem; margin-bottom: 1rem; font-size: 0.8rem; color: var(--text2); }}
  .meta-row strong {{ color: var(--text); }}

  .score-pill {{ display: inline-block; min-width: 1.8rem; padding: 0.15rem 0.45rem; border-radius: 6px; font-weight: 700; text-align: center; font-size: 0.8rem; }}
  .s5 {{ background: rgba(34,197,94,0.2); color: var(--green); }}
  .s4 {{ background: rgba(34,197,94,0.1); color: #86efac; }}
  .s3 {{ background: rgba(234,179,8,0.15); color: var(--yellow); }}
  .s2 {{ background: rgba(249,115,22,0.15); color: #fb923c; }}
  .s1 {{ background: rgba(239,68,68,0.15); color: var(--red); }}
  .s0 {{ background: rgba(239,68,68,0.2); color: var(--red); }}

  .type-tag {{ font-size: 0.7rem; padding: 0.15rem 0.4rem; border-radius: 4px; font-weight: 600; }}
  .type-single {{ background: rgba(59,130,246,0.15); color: var(--accent); }}
  .type-multi {{ background: rgba(168,85,247,0.15); color: var(--purple); }}
  .type-comparison {{ background: rgba(6,182,212,0.15); color: var(--cyan); }}
  .type-csv {{ background: rgba(234,179,8,0.15); color: #eab308; }}

  .hit-badge {{ font-size: 0.75rem; font-weight: 600; }}
  .hit-yes {{ color: var(--green); }}
  .hit-no {{ color: var(--red); }}
  .j-label-ko {{ font-size: 0.65rem; color: var(--text2); font-weight: 400; margin-left: 0.2rem; }}
  .latency-row {{ font-size: 0.78rem; color: var(--text2); font-family: monospace; }}

  .latency-section {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 2.5rem; }}
  .latency-section h2 {{ font-size: 1.1rem; margin-bottom: 1rem; }}
  .latency-table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; }}
  .latency-table th {{ text-align: left; color: var(--text2); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }}
  .latency-table td {{ padding: 0.55rem 0.75rem; border-bottom: 1px solid var(--border); color: var(--text); }}
  .latency-table tr:last-child td {{ border-bottom: none; }}
  .latency-table tr.total-row td {{ font-weight: 700; color: var(--accent); background: rgba(59,130,246,0.05); }}
  .latency-table .stage-col {{ color: var(--text2); font-size: 0.78rem; }}
  .latency-bar {{ display: inline-block; height: 6px; border-radius: 3px; margin-left: 0.4rem; vertical-align: middle; opacity: 0.6; }}

  .footer {{ text-align: center; color: var(--text2); font-size: 0.75rem; padding: 2rem 0 1rem; border-top: 1px solid var(--border); }}

  .expand-all {{ background: var(--surface2); border: 1px solid var(--border); color: var(--text2); padding: 0.4rem 1rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; margin-bottom: 1rem; }}
  .expand-all:hover {{ color: var(--text); border-color: var(--text2); }}

  @media (max-width: 768px) {{
    .charts {{ grid-template-columns: 1fr; }}
    .cards {{ grid-template-columns: repeat(2, 1fr); }}
    .answer-grid {{ grid-template-columns: 1fr; }}
    .judge-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>BiddingMate RAG 평가 리포트</h1>
    <p class="subtitle">LLM-as-Judge 기반 End-to-End 평가 결과</p>
    <div>
      <span class="badge badge-blue">label: {results.get('meta',{}).get('label','current')}</span>
      <span class="badge badge-green">{S['num_queries']}개 질문</span>
      <span class="badge badge-purple">top_k: {S['top_k']}</span>
    </div>
  </div>

  <div class="cards" id="cards"></div>

  <div class="charts">
    <div class="chart-box"><h3>LLM Judge 평균 점수</h3><canvas id="radarChart"></canvas></div>
    <div class="chart-box"><h3>질의 유형별 평균 점수</h3><canvas id="barChart"></canvas></div>
    <div class="chart-box"><h3>질문별 점수 분포</h3><canvas id="heatChart"></canvas></div>
    <div class="chart-box"><h3>Correctness 점수 분포</h3><canvas id="distChart"></canvas></div>
  </div>

  <div class="insights" id="insights"></div>

  <div class="latency-section">
    <h2>평균 레이턴시 (단계별)</h2>
    <table class="latency-table" id="latencyTable"></table>
  </div>

  <div class="table-section">
    <h2>질문별 상세 결과</h2>
    <button class="expand-all" onclick="toggleAll()">전체 펼치기/접기</button>
    <div id="queryCards"></div>
  </div>

  <div class="footer">
    BiddingMate RAG Evaluation &mdash; Generated 2026-02-10 &mdash; LLM-as-Judge (gpt-5-mini) &mdash; 소요 시간: {results.get('meta',{}).get('elapsed_seconds',0)}초
  </div>

</div>

<script>
const SUMMARY = {json.dumps(S, ensure_ascii=False)};
const PQ = {inline_data};

// --- Summary Cards ---
const S = SUMMARY;
const cardsEl = document.getElementById('cards');
const TTScoreTable = (rows) => `<table class="tt-table"><tr><th>점수</th><th>기준</th></tr>${{rows.map(r=>`<tr><td>${{r[0]}}</td><td>${{r[1]}}</td></tr>`).join('')}}</table>`;
const LLM_ROWS = [
  [5,'기대 답변의 핵심 정보를 모두 정확히 포함'],
  [4,'대부분 정확하나 사소한 부정확 있음'],
  [3,'핵심의 절반 정도가 정확'],
  [2,'일부만 맞고 오류 포함'],
  [1,'거의 관련 없는 답변'],
  [0,'완전히 틀리거나 답변 거부'],
];
const AC_ROWS = [
  [5,'기대 답변의 모든 핵심 포인트를 빠짐없이 포함'],
  [4,'대부분 포함하나 사소한 항목 1~2개 누락'],
  [3,'핵심 포인트의 절반 정도만 커버'],
  [2,'주요 정보 대부분 누락, 일부만 언급'],
  [1,'핵심 정보가 거의 없음'],
  [0,'관련 정보 전혀 없음 또는 답변 거부'],
];
const F_ROWS = [
  [5,'모든 내용이 context에서 직접 확인 가능'],
  [4,'대부분 근거 있으나 사소한 추론 포함'],
  [3,'핵심은 있으나 상당한 추론/일반화 포함'],
  [2,'부분적으로만 관련, 환각 포함'],
  [1,'대부분 환각이거나 context와 무관'],
  [0,'완전한 환각 또는 context 무시'],
];
const CR_ROWS = [
  [5,'context가 질문에 완벽히 관련, 충분한 정보 포함'],
  [4,'대부분 관련, 일부 불필요한 내용'],
  [3,'부분적 관련, 핵심 정보 일부 부족'],
  [2,'관련성 낮고 대부분 무관'],
  [1,'거의 관련 없는 문서'],
  [0,'완전히 무관'],
];

const cardDefs = [
  {{label:'Correctness',ko:'정확성',value:S.avg_correctness.toFixed(2),max:'/5',color:'var(--accent)',
    tooltip:`<div class="tt-title">Correctness · 정확성</div>
      <div class="tt-desc">생성된 답변이 기대 답변과 의미적으로 일치하는가?</div>
      <div class="tt-kv"><strong>관점:</strong> 답변의 정확성 — 맞는 정보인가</div>
      <div class="tt-kv"><strong>판단 기준:</strong> 기대 답변의 핵심 사실과 생성 답변의 사실이 일치하는 정도</div>
      <div class="tt-kv"><strong>Coverage와의 차이:</strong> Correctness는 "틀린 정보가 있는가"에 초점</div>
      ${{TTScoreTable(LLM_ROWS)}}`}},
  {{label:'Answer Coverage',ko:'답변 커버리지',value:(S.avg_answer_coverage||0).toFixed(2),max:'/5',color:'#f97316',
    tooltip:`<div class="tt-title">Answer Coverage · 답변 커버리지</div>
      <div class="tt-desc">기대 답변의 핵심 정보가 생성 답변에 얼마나 누락 없이 포함되었는가?</div>
      <div class="tt-kv"><strong>관점:</strong> 답변의 완전성 — 빠진 정보가 없는가</div>
      <div class="tt-kv"><strong>판단 기준:</strong> 기대 답변의 핵심 포인트 목록 대비 생성 답변이 커버한 비율</div>
      <div class="tt-kv"><strong>Correctness와의 차이:</strong> Coverage는 "빠진 정보가 있는가"에 초점</div>
      ${{TTScoreTable(AC_ROWS)}}`}},
  {{label:'Faithfulness',ko:'충실성',value:S.avg_faithfulness.toFixed(2),max:'/5',color:'var(--green)',
    tooltip:`<div class="tt-title">Faithfulness · 충실성</div>
      <div class="tt-desc">생성된 답변이 검색된 context에 근거하고 있는가? (환각 없는가)</div>
      <div class="tt-kv"><strong>관점:</strong> 답변의 근거 충실도</div>
      <div class="tt-kv"><strong>판단 기준:</strong> 답변의 각 주장이 검색된 context에서 확인 가능한 정도</div>
      ${{TTScoreTable(F_ROWS)}}`}},
  {{label:'Context Relevance',ko:'검색 관련성',value:(S.avg_context_relevance||0).toFixed(2),max:'/5',color:'var(--purple)',
    tooltip:`<div class="tt-title">Context Relevance · 검색 관련성</div>
      <div class="tt-desc">검색된 context가 질문에 실제로 관련 있는가?</div>
      <div class="tt-kv"><strong>관점:</strong> 검색 품질</div>
      <div class="tt-kv"><strong>판단 기준:</strong> 검색된 문서가 질문에 답하는 데 필요한 정보를 포함하는 정도</div>
      ${{TTScoreTable(CR_ROWS)}}`}},
  {{label:'Recall@5 (Source)',ko:'검색 재현율·문서',value:((S.recall_at_k_source||0)*100).toFixed(0)+'%',max:'',color:'var(--cyan)',
    tooltip:`<div class="tt-title">Recall@K (Source) · 검색 재현율 — 문서 단위</div>
      <div class="tt-desc">top-K 검색 결과에 정답 문서(source 기준)가 포함된 질문의 비율</div>
      <div class="tt-kv"><strong>범위:</strong> 0.0 ~ 1.0</div>
      <div class="tt-kv"><strong>매칭:</strong> 파일명(source)만 일치하면 hit</div>
      <div class="tt-kv"><strong>multi_doc (Strict):</strong> sources 리스트의 모든 source가 top-K에 있어야 1.0. 하나라도 누락 시 0.0</div>
      <span class="tt-formula">(Recall@K > 0인 질문 수) / 전체 질문 수</span>`}},
  {{label:'MRR (Source)',ko:'평균 역순위·문서',value:(S.mrr_source||0).toFixed(2),max:'',color:'var(--yellow)',
    tooltip:`<div class="tt-title">MRR (Source) · 평균 역순위 — 문서 단위</div>
      <div class="tt-desc">정답 문서(source 기준)가 검색 결과에서 몇 번째에 위치하는지의 역수 평균</div>
      <div class="tt-kv"><strong>범위:</strong> 0.0 ~ 1.0</div>
      <div class="tt-kv"><strong>매칭:</strong> 파일명(source)만 일치하면 hit</div>
      <span class="tt-formula">mean(1/rank) — 정답 없으면 0</span>`}},
  {{label:'Avg Latency',ko:'평균 응답시간',value:'{_lat_value}',max:'',color:'var(--cyan)',
    tooltip:`{_lat_tooltip}`}},
  {{label:'평가 건수',ko:'',value:S.num_evaluated+'/'+S.num_queries,max:'',color:'var(--text)',tooltip:null}},
];
cardsEl.innerHTML = cardDefs.map(c=>`
  <div class="card">
    <div class="label">${{c.label}}${{c.ko?`<br><span style="font-size:0.7rem;color:var(--text2);text-transform:none;letter-spacing:0">${{c.ko}}</span>`:''}}</div>
    <div class="value" style="color:${{c.color}}">${{c.value}}</div>
    <div class="max">${{c.max}}</div>
    ${{c.tooltip?`<div class="tooltip-box">${{c.tooltip}}</div>`:''}}
  </div>
`).join('');

// --- Radar ---
new Chart(document.getElementById('radarChart'), {{
  type: 'radar',
  data: {{
    labels: ['Correctness', 'Answer Coverage', 'Faithfulness', 'Context Relevance', 'Recall@K (x5)', 'MRR (x5)'],
    datasets: [{{
      label: '현재 성능',
      data: [S.avg_correctness, S.avg_answer_coverage||0, S.avg_faithfulness, S.avg_context_relevance||0, (S.recall_at_k_source||0)*5, (S.mrr_source||0)*5],
      backgroundColor: 'rgba(59,130,246,0.15)',
      borderColor: 'rgba(59,130,246,0.8)',
      pointBackgroundColor: 'rgba(59,130,246,1)',
      borderWidth: 2
    }}]
  }},
  options: {{
    scales: {{ r: {{ min:0, max:5, ticks:{{stepSize:1,color:'#666'}}, grid:{{color:'#2a2a2a'}}, pointLabels:{{color:'#a1a1a1',font:{{size:11}}}} }} }},
    plugins: {{ legend: {{display:false}} }}
  }}
}});

// --- Bar by type ---
const types = ['csv_match','single_doc','multi_doc'];
const typeLabels = ['CSV Match','Single Doc','Multi Doc'];
const byType = {{}};
PQ.forEach(q => {{
  const t = q.query_type || 'unknown';
  if (!byType[t]) byType[t] = {{c:[],ac:[],f:[],cr:[]}};
  byType[t].c.push(q.correctness?.score??0);
  byType[t].ac.push(q.answer_coverage?.score??0);
  byType[t].f.push(q.faithfulness?.score??0);
  byType[t].cr.push(q.context_relevance?.score??0);
}});
const avg = arr => arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0;

new Chart(document.getElementById('barChart'), {{
  type: 'bar',
  data: {{
    labels: typeLabels,
    datasets: [
      {{label:'Correctness', data:types.map(t=>avg(byType[t]?.c||[])), backgroundColor:'rgba(59,130,246,0.7)'}},
      {{label:'Answer Coverage', data:types.map(t=>avg(byType[t]?.ac||[])), backgroundColor:'rgba(249,115,22,0.7)'}},
      {{label:'Faithfulness', data:types.map(t=>avg(byType[t]?.f||[])), backgroundColor:'rgba(34,197,94,0.7)'}},
      {{label:'Context Relevance', data:types.map(t=>avg(byType[t]?.cr||[])), backgroundColor:'rgba(168,85,247,0.7)'}},
    ]
  }},
  options: {{
    scales: {{ y:{{min:0,max:5,ticks:{{color:'#666'}},grid:{{color:'#2a2a2a'}}}}, x:{{ticks:{{color:'#a1a1a1'}},grid:{{display:false}}}} }},
    plugins: {{ legend:{{labels:{{color:'#a1a1a1',font:{{size:11}}}}}} }}
  }}
}});

// --- Per-query bar ---
new Chart(document.getElementById('heatChart'), {{
  type: 'bar',
  data: {{
    labels: PQ.map(q => q.id?.replace('eval_','')),
    datasets: [
      {{label:'C', data:PQ.map(q=>q.correctness?.score??0), backgroundColor:PQ.map(q=>{{const s=q.correctness?.score??0; return s>=4?'rgba(34,197,94,0.6)':s>=3?'rgba(234,179,8,0.6)':'rgba(239,68,68,0.6)';}})}},
      {{label:'AC', data:PQ.map(q=>q.answer_coverage?.score??0), backgroundColor:'rgba(249,115,22,0.4)'}},
      {{label:'F', data:PQ.map(q=>q.faithfulness?.score??0), backgroundColor:'rgba(34,197,94,0.3)'}},
      {{label:'CR', data:PQ.map(q=>q.context_relevance?.score??0), backgroundColor:'rgba(168,85,247,0.3)'}},
    ]
  }},
  options: {{
    scales: {{ y:{{min:0,max:5,ticks:{{color:'#666'}},grid:{{color:'#2a2a2a'}}}}, x:{{ticks:{{color:'#a1a1a1',font:{{size:9}}}},grid:{{display:false}}}} }},
    plugins: {{ legend:{{labels:{{color:'#a1a1a1',font:{{size:10}}}}}} }}
  }}
}});

// --- Doughnut ---
const cScores = PQ.map(q=>q.correctness?.score??0);
const dist = [0,1,2,3,4,5].map(s => cScores.filter(v=>v===s).length);
new Chart(document.getElementById('distChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['0점','1점','2점','3점','4점','5점'],
    datasets: [{{
      data: dist,
      backgroundColor: ['rgba(239,68,68,0.7)','rgba(239,68,68,0.5)','rgba(249,115,22,0.6)','rgba(234,179,8,0.6)','rgba(34,197,94,0.5)','rgba(34,197,94,0.7)'],
      borderWidth: 0
    }}]
  }},
  options: {{ plugins: {{ legend:{{position:'right', labels:{{color:'#a1a1a1',font:{{size:11}},padding:12}}}} }} }}
}});

// --- Insights ---
const perfect = PQ.filter(q=>(q.correctness?.score??0)===5).length;
const weak = PQ.filter(q=>(q.correctness?.score??0)<=2).length;
document.getElementById('insights').innerHTML = `
  <h2>핵심 인사이트</h2>
  <div class="insight-item"><div class="insight-icon">✅</div><div class="insight-text"><strong>Faithfulness ${{S.avg_faithfulness}}/5</strong> <span>— 환각이 거의 없음. context에 없는 정보를 만들어내지 않음</span></div></div>
  <div class="insight-item"><div class="insight-icon">🎯</div><div class="insight-text"><strong>Correctness 만점 ${{perfect}}/20건</strong> <span>— single_doc 유형에서 특히 강함. 정답 청크가 검색되면 높은 정확도</span></div></div>
  <div class="insight-item"><div class="insight-icon">⚠️</div><div class="insight-text"><strong>저조 항목 ${{weak}}건 (Correctness ≤ 2)</strong> <span>— 공통 원인: 정답 청크가 top-5에 미포함 → "근거 없음" 응답</span></div></div>
  <div class="insight-item"><div class="insight-icon">📊</div><div class="insight-text"><strong>유형별 격차</strong> <span>— single_doc > multi_doc 순. csv_match는 벡터 검색 미사용 (별도 판단 필요)</span></div></div>
  <div class="insight-item"><div class="insight-icon">🔍</div><div class="insight-text"><strong>병목: Retrieval 정밀도</strong> <span>— Hit Rate 90%이지만, 정답 "페이지"가 아닌 다른 페이지가 검색되어 Correctness 하락</span></div></div>
`;

// --- Latency Table ---
(function() {{
  const stages = ['analyze_query','retrieve','extract_evidence','generate'];
  const stageLabels = ['analyze_query','retrieve','extract_evidence','generate'];
  const groups = {{
    '전체 평균': PQ,
    'CSV Match': PQ.filter(q=>q.query_type==='csv_match'),
    'Single Doc': PQ.filter(q=>q.query_type==='single_doc'),
    'Multi Doc':  PQ.filter(q=>q.query_type==='multi_doc'),
  }};

  // 최대 total 구해서 bar 너비 기준 잡기
  const allTotals = PQ.filter(q=>q.latencies).map(q=>stages.reduce((s,k)=>s+(q.latencies[k]||0),0));
  const maxTotal = Math.max(...allTotals, 1);

  const table = document.getElementById('latencyTable');
  const header = `<thead><tr>
    <th>구간</th>
    <th>analyze_query</th><th>retrieve</th><th>extract_evidence</th><th>generate</th>
    <th>합계</th><th>n</th>
  </tr></thead>`;

  const rows = Object.entries(groups).map(([label, items], idx) => {{
    const withLat = items.filter(q=>q.latencies && Object.keys(q.latencies).length > 0);
    const n = withLat.length;
    if (!n) return `<tr><td colspan="7" style="color:var(--text2);padding:0.5rem 0.75rem">${{label}}: 레이턴시 데이터 없음 (chatbot 모드)</td></tr>`;
    const avgs = stages.map(k => withLat.reduce((s,q)=>s+(q.latencies[k]||0),0)/n);
    const total = avgs.reduce((a,b)=>a+b,0);
    const barW = Math.round((total/maxTotal)*80);
    const isTotal = idx===0;
    return `<tr class="${{isTotal?'total-row':''}}">
      <td>${{label}}</td>
      ${{avgs.map(v=>`<td>${{v.toFixed(2)}}s</td>`).join('')}}
      <td>${{total.toFixed(2)}}s<span class="latency-bar" style="width:${{barW}}px;background:var(--accent)"></span></td>
      <td class="stage-col">${{n}}</td>
    </tr>`;
  }}).join('');

  table.innerHTML = header + `<tbody>${{rows}}</tbody>`;
}})();

// --- Query Cards (expandable with answers) ---
const scoreClass = s => 's'+Math.min(5,Math.max(0,s));
const typeClass = t => t==='single_doc'?'type-single':t==='multi_doc'?'type-multi':t==='csv_match'?'type-csv':'type-comparison';
const typeName = t => t==='single_doc'?'Single':t==='multi_doc'?'Multi':t==='csv_match'?'CSV':'Compare';
const CONVERTED_DOC_EXTS = new Set(['hwp', 'hwpx', 'pdf']);

function normalizeSourceName(src) {{
  return (src || '').toString().normalize('NFC').trim().split(/[\\\\/]/).pop().toLowerCase();
}}

function splitSourceParts(src) {{
  const name = normalizeSourceName(src);
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return {{ name, stem: name, ext: '' }};
  return {{ name, stem: name.slice(0, dot), ext: name.slice(dot + 1) }};
}}

function normalizeStemForEquivalence(stem) {{
  return (stem || '')
    .toString()
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^0-9a-z\\u3131-\\uD79D]+/g, '');
}}

function isEquivalentSource(a, b) {{
  const pa = splitSourceParts(a);
  const pb = splitSourceParts(b);
  if (!pa.name || !pb.name) return false;
  if (pa.name === pb.name) return true;
  if (pa.stem === pb.stem && CONVERTED_DOC_EXTS.has(pa.ext) && CONVERTED_DOC_EXTS.has(pb.ext)) {{
    return true;
  }}
  if (
    normalizeStemForEquivalence(pa.stem) === normalizeStemForEquivalence(pb.stem)
    && CONVERTED_DOC_EXTS.has(pa.ext)
    && CONVERTED_DOC_EXTS.has(pb.ext)
  ) {{
    return true;
  }}
  return false;
}}

function cleanAnswerForDisplay(text) {{
  const raw = (text || '').toString().normalize('NFKC').replace(/\\r\\n/g, '\\n');
  if (!raw.trim()) return raw;

  const lines = [];
  for (const original of raw.split('\\n')) {{
    let line = original
      .replace(/^\\s*[-*•]\\s*/, '')
      .replace(/^#+\\s*/, '')
      .replace(/\\s+/g, ' ')
      .trim();

    if (!line) continue;

    line = line
      .replace(/Col\\d+\\s*:\\s*/gi, '')
      .replace(/요구\\s*사항\\s*상세\\s*설명\\s*,?/g, '')
      .replace(/세부\\s*내용\\s*,?/g, '')
      .replace(/\\[\\s*\\d+\\s*\\[/g, '[')
      .replace(/(\\S+)\\s+\\1(\\s+\\1)+/g, '$1')
      .trim();

    if (!line) continue;
    if (!/[A-Za-z0-9가-힣]/.test(line)) continue;

    const weirdChars = (line.match(/[^\\w\\s가-힣\\.\\,\\-\\:\\;\\(\\)\\/%\\`\\|\\[\\]'\\"~]/g) || []).length;
    if (line.length >= 24 && weirdChars / line.length > 0.35) continue;

    const compact = line.replace(/\\s+/g, '');
    if (compact.length > 120 && !/[.!?]/.test(line)) {{
      line = `${{line.slice(0, 120)}} ...`;
    }}

    lines.push(line);
  }}

  const deduped = [];
  const seen = new Set();
  for (const line of lines) {{
    const key = line.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(line);
  }}

  if (!deduped.length) return raw.trim();
  return deduped.join('\\n');
}}

const cardsContainer = document.getElementById('queryCards');
PQ.forEach(q => {{
  const cs = q.correctness?.score??0, acs = q.answer_coverage?.score??0, fs = q.faithfulness?.score??0, crs = q.context_relevance?.score??0;
  const cReason = q.correctness?.reason??'', acReason = q.answer_coverage?.reason??'', fReason = q.faithfulness?.reason??'', crReason = q.context_relevance?.reason??'';
  const gen = cleanAnswerForDisplay(q.generated_answer || '(답변 없음)');
  const exp = cleanAnswerForDisplay(q.expected_answer || '(정답 없음)');
  const hit = q.hit_position;
  const qt = q.query_type || 'unknown';

  const card = document.createElement('div');
  card.className = 'query-card';
  card.innerHTML = `
    <div class="query-header" onclick="this.parentElement.classList.toggle('open')">
      <span class="query-id">${{q.id?.replace('eval_','#')}}</span>
      <span class="type-tag ${{typeClass(qt)}}">${{typeName(qt)}}</span>
      <span class="query-q">${{q.question||''}}</span>
      <span class="query-scores">
        <span class="score-pill ${{scoreClass(cs)}}" title="Correctness">C:${{cs}}</span>
        <span class="score-pill ${{scoreClass(acs)}}" title="Answer Coverage">AC:${{acs}}</span>
        <span class="score-pill ${{scoreClass(fs)}}" title="Faithfulness">F:${{fs}}</span>
        <span class="score-pill ${{scoreClass(crs)}}" title="Context Relevance">CR:${{crs}}</span>
        <span class="hit-badge ${{hit?'hit-yes':'hit-no'}}">${{hit?'Hit@'+hit:'MISS'}}</span>
      </span>
      <span class="query-chevron">▶</span>
    </div>
    <div class="query-body">
      <div class="meta-row">
        <span><strong>유형:</strong> ${{qt}}</span>
        <span><strong>검색 문서:</strong> ${{q.num_retrieved||0}}개</span>
        <span><strong>Hit (source):</strong> <span class="${{hit?'hit-yes':'hit-no'}}">${{hit?'Hit@'+hit:'MISS'}}</span></span>
        <span><strong>Recall@K (source):</strong> ${{(q.recall_at_k*100).toFixed(0)}}%</span>
      </div>
      <div class="meta-row" style="flex-direction:column;gap:0.4rem">
        <span><strong>정답 문서:</strong> ${{(q.ground_truth_sources||[]).map(s=>`<code style="font-size:0.76rem;background:rgba(59,130,246,0.1);color:#93c5fd;padding:0.1rem 0.4rem;border-radius:3px">${{s}}</code>`).join(' ')}}</span>
        <span><strong>검색된 문서:</strong> ${{(q.retrieved_sources||[]).map(s=>{{
          const isHit = (q.ground_truth_sources||[]).some(gt=>isEquivalentSource(s, gt));
          return `<code style="font-size:0.76rem;background:${{isHit?'rgba(34,197,94,0.12)':'rgba(239,68,68,0.08)'}};color:${{isHit?'#86efac':'#fca5a5'}};padding:0.1rem 0.4rem;border-radius:3px">${{s}}</code>`;
        }}).join(' ')}}</span>
      </div>
      <div class="meta-row latency-row">
        ${{q.latencies?`<span><strong>지연시간:</strong> analyze=${{(q.latencies.analyze_query||0).toFixed(1)}}s | retrieve=${{(q.latencies.retrieve||0).toFixed(2)}}s | evidence=${{(q.latencies.extract_evidence||0).toFixed(1)}}s | generate=${{(q.latencies.generate||0).toFixed(1)}}s</span>`:''}}</span>
      </div>
      <div class="answer-grid">
        <div class="answer-box expected">
          <div class="box-label">기대 답변 (Expected)</div>
          <div class="box-content">${{escapeHtml(exp)}}</div>
        </div>
        <div class="answer-box generated">
          <div class="box-label">생성 답변 (Generated)</div>
          <div class="box-content">${{escapeHtml(gen)}}</div>
        </div>
      </div>
      <div class="judge-grid">
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Correctness <span class="j-label-ko">정확성</span></span>
            <span class="score-pill ${{scoreClass(cs)}}">${{cs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(cReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Answer Coverage <span class="j-label-ko">커버리지</span></span>
            <span class="score-pill ${{scoreClass(acs)}}">${{acs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(acReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Faithfulness <span class="j-label-ko">충실성</span></span>
            <span class="score-pill ${{scoreClass(fs)}}">${{fs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(fReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Context Relevance <span class="j-label-ko">검색관련성</span></span>
            <span class="score-pill ${{scoreClass(crs)}}">${{crs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(crReason)}}</div>
        </div>
      </div>
    </div>
  `;
  cardsContainer.appendChild(card);
}});

function escapeHtml(text) {{
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}}

let allOpen = false;
function toggleAll() {{
  allOpen = !allOpen;
  document.querySelectorAll('.query-card').forEach(c => {{
    if (allOpen) c.classList.add('open');
    else c.classList.remove('open');
  }});
}}
<\/script>
</body>
</html>"""


def main():
    import argparse

    parser = argparse.ArgumentParser(description="eval_results JSON → HTML 대시보드")
    parser.add_argument(
        "--label",
        type=str,
        default="current",
        help="eval_results_{label}.json 을 읽어 eval_report_{label}.html 생성 (기본: current)",
    )
    args = parser.parse_args()

    eval_dir = _get_eval_dir()
    input_path = eval_dir / f"eval_results_{args.label}.json"
    output_path = eval_dir / f"eval_report_{args.label}.html"

    if not input_path.exists():
        print(f"[ERROR] {input_path} 없음")
        print(f"       먼저 실행: uv run python scripts/eval_retrieval.py --label {args.label}")
        return

    with open(input_path, encoding="utf-8") as f:
        results = json.load(f)

    html = build_html(results)
    # f-string 안에서 </script>를 직접 쓸 수 없으므로 후처리
    html = html.replace("<\\/script>", "</script>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] {output_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
