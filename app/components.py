from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


FAQ_QUESTIONS = [
    "예산 규모와 집행 조건을 요약해줘",
    "사업 기간과 주요 마일스톤을 정리해줘",
    "참가 자격 요건을 알려줘",
    "필수 제출서류 체크리스트를 만들어줘",
    "평가 항목과 배점을 정리해줘",
    "마감일과 일정 리스크를 알려줘",
]

CARD_META: dict[str, dict[str, str]] = {
    "예산":    {"icon": "💰", "color": "#10A37F"},
    "기간":    {"icon": "📅", "color": "#6366F1"},
    "참가요건": {"icon": "✅", "color": "#F59E0B"},
    "제출서류": {"icon": "📋", "color": "#3B82F6"},
    "평가항목": {"icon": "⭐", "color": "#EC4899"},
    "마감일":  {"icon": "⏰", "color": "#EF4444"},
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        /* ── Base ── */
        .stApp { background: #FFFFFF; color: #0F172A; }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: #F8FAFC !important;
            border-right: 1px solid #E2E8F0;
        }

        /* ── App Header ── */
        .app-header {
            background: linear-gradient(135deg, #10A37F 0%, #0D8A6A 55%, #0B7A5E 100%);
            border-radius: 16px;
            padding: 26px 32px;
            margin-bottom: 24px;
        }
        .app-header-title {
            font-size: 1.65rem;
            font-weight: 700;
            color: white;
            margin: 0;
            letter-spacing: -0.02em;
        }
        .app-header-sub {
            color: rgba(255,255,255,0.82);
            font-size: 0.88rem;
            margin-top: 5px;
        }
        .app-header-badge {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            border: 1px solid rgba(255,255,255,0.35);
            border-radius: 999px;
            padding: 2px 12px;
            font-size: 0.75rem;
            color: white;
            margin-top: 12px;
        }

        /* ── Summary Cards ── */
        .summary-card {
            border: 1px solid #E2E8F0;
            border-radius: 14px;
            padding: 16px 14px 16px 20px;
            margin-bottom: 12px;
            background: #FFFFFF;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            transition: box-shadow 0.2s ease, transform 0.2s ease;
            min-height: 110px;
            position: relative;
            overflow: hidden;
        }
        .summary-card:hover {
            box-shadow: 0 6px 18px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }
        .summary-card-accent {
            position: absolute;
            top: 0; left: 0;
            width: 5px; height: 100%;
            border-radius: 14px 0 0 14px;
        }
        .summary-key {
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: #64748B;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .summary-value {
            color: #0F172A;
            font-size: 0.88rem;
            line-height: 1.55;
            font-weight: 400;
        }

        /* ── Tabs ── */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            background: #F1F5F9;
            padding: 5px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid #E2E8F0;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px !important;
            background: transparent !important;
            color: #64748B !important;
            padding: 0.45rem 1.15rem !important;
            font-weight: 500;
            font-size: 0.88rem;
            transition: all 0.15s;
            border: none !important;
        }
        .stTabs [aria-selected="true"] {
            background: #10A37F !important;
            color: #ffffff !important;
            box-shadow: 0 2px 6px rgba(16,163,127,0.35) !important;
        }

        /* ── Buttons ── */
        .stButton > button {
            border-radius: 8px;
            font-weight: 500;
            font-size: 0.88rem;
            transition: all 0.18s;
        }
        .stButton > button[kind="primary"] {
            background: #10A37F;
            border: 1px solid #10A37F;
            color: #fff;
            box-shadow: 0 2px 4px rgba(16,163,127,0.25);
        }
        .stButton > button[kind="primary"]:hover {
            background: #0D8A6A;
            border-color: #0D8A6A;
            box-shadow: 0 4px 10px rgba(16,163,127,0.35);
        }
        .stButton > button[kind="secondary"] {
            background: #fff;
            border: 1px solid #E2E8F0;
            color: #374151;
        }
        .stButton > button[kind="secondary"]:hover {
            background: #F8FAFC;
            border-color: #CBD5E1;
        }

        /* ── Answer Box ── */
        .answer-box {
            border: 1px solid #E2E8F0;
            border-radius: 14px;
            padding: 24px;
            background: #FFFFFF;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .section-title {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: #94A3B8;
            margin: 20px 0 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #F1F5F9;
        }
        .section-title:first-child { margin-top: 0; }
        .answer-summary {
            color: #0F172A;
            font-size: 0.95rem;
            line-height: 1.7;
        }
        .answer-evidence {
            background: #F8FAFC;
            border-left: 3px solid #10A37F;
            border-radius: 0 8px 8px 0;
            padding: 8px 14px;
            margin-top: 6px;
            font-size: 0.82rem;
            color: #475569;
            line-height: 1.5;
        }

        /* ── Metrics ── */
        [data-testid="stMetric"] {
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 14px 12px;
        }
        [data-testid="stMetricValue"] {
            color: #10A37F !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricLabel"] {
            color: #64748B !important;
            font-size: 0.8rem !important;
        }

        /* ── Container borders ── */
        [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px !important;
            border: 1px solid #E2E8F0 !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
        }

        /* ── Sidebar Branding ── */
        .sidebar-brand {
            text-align: center;
            padding: 20px 8px 20px;
            border-bottom: 1px solid #E2E8F0;
            margin-bottom: 16px;
        }
        .sidebar-brand-icon { font-size: 2.8rem; line-height: 1; }
        .sidebar-brand-name {
            font-size: 1.05rem;
            font-weight: 700;
            color: #0F172A;
            margin-top: 8px;
        }
        .sidebar-brand-sub { font-size: 0.73rem; color: #94A3B8; }

        .sidebar-stat-grid { display: flex; gap: 8px; }
        .sidebar-stat-card {
            flex: 1;
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 12px 6px;
            text-align: center;
        }
        .sidebar-stat-value {
            font-size: 1.3rem;
            font-weight: 700;
            color: #10A37F;
        }
        .sidebar-stat-label {
            font-size: 0.68rem;
            color: #94A3B8;
            margin-top: 2px;
        }
        .sidebar-section {
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #94A3B8;
            margin: 18px 0 8px;
        }

        /* ── Step labels ── */
        .step-label {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #10A37F;
            background: #ECFDF5;
            border-radius: 6px;
            padding: 4px 12px 4px 6px;
            margin-bottom: 10px;
        }
        .step-num {
            background: #10A37F;
            color: white;
            border-radius: 50%;
            width: 20px; height: 20px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.72rem;
            font-weight: 700;
            flex-shrink: 0;
        }

        /* ── Empty state ── */
        .empty-state {
            text-align: center;
            padding: 48px 16px;
        }
        .empty-state-icon { font-size: 2.8rem; }
        .empty-state-text {
            color: #64748B;
            font-size: 0.92rem;
            margin-top: 12px;
            font-weight: 500;
        }
        .empty-state-sub {
            color: #94A3B8;
            font-size: 0.8rem;
            margin-top: 4px;
        }

        /* ── Upload area ── */
        [data-testid="stFileUploader"] section {
            border: 2px dashed #CBD5E1 !important;
            border-radius: 10px !important;
            background: #FAFBFC !important;
            transition: all 0.2s;
        }
        [data-testid="stFileUploader"] section:hover {
            border-color: #10A37F !important;
            background: #ECFDF5 !important;
        }

        /* ── Inputs ── */
        [data-baseweb="input"] { border-radius: 8px !important; }
        [data-baseweb="select"] > div { border-radius: 8px !important; }

        /* ── Alerts ── */
        [data-testid="stAlert"] { border-radius: 10px !important; }

        /* ── Divider ── */
        hr { border-color: #E2E8F0 !important; margin: 16px 0 !important; }

        /* ── Subheaders ── */
        h3 {
            font-size: 1.05rem !important;
            font-weight: 600 !important;
            color: #0F172A !important;
            letter-spacing: -0.01em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def default_summary_cards() -> dict[str, str]:
    return {
        "예산":    "문서에서 추출된 명시 예산이 없습니다. 질의로 확인하세요.",
        "기간":    "사업기간 정보가 아직 확정되지 않았습니다.",
        "참가요건": "참가자격은 업종/실적/인력 요건 중심으로 확인이 필요합니다.",
        "제출서류": "제안서, 가격입찰서, 실적증빙 여부를 확인하세요.",
        "평가항목": "기술평가/가격평가 기준 확인이 필요합니다.",
        "마감일":  "입찰 마감일 정보가 아직 추출되지 않았습니다.",
    }


def infer_summary_cards(chatbot: Any) -> dict[str, str]:
    cards = default_summary_cards()
    try:
        ranking = chatbot.vector_store.get_ranking("amount", 1)
        if ranking:
            top = ranking[0]
            amount = getattr(top, "amount", "") or "정보 없음"
            project = getattr(top, "project_name", "") or "프로젝트명 미확인"
            cards["예산"] = f"상위 문서 기준 예산: {amount}"
            cards["기간"] = f"주요 대상 사업: {project}"
    except Exception:
        pass
    return cards


def render_summary_cards(cards: dict[str, str]) -> None:
    keys = ["예산", "기간", "참가요건", "제출서류", "평가항목", "마감일"]
    for i in range(0, len(keys), 3):
        cols = st.columns(3)
        for idx, key in enumerate(keys[i : i + 3]):
            meta = CARD_META.get(key, {"icon": "📌", "color": "#10A37F"})
            color = meta["color"]
            icon = meta["icon"]
            value = cards.get(key, "-")
            with cols[idx]:
                st.markdown(
                    f"""<div class="summary-card">
                        <div class="summary-card-accent" style="background:{color}"></div>
                        <div class="summary-key">
                            <span>{icon}</span>{key}
                        </div>
                        <div class="summary-value">{value}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )


def _sentence_split(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if p.strip()]


def parse_answer_payload(result: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]]]:
    answer = str(result.get("answer", "") or "").strip()
    sentences = _sentence_split(answer)
    summary = " ".join(sentences[:2]) if sentences else "답변이 생성되지 않았습니다."

    bullets: list[str] = []
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            bullets.append(stripped.lstrip("-* "))
        elif stripped.startswith("|"):
            continue
        elif len(bullets) < 5 and len(stripped) > 8 and not stripped.startswith("###"):
            bullets.append(stripped)
        if len(bullets) >= 5:
            break

    evidence = result.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    return summary, bullets[:5], evidence[:5]


def render_answer_sections(result: dict[str, Any]) -> None:
    summary, bullets, evidence = parse_answer_payload(result)
    st.markdown('<div class="answer-box">', unsafe_allow_html=True)

    st.markdown("<div class='section-title'>📝 요약</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='answer-summary'>{summary}</div>", unsafe_allow_html=True)

    st.markdown("<div class='section-title'>💡 핵심 포인트</div>", unsafe_allow_html=True)
    if bullets:
        for item in bullets:
            st.markdown(f"- {item}")
    else:
        st.caption("핵심 포인트를 자동 추출하지 못했습니다.")

    st.markdown("<div class='section-title'>📎 근거 (페이지/섹션)</div>", unsafe_allow_html=True)
    if evidence:
        for idx, ev in enumerate(evidence, start=1):
            source = ev.get("source", "unknown")
            page = ev.get("page")
            text = str(ev.get("text", "")).strip()

            page_val = str(page).strip() if page not in (None, "", "-", "None") else ""
            page_badge = (
                f" <span style='font-size:0.7rem;background:#ECFDF5;border:1px solid #10A37F;"
                f"border-radius:4px;padding:1px 6px;color:#10A37F;font-weight:600;"
                f"vertical-align:middle;'>p.{page_val}</span>"
                if page_val else ""
            )
            st.markdown(
                f"<div class='answer-evidence'>"
                f"<strong>#{idx}</strong> &nbsp; {source}{page_badge}"
                f"</div>",
                unsafe_allow_html=True,
            )
            if text:
                preview = text[:200] + ("…" if len(text) > 200 else "")
                st.caption(preview)
    else:
        st.caption("근거 정보가 제공되지 않았습니다.")
    st.markdown("</div>", unsafe_allow_html=True)


def build_dummy_pdf_bytes(summary: str) -> bytes:
    content = (
        "RFP Summary (Dummy Export)\n"
        "==========================\n"
        f"{summary or 'No summary'}\n"
    )
    return content.encode("utf-8")


def build_checklist_csv_bytes() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["항목", "체크", "비고"])
    writer.writerow(["참가자격 확인", "", "업종/실적/인력 요건"])
    writer.writerow(["제출서류 준비", "", "제안서/가격입찰서/증빙"])
    writer.writerow(["평가기준 분석", "", "기술/가격 배점"])
    writer.writerow(["마감일 검토", "", "접수 채널 및 시간"])
    return output.getvalue().encode("utf-8-sig")



def _parse_date_safe(date_str: str) -> date | None:
    """날짜 문자열에서 date 객체를 파싱합니다."""
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(date_str or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _split_filename(filename: str) -> tuple[str, str]:
    """'기관명_사업명.hwp' 형태 파일명에서 기관과 사업명을 분리합니다."""
    stem = Path(filename).stem
    stem = re.sub(r"\.(docx|pdf|hwpx?)$", "", stem, flags=re.IGNORECASE)
    parts = stem.split("_", 1)
    org = parts[0].strip()
    project = parts[1].strip() if len(parts) > 1 else stem
    return org, project


def real_bids_dataframe(chatbot: Any) -> pd.DataFrame:
    """벡터스토어 org_registry 또는 파일명 파싱으로 실제 입찰 목록을 생성합니다.

    우선순위:
    1. chatbot.vector_store.org_registry (기관명·예산·사업명 추출 완료)
    2. data/files/ 파일명 파싱 (예산·마감일 없음)
    3. 빈 DataFrame 반환 (데이터 없음 안내)
    """
    rows: list[dict] = []

    try:
        registry = chatbot.vector_store.org_registry
        if registry:
            for idx, (org_name, info) in enumerate(sorted(registry.items()), start=1):
                budget: int | None = int(info.amount_numeric) if info.amount_numeric > 0 else None
                deadline: date | None = None
                if info.open_date:
                    parsed = _parse_date_safe(info.open_date)
                    if parsed:
                        deadline = parsed + timedelta(days=30)
                rows.append({
                    "공고번호": f"RFP-{idx:03d}",
                    "사업명": info.project_name or org_name,
                    "기관": org_name,
                    "예산": budget,
                    "마감일": deadline,
                })
    except Exception:
        pass

    if not rows:
        try:
            from src.utils.config import get_data_dir
            files_dir = get_data_dir() / "files"
            if files_dir.exists():
                all_files: list[Path] = []
                for pat in ("*.hwp", "*.hwpx", "*.pdf"):
                    all_files.extend(sorted(files_dir.glob(pat)))
                for idx, f in enumerate(all_files, start=1):
                    org, project = _split_filename(f.name)
                    rows.append({
                        "공고번호": f"RFP-{idx:03d}",
                        "사업명": project,
                        "기관": org,
                        "예산": None,
                        "마감일": None,
                    })
        except Exception:
            pass

    if not rows:
        return pd.DataFrame(columns=["공고번호", "사업명", "기관", "예산", "마감일"])

    return pd.DataFrame(rows)
