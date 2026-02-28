#!/usr/bin/env python3
"""E2E: '사업비 높은 공고 TOP3' → answer/evidence 분리 검증."""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from src.graph.workflow import RAGChatbotV17
from src.utils.config import get_data_dir, get_default_db_path
from pathlib import Path

ROOT = Path(__file__).resolve().parent
candidates = [ROOT / "data_index" / "chroma_B", Path(get_default_db_path())]
db_path = str(next((p for p in candidates if p.exists()), candidates[0]))

chatbot = RAGChatbotV17(data_dir=str(get_data_dir()), db_path=db_path)
result = chatbot.answer("사업비 높은 공고 TOP3", top_k=30)

answer = str(result.get("answer", ""))
evidence = result.get("evidence", [])

print("=" * 70)
print("  📝 answer (최종 답변)")
print("=" * 70)
print(answer)

print(f"\n{'=' * 70}")
print(f"  📎 evidence ({len(evidence)}건)")
print("=" * 70)
for i, ev in enumerate(evidence):
    print(f"\n  [{i+1}] source: {ev.get('source', '?')}")
    print(f"      text:\n{ev.get('text', '')}")

print(f"\n{'=' * 70}")
print("  검증")
print("=" * 70)
print(f"  evidence 존재: {len(evidence) > 0}")
if evidence:
    ev_text = str(evidence[0].get("text", ""))
    print(f"  evidence에 표 데이터: {'|' in ev_text}")
    print(f"  evidence에 기관명: {any(kw in ev_text for kw in ['공사', '대학', '조달', '기관'])}")
print(f"  answer에 요약 형태: {len(answer) < 500}")
print(f"  answer 길이: {len(answer)}")
if evidence:
    print(f"  evidence 길이: {len(ev_text)}")
