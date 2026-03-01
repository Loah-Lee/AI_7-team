from __future__ import annotations

import re
import unicodedata
from typing import Callable

from src.utils.text_ops import looks_incomplete_clause as default_looks_incomplete_clause


def normalize_answer_for_compare(answer: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(answer or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def enforce_honorific_tone(answer: str) -> str:
    """최종 답변의 문장 어미를 존댓말 중심으로 정규화합니다."""
    text = unicodedata.normalize("NFKC", str(answer or "")).strip()
    if not text:
        return ""
    converted_lines: list[str] = []
    for raw in text.splitlines():
        line = unicodedata.normalize("NFKC", raw).strip()
        if not line:
            continue

        line = line.replace("할수있음", "할 수 있습니다")
        line = line.replace("할수 있음", "할 수 있습니다")
        line = line.replace("할 수 있음", "할 수 있습니다")
        line = line.replace("조정함", "조정합니다")
        line = line.replace("가능함", "가능합니다")
        line = line.replace("확인됨", "확인됩니다")
        if line.endswith("하며"):
            line = line[:-2] + "합니다"
        if line.endswith("이며"):
            line = line[:-2] + "입니다"
        if line.endswith("이고"):
            line = line[:-2] + "입니다"

        if line.startswith("- "):
            content = line[2:].strip()
            if content and re.search(r"[가-힣]$", content):
                if not re.search(r"(습니다|입니다|합니다|됩니다|있습니다|없습니다|하세요|해 주세요)[.!?]?$", content):
                    if content.endswith("함"):
                        content = content[:-1] + "합니다"
                    elif content.endswith("됨"):
                        content = content[:-1] + "됩니다"
                    elif content.endswith("가능"):
                        content += "합니다"
                    elif content.endswith("다") and not content.endswith("니다"):
                        content = content[:-1] + "입니다"
                    elif not content.endswith("."):
                        content += "입니다"
            if content and not content.endswith((".", "!", "?")):
                content += "."
            line = f"- {content}" if content else line
        else:
            if re.search(r"[가-힣]$", line):
                if not re.search(r"(습니다|입니다|합니다|됩니다|있습니다|없습니다|하세요|해 주세요)[.!?]?$", line):
                    if line.endswith("함"):
                        line = line[:-1] + "합니다"
                    elif line.endswith("됨"):
                        line = line[:-1] + "됩니다"
                    elif line.endswith("가능"):
                        line += "합니다"
                    elif line.endswith("다") and not line.endswith("니다"):
                        line = line[:-1] + "입니다"
                    else:
                        line += "입니다"
            if not line.endswith((".", "!", "?")):
                line += "."

        converted_lines.append(line)

    return "\n".join(converted_lines).strip()


def format_answer_for_readability(
    answer: str,
    style: str = "concise",
    looks_incomplete_clause_fn: Callable[[str], bool] | None = None,
) -> str:
    """답변을 읽기 쉬운 자연문장(최종 사용자용)으로 정규화합니다."""
    text = (answer or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    normalized_style = str(style).lower()
    answer_style = "guide" if normalized_style in {"guide", "descriptive"} else "concise"
    looks_incomplete = looks_incomplete_clause_fn or default_looks_incomplete_clause

    def _has_markdown_table(raw_text: str) -> bool:
        consecutive = 0
        for line in raw_text.split("\n"):
            if unicodedata.normalize("NFKC", line).strip().count("|") >= 2:
                consecutive += 1
                if consecutive >= 3:
                    return True
            else:
                consecutive = 0
        return False

    if _has_markdown_table(text):
        preserved: list[str] = []
        for raw_line in text.split("\n"):
            stripped = unicodedata.normalize("NFKC", raw_line).strip()
            if not stripped:
                continue
            if stripped.count("|") >= 2:
                preserved.append(stripped)
            else:
                cleaned = re.sub(
                    r"^(?:핵심\s*결론|결론|요약|핵심\s*답변|근거\s*요약|설명|핵심\s*포인트|가이드)\s*[:：]\s*",
                    "",
                    stripped,
                    flags=re.IGNORECASE,
                ).strip()
                if cleaned:
                    preserved.append(cleaned)
        return "\n".join(preserved).strip()

    def _normalize_line(value: str) -> str:
        return unicodedata.normalize("NFKC", value or "").strip()

    def _is_source_line(value: str) -> bool:
        raw = _normalize_line(value)
        lowered = raw.lower()
        if not raw:
            return False
        if lowered.startswith("출처:") or lowered.startswith("source:"):
            return True
        if re.search(r"\.(pdf|hwp|hwpx|docx?|xlsx?|csv)\b", lowered):
            return True
        if "data_list" in lowered and "csv" in lowered:
            return True
        if "|" in raw and re.search(r"(pdf|hwp|hwpx|csv)", lowered):
            return True
        if re.search(r"\bp\.\s*\d+\b", lowered) and ("|" in raw or ":" in raw):
            return True
        return False

    section_alias = {
        "핵심 답변": "핵심 답변",
        "근거 요약": "근거 요약",
        "근거": "근거 요약",
        "출처": "출처",
    }
    sections: dict[str, list[str]] = {"핵심 답변": [], "근거 요약": [], "출처": []}
    preamble: list[str] = []
    current_section: str | None = None

    for raw_line in text.split("\n"):
        line = _normalize_line(raw_line)
        if not line:
            continue

        bracket_heading = re.match(r"^\[(핵심 답변|근거 요약|근거|출처)\]\s*(.*)$", line)
        plain_heading = re.match(r"^(?:#{1,6}\s*)?(핵심 답변|근거 요약|근거|출처)\s*:?\s*(.*)$", line)
        heading_match = bracket_heading or plain_heading

        if heading_match:
            current_section = section_alias[heading_match.group(1)]
            trailing = heading_match.group(2).strip()
            if trailing:
                sections[current_section].append(trailing)
            continue

        if current_section:
            sections[current_section].append(line)
        else:
            preamble.append(line)

    if not any(sections.values()):
        content_lines = [_normalize_line(line) for line in text.split("\n") if _normalize_line(line)]
        source_lines = [line for line in content_lines if _is_source_line(line)]
        non_source_lines = [line for line in content_lines if not _is_source_line(line)]
        if non_source_lines:
            sections["핵심 답변"].append(non_source_lines[0])
            sections["근거 요약"].extend(non_source_lines[1:])
        sections["출처"].extend(source_lines)
    else:
        if preamble:
            if not sections["핵심 답변"]:
                sections["핵심 답변"].append(preamble[0])
                sections["근거 요약"].extend(preamble[1:])
            else:
                sections["근거 요약"].extend(preamble)

    if not sections["출처"]:
        inferred_sources: list[str] = []
        for line in sections["근거 요약"]:
            if _is_source_line(line):
                inferred_sources.append(line)
        if inferred_sources:
            sections["출처"].extend(inferred_sources)
            sections["근거 요약"] = [line for line in sections["근거 요약"] if not _is_source_line(line)]

    def _soften_tone(value: str) -> str:
        softened = _normalize_line(value)
        if not softened:
            return softened

        softened = re.sub(
            r"^(?:핵심\s*결론|결론|요약|핵심\s*답변|근거\s*요약|설명|핵심\s*포인트|가이드)\s*[:：]\s*",
            "",
            softened,
            flags=re.IGNORECASE,
        )
        softened = softened.replace("문서 기준으로 ", "")
        softened = softened.replace("문서 기준으로", "")
        softened = softened.replace("문서 기준 ", "")
        softened = softened.replace("문서 기준", "")
        softened = softened.replace("관련 직접 근거는", "관련 근거는")
        softened = softened.replace("직접 근거 문구는", "근거 문구는")
        softened = softened.replace("직접 근거(예산/금액 표기)", "근거(예산/금액 표기)")
        softened = softened.replace("단정 답변을 생략합니다.", "단정하지 않겠습니다.")

        softened = re.sub(r"\s{2,}", " ", softened).strip()
        softened = re.sub(r"^[,.:;]\s*", "", softened)
        return softened

    def _trim_item(value: str, max_len: int) -> str:
        if len(value) <= max_len:
            return value
        return value[: max_len - 1].rstrip() + "…"

    def _overlap_ratio(left: str, right: str) -> float:
        l_tokens = {
            tok
            for tok in re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", left.lower()))
            if tok
        }
        r_tokens = {
            tok
            for tok in re.findall(r"[0-9a-zA-Z가-힣]{2,}", unicodedata.normalize("NFKC", right.lower()))
            if tok
        }
        if not l_tokens or not r_tokens:
            return 0.0
        inter = len(l_tokens & r_tokens)
        base = max(1, min(len(l_tokens), len(r_tokens)))
        return inter / base

    def _norm_compact(value: str) -> str:
        return re.sub(r"[^0-9a-zA-Z가-힣]+", "", unicodedata.normalize("NFKC", value or "").lower())

    def _extract_numeric_markers(value: str) -> set[str]:
        normalized = unicodedata.normalize("NFKC", value or "")
        markers = {
            re.sub(r"\s+", "", m).lower()
            for m in re.findall(
                r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:%|원|만원|억원|명|건|개|회|시간|일|주|개월|년|MB|GB|KB)?",
                normalized,
                flags=re.IGNORECASE,
            )
            if m and re.search(r"\d", m)
        }
        return {m for m in markers if m}

    def _clean_item(value: str) -> str:
        item = _normalize_line(value)
        item = re.sub(r"^[-*•]\s*", "", item)
        item = re.sub(r"^(?:출처|source)\s*:\s*", "", item, flags=re.IGNORECASE)
        item = re.sub(
            r"^(?:핵심\s*결론|결론|요약|핵심\s*답변|근거\s*요약|설명|핵심\s*포인트|가이드)\s*[:：]\s*",
            "",
            item,
            flags=re.IGNORECASE,
        )
        return _soften_tone(item).strip()

    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            cleaned = _clean_item(value)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cleaned)
        return deduped

    core_limit = 3 if answer_style == "guide" else 2
    evidence_limit = 6 if answer_style == "guide" else 2
    core_items = [_trim_item(item, 320 if answer_style == "guide" else 280) for item in _dedupe(sections["핵심 답변"])][:core_limit]
    evidence_items = [_trim_item(item, 240 if answer_style == "guide" else 320) for item in _dedupe(sections["근거 요약"])][:evidence_limit]
    source_items_all = _dedupe(sections["출처"])
    source_items_filtered = [item for item in source_items_all if _is_source_line(item)]
    source_items = source_items_filtered if source_items_filtered else source_items_all
    source_items = [_trim_item(item, 240) for item in source_items][:2]

    if not core_items:
        core_items = ["요청하신 항목은 문서에서 확인되지 않습니다."]

    primary = core_items[0] if core_items else "요청하신 항목에 대해 문서에서 확인 가능한 내용을 정리했습니다."
    primary = _trim_item(primary, 320 if answer_style == "guide" else 280)

    rendered: list[str] = [primary]
    if answer_style == "guide":
        for extra in core_items[1:2]:
            rendered.append(extra)
        guide_points: list[str] = []
        for item in evidence_items:
            cleaned = item.strip()
            if not cleaned:
                continue
            if re.match(r"^(근거|출처|source)\s*:", cleaned, flags=re.IGNORECASE):
                continue
            guide_points.append(cleaned)
        if guide_points:
            rendered.extend([f"- {point}" for point in guide_points[:6]])
        return "\n".join(rendered).strip()

    if "확인되지 않습니다" not in primary and evidence_items:
        follow = ""
        needs_follow = looks_incomplete(primary)
        for candidate in evidence_items:
            cand = candidate.strip()
            if not cand:
                continue
            if re.match(r"^(근거|출처|source)\s*:", cand, flags=re.IGNORECASE):
                continue
            cand_lower = unicodedata.normalize("NFKC", cand.lower())
            has_context_marker = any(
                marker in cand_lower
                for marker in ["경우", "다만", "단 ", "단,", "예외", "초과", "협의", "허용", "가능"]
            )
            if not needs_follow and not has_context_marker:
                continue
            primary_norm = _norm_compact(primary)
            cand_norm = _norm_compact(cand)
            if (primary_norm and cand_norm and (primary_norm in cand_norm or cand_norm in primary_norm)) or _overlap_ratio(primary, cand) >= 0.45:
                continue
            primary_nums = _extract_numeric_markers(primary)
            cand_nums = _extract_numeric_markers(cand)
            if primary_nums and cand_nums and (primary_nums & cand_nums):
                continue
            if looks_incomplete(cand):
                continuation = ""
                for nxt in evidence_items:
                    nxt_line = nxt.strip()
                    if not nxt_line or nxt_line == cand:
                        continue
                    if looks_incomplete(nxt_line):
                        continue
                    if nxt_line.startswith(("경우", "이 경우", "으로", "로", "및", "또는", "단", "다만")):
                        continuation = nxt_line
                        break
                if continuation:
                    cand = f"{cand} {continuation}".strip()
                else:
                    continue
            cand = cand.rstrip(",;: ")
            if not cand:
                continue
            follow = cand
            break
        if follow:
            rendered.append(_trim_item(follow, 320))

    return "\n".join(rendered).strip()


def compact_answer_sections(
    answer: str,
    style: str = "concise",
    format_answer_for_readability_fn: Callable[[str, str], str] | None = None,
) -> str:
    normalized_style = str(style).lower()
    answer_style = "guide" if normalized_style in {"guide", "descriptive"} else "concise"
    formatter = format_answer_for_readability_fn or format_answer_for_readability
    text = formatter(answer, answer_style)
    lines = [
        unicodedata.normalize("NFKC", str(raw_line or "")).strip()
        for raw_line in text.splitlines()
    ]
    lines = [
        line
        for line in lines
        if line
        and not re.match(
            r"^(근거|출처|source|핵심\s*결론|결론|요약|핵심\s*답변|근거\s*요약|설명|핵심\s*포인트|가이드)\s*[:：]?$",
            line,
            flags=re.IGNORECASE,
        )
    ]
    if not lines:
        return ""

    if answer_style == "guide":
        trimmed = [re.sub(r"\s+", " ", line).strip() for line in lines if line.strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for line in trimmed:
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(line)
        if len(deduped) > 6:
            deduped = deduped[:6]
        return "\n".join(deduped).strip()

    def _trim_line(value: str, max_chars: int) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 1].rstrip() + "…"

    core_line = _trim_line(lines[0], 300)
    rendered = [core_line]
    if len(lines) > 1:
        rendered.append(_trim_line(lines[1], 360))
    return "\n".join(rendered).strip()
