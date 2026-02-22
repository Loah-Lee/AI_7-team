"""CSV 검색 노드

라우팅 LLM이 생성한 구조화된 쿼리(csv_query)를 받아
DataFrame 연산을 수행하고, context_appender 호환 형식으로 반환한다.

csv_query 스키마:
    {
        "filters": [{"column": str, "op": str, "value": Any}],
        "sort": {"column": str, "order": "asc" | "desc"},
        "limit": int,
        "keyword": str
    }

search_result 반환 형식:
    [(사업명: str, metadata: dict), ...]
"""

from typing import Any, Dict, List, Tuple

import pandas as pd

from .csv_preprocessor import DATE_COLUMNS, load_csv


_df: pd.DataFrame = load_csv()

KEYWORD_SEARCH_COLUMNS = ["사업명", "발주 기관", "사업 요약"]

OPS = {
    ">=": lambda s, v: s >= v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    "<": lambda s, v: s < v,
    "==": lambda s, v: s == v,
}


# ============================================================
# 내부 함수
# ============================================================

def _cast_value(column: str, value: Any) -> Any:
    if column in DATE_COLUMNS:
        if isinstance(value, list):
            return [pd.to_datetime(v) for v in value]
        return pd.to_datetime(value)
    return value


def _apply_filters(df: pd.DataFrame, filters: List[Dict[str, Any]]) -> pd.DataFrame:
    for f in filters:
        col = f["column"]
        op = f["op"]
        val = _cast_value(col, f["value"])

        if op == "between":
            df = pd.DataFrame(df[df[col].between(val[0], val[1])])
        elif op in OPS:
            df = pd.DataFrame(df[OPS[op](df[col], val)])

    return df


def _apply_keyword(df: pd.DataFrame, keyword: str) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for col in KEYWORD_SEARCH_COLUMNS:
        if col in df.columns:
            mask = mask | df[col].str.contains(keyword, case=False, na=False)
    return pd.DataFrame(df[mask])


def _serialize(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "item"):
        return value.item()
    return value


def _format_results(df: pd.DataFrame) -> List[Tuple[str, Dict[str, Any]]]:
    results: List[Tuple[str, Dict[str, Any]]] = []
    for idx, row in df.iterrows():
        text = str(row["사업명"])
        metadata = {"uid": f"csv_{idx}", "source": "csv"}
        for col in df.columns:
            metadata[col] = _serialize(row[col])
        results.append((text, metadata))
    return results


# ============================================================
# 공개 API
# ============================================================

def csv_search(state: Dict[str, Any]) -> Dict[str, Any]:
    csv_query = state.get("csv_query")
    if not csv_query:
        return {"search_result": []}

    result_df = _df.copy()

    if "filters" in csv_query:
        result_df = _apply_filters(result_df, csv_query["filters"])

    if "keyword" in csv_query:
        result_df = _apply_keyword(result_df, csv_query["keyword"])

    if "sort" in csv_query:
        sort_conf = csv_query["sort"]
        result_df = result_df.sort_values(
            sort_conf["column"],
            ascending=sort_conf.get("order", "desc") == "asc",
            na_position="last",
        )

    limit = csv_query.get("limit")
    if limit:
        result_df = result_df.head(limit)

    return {"search_result": _format_results(result_df)}


# ============================================================
# 단독 테스트
# ============================================================

if __name__ == "__main__":
    test_queries = [
        {
            "name": "사업비 TOP 3",
            "csv_query": {
                "sort": {"column": "사업 금액", "order": "desc"},
                "limit": 3,
            },
        },
        {
            "name": "10억 이상 사업",
            "csv_query": {
                "filters": [{"column": "사업 금액", "op": ">=", "value": 1e9}],
            },
        },
        {
            "name": "5억~10억 사이",
            "csv_query": {
                "filters": [{"column": "사업 금액", "op": "between", "value": [5e8, 1e9]}],
            },
        },
        {
            "name": "고려대 발주 프로젝트",
            "csv_query": {
                "keyword": "고려대",
            },
        },
    ]

    for tc in test_queries:
        print(f"\n{'='*60}")
        print(f"TEST: {tc['name']}")
        print(f"{'='*60}")
        result = csv_search({"csv_query": tc["csv_query"]})
        for text, meta in result["search_result"]:
            budget = f"{meta['사업금액_억']:.2f}억" if meta.get("사업금액_억") else "N/A"
            print(f"  - {text} | {budget} | {meta.get('발주 기관')}")
        print(f"  총 {len(result['search_result'])}건")
