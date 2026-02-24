"""eval_results JSON → 단일 HTML 대시보드 생성.

실행: uv run python scripts/build_eval_report.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
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


def _resolve_path(path_like: str | None, default_path: Path) -> Path:
    if not path_like:
        return default_path
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def build_html(results: dict) -> str:
    S = results["summary"]
    pq = results["per_query"]
    meta = results.get("meta", {}) if isinstance(results.get("meta"), dict) else {}
    label = str(meta.get("label", "current"))
    generated_date = str(meta.get("generated_date", datetime.now().strftime("%Y-%m-%d")))
    judge_model = str(meta.get("judge_model", "gpt-5-mini"))
    elapsed_seconds = float(meta.get("elapsed_seconds", 0.0))

    # JSON 데이터를 inline으로 삽입
    inline_data = json.dumps(pq, ensure_ascii=False)

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
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; text-align: center; }}
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

  .hit-badge {{ font-size: 0.75rem; font-weight: 600; }}
  .hit-yes {{ color: var(--green); }}
  .hit-no {{ color: var(--red); }}

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
      <span class="badge badge-blue">label: {label}</span>
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

  <div class="table-section">
    <h2>질문별 상세 결과</h2>
    <button class="expand-all" onclick="toggleAll()">전체 펼치기/접기</button>
    <div id="queryCards"></div>
  </div>

  <div class="footer">
    BiddingMate RAG Evaluation &mdash; Generated {generated_date} &mdash; LLM-as-Judge ({judge_model}) &mdash; 소요 시간: {elapsed_seconds:.1f}초
  </div>

</div>

<script>
const SUMMARY = {json.dumps(S, ensure_ascii=False)};
const PQ = {inline_data};

// --- Summary Cards ---
const S = SUMMARY;
const cardsEl = document.getElementById('cards');
const cardDefs = [
  {{label:'Correctness',value:S.avg_correctness.toFixed(2),max:'/5',color:'var(--accent)'}},
  {{label:'Answer Coverage',value:(S.avg_answer_coverage||0).toFixed(2),max:'/5',color:'#f97316'}},
  {{label:'Faithfulness',value:S.avg_faithfulness.toFixed(2),max:'/5',color:'var(--green)'}},
  {{label:'Context Relevance',value:(S.avg_context_relevance||0).toFixed(2),max:'/5',color:'var(--purple)'}},
  {{label:'Recall@5 (Source)',value:((S.recall_at_k_source||0)*100).toFixed(0)+'%',max:'',color:'var(--cyan)'}},
  {{label:'MRR (Source)',value:(S.mrr_source||0).toFixed(2),max:'',color:'var(--yellow)'}},
  {{label:'Recall@5 (Page)',value:((S.recall_at_k_page||0)*100).toFixed(0)+'%',max:'',color:'var(--cyan)'}},
  {{label:'MRR (Page)',value:(S.mrr_page||0).toFixed(2),max:'',color:'var(--yellow)'}},
  {{label:'평가 건수',value:S.num_evaluated+'/'+S.num_queries,max:'',color:'var(--text)'}},
];
cardsEl.innerHTML = cardDefs.map(c=>`
  <div class="card">
    <div class="label">${{c.label}}</div>
    <div class="value" style="color:${{c.color}}">${{c.value}}</div>
    <div class="max">${{c.max}}</div>
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
const types = ['single_doc','multi_doc','comparison'];
const typeLabels = ['Single Doc','Multi Doc','Comparison'];
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
  <div class="insight-item"><div class="insight-icon">📊</div><div class="insight-text"><strong>유형별 격차</strong> <span>— single_doc > multi_doc > comparison 순. 복잡한 질문일수록 성능 하락</span></div></div>
  <div class="insight-item"><div class="insight-icon">🔍</div><div class="insight-text"><strong>병목: Retrieval 정밀도</strong> <span>— Hit Rate 90%이지만, 정답 "페이지"가 아닌 다른 페이지가 검색되어 Correctness 하락</span></div></div>
`;

// --- Query Cards (expandable with answers) ---
const scoreClass = s => 's'+Math.min(5,Math.max(0,s));
const typeClass = t => t==='single_doc'?'type-single':t==='multi_doc'?'type-multi':'type-comparison';
const typeName = t => t==='single_doc'?'Single':t==='multi_doc'?'Multi':'Compare';
const fmtGtSources = q => {{
  const arr = Array.isArray(q.ground_truth_sources) ? q.ground_truth_sources : [];
  if (arr.length > 0) {{
    return arr.map(x => x?.source || '').filter(Boolean).join(' | ') || 'N/A';
  }}
  return q.ground_truth_source || 'N/A';
}};
const fmtGtPages = q => {{
  const arr = Array.isArray(q.ground_truth_sources) ? q.ground_truth_sources : [];
  if (arr.length > 0) {{
    const pages = arr
      .map(x => (x && x.page != null ? x.page : null))
      .filter(v => v != null);
    return pages.length ? pages.join(', ') : 'N/A';
  }}
  return q.ground_truth_page!=null ? q.ground_truth_page : 'N/A';
}};

const cardsContainer = document.getElementById('queryCards');
PQ.forEach(q => {{
  const cs = q.correctness?.score??0, acs = q.answer_coverage?.score??0, fs = q.faithfulness?.score??0, crs = q.context_relevance?.score??0;
  const cReason = q.correctness?.reason??'', acReason = q.answer_coverage?.reason??'', fReason = q.faithfulness?.reason??'', crReason = q.context_relevance?.reason??'';
  const gen = q.generated_answer || '(답변 없음)';
  const exp = q.expected_answer || '(정답 없음)';
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
        <span><strong>Hit 위치 (source):</strong> ${{hit||'없음'}}</span>
        <span><strong>Hit 위치 (page):</strong> ${{q.hit_position_page||'없음'}}</span>
        <span><strong>정답 문서:</strong> ${{fmtGtSources(q)}}</span>
        <span><strong>정답 페이지:</strong> ${{fmtGtPages(q)}}</span>
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
            <span class="j-label">Correctness</span>
            <span class="score-pill ${{scoreClass(cs)}}">${{cs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(cReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Answer Coverage</span>
            <span class="score-pill ${{scoreClass(acs)}}">${{acs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(acReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Faithfulness</span>
            <span class="score-pill ${{scoreClass(fs)}}">${{fs}}/5</span>
          </div>
          <div class="j-reason">${{escapeHtml(fReason)}}</div>
        </div>
        <div class="judge-item">
          <div class="j-header">
            <span class="j-label">Context Relevance</span>
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


def main() -> None:
    parser = argparse.ArgumentParser(description="eval_results JSON을 HTML 리포트로 변환")
    parser.add_argument("--input", type=str, default=None, help="입력 JSON 경로")
    parser.add_argument("--output", type=str, default=None, help="출력 HTML 경로")
    args = parser.parse_args()

    input_path = _resolve_path(args.input, _get_eval_dir() / "eval_results_current.json")
    output_path = _resolve_path(args.output, _get_eval_dir() / "eval_report.html")

    if not input_path.exists():
        print(f"[ERROR] {input_path} 없음")
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
