"""CSV 전처리 모듈

data_list.csv를 로드하여 정제된 DataFrame으로 반환한다.
- 텍스트 열 제외
- 날짜 컬럼 datetime 변환
- 공고 차수 nullable int 변환
- 사업금액_억 편의 컬럼 추가
- pickle 캐싱 (CSV 수정 시 자동 재파싱)
"""

from pathlib import Path

import pandas as pd


# ============================================================
# 경로 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "data_list.csv"
CACHE_PATH = Path(__file__).resolve().parent / "csv_cache.pkl"

USE_COLUMNS = [
    "공고 번호",
    "공고 차수",
    "사업명",
    "사업 금액",
    "발주 기관",
    "공개 일자",
    "입찰 참여 시작일",
    "입찰 참여 마감일",
    "사업 요약",
    "파일형식",
    "파일명",
]

DATE_COLUMNS = ["공개 일자", "입찰 참여 시작일", "입찰 참여 마감일"]


# ============================================================
# 내부 함수
# ============================================================

def _preprocess(df: pd.DataFrame) -> pd.DataFrame:
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "공고 차수" in df.columns:
        df["공고 차수"] = df["공고 차수"].astype("Int64")

    if "사업 금액" in df.columns:
        df.loc[df["사업 금액"] < 1e7, "사업 금액"] = float("nan")
        df["사업금액_억"] = df["사업 금액"] / 1e8

    return df


# ============================================================
# 공개 API
# ============================================================

def load_csv(use_cache: bool = True) -> pd.DataFrame:
    """CSV를 로드하여 정제된 DataFrame을 반환한다.

    pickle 캐시가 존재하고 CSV보다 최신이면 캐시에서 로드한다.
    캐시가 없거나 CSV가 갱신되었으면 재파싱 후 캐시를 갱신한다.

    Args:
        use_cache: pickle 캐시 사용 여부 (기본값 True)

    Returns:
        정제된 DataFrame (100행 × 12열)

    Raises:
        FileNotFoundError: CSV 파일이 존재하지 않을 때
    """
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {CSV_PATH}")

    if use_cache and CACHE_PATH.exists():
        if CACHE_PATH.stat().st_mtime >= CSV_PATH.stat().st_mtime:
            cached = pd.read_pickle(CACHE_PATH)
            assert isinstance(cached, pd.DataFrame)
            return cached

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    df = df.drop(columns=["텍스트"])
    df = _preprocess(df)

    df.to_pickle(CACHE_PATH)

    return df


# ============================================================
# 단독 실행: 데이터 요약 출력
# ============================================================

if __name__ == "__main__":
    data = load_csv(use_cache=False)
    print(f"Shape: {data.shape}")
    print(f"\nColumns: {list(data.columns)}")
    print(f"\nDtypes:\n{data.dtypes}")
    print(f"\nNull counts:\n{data.isnull().sum()}")
    print(f"\n사업 금액 범위: {data['사업 금액'].min():,.0f}원 ~ {data['사업 금액'].max():,.0f}원")
    print(f"사업금액_억 범위: {data['사업금액_억'].min():.2f}억 ~ {data['사업금액_억'].max():.2f}억")
    print(f"\n발주 기관 ({data['발주 기관'].nunique()}개): {data['발주 기관'].unique()[:5].tolist()} ...")
    print(f"\nSample (3행):")
    print(data[["사업명", "사업 금액", "사업금액_억", "발주 기관"]].head(3).to_string())
