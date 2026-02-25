#!/usr/bin/env python3
"""
메타데이터 필터 모듈

검색 결과에 대한 메타데이터 필터링을 제공합니다.
"""

from __future__ import annotations

import re
from typing import Any


class MetadataFilter:
    """메타데이터 필터 클래스."""

    def __init__(
        self,
        source_filter: list[str] | None = None,
        org_filter: list[str] | None = None,
        type_filter: list[str] | None = None
    ):
        """메타데이터 필터를 초기화합니다.

        Args:
            source_filter: 소스 필터 리스트
            org_filter: 기관 필터 리스트
            type_filter: 타입 필터 리스트
        """
        self.source_filter = set(source_filter) if source_filter else None
        self.org_filter = set(org_filter) if org_filter else None
        self.type_filter = set(type_filter) if type_filter else None

    def filter_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """검색 결과를 필터링합니다.

        Args:
            results: 검색 결과 리스트

        Returns:
            필터링된 결과 리스트
        """
        filtered = []

        for result in results:
            metadata = result.get('metadata', {})

            if self._matches_filters(metadata):
                filtered.append(result)

        return filtered

    def _matches_filters(self, metadata: dict[str, Any]) -> bool:
        """메타데이터가 필터와 일치하는지 확인합니다.

        Args:
            metadata: 메타데이터

        Returns:
            일치 여부
        """
        if self.source_filter and metadata.get('source') not in self.source_filter:
            return False

        if self.org_filter and metadata.get('org') not in self.org_filter:
            return False

        if self.type_filter and metadata.get('type') not in self.type_filter:
            return False

        return True

    def add_source_filter(self, source: str) -> None:
        """소스 필터를 추가합니다.

        Args:
            source: 추가할 소스
        """
        if self.source_filter is None:
            self.source_filter = set()
        self.source_filter.add(source)

    def add_org_filter(self, org: str) -> None:
        """기관 필터를 추가합니다.

        Args:
            org: 추가할 기관
        """
        if self.org_filter is None:
            self.org_filter = set()
        self.org_filter.add(org)

    def add_type_filter(self, type_filter: str) -> None:
        """타입 필터를 추가합니다.

        Args:
            type_filter: 추가할 타입
        """
        if self.type_filter is None:
            self.type_filter = set()
        self.type_filter.add(type_filter)

    def clear_filters(self) -> None:
        """모든 필터를 제거합니다."""
        self.source_filter = None
        self.org_filter = None
        self.type_filter = None


class AmountFilter:
    """금액 기반 필터 클래스."""

    @staticmethod
    def parse_amount_range(query: str) -> tuple[int | None, int | None]:
        """질문에서 금액 범위를 파싱합니다.

        Args:
            query: 사용자 질문

        Returns:
            (최소 금액, 최대 금액) 튜플
        """
        amount_min = None
        amount_max = None

        # 범위 패턴
        range_patterns = [
            r'(\d+\.?\d*)\s*(억|만)\s*(?:에서|부터|~)\s*(\d+\.?\d*)\s*(억|만)\s*(?:사이|까지)?',
            r'(\d+\.?\d*)\s*~\s*(\d+\.?\d*)\s*(억|만)',
        ]

        for pattern in range_patterns:
            match = re.search(pattern, query)
            if match:
                groups = match.groups()
                # 파싱 로직
                if len(groups) == 4:
                    value1, unit1, value2, unit2 = float(groups[0]), groups[1], float(groups[2]), groups[3]
                elif len(groups) == 3:
                    value1, value2, unit = float(groups[0]), float(groups[1]), groups[2]
                    unit1 = unit2 = unit
                else:
                    continue

                # 단위 변환
                from src.utils.config import AMOUNT_UNITS
                if unit1 == '억':
                    amount_min = int(value1 * AMOUNT_UNITS['억'])
                else:
                    amount_min = int(value1 * AMOUNT_UNITS['만'])

                if unit2 == '억':
                    amount_max = int(value2 * AMOUNT_UNITS['억'])
                else:
                    amount_max = int(value2 * AMOUNT_UNITS['만'])

                # 최소/최대 스왑
                if amount_min > amount_max:
                    amount_min, amount_max = amount_max, amount_min
                break

        # 단일 조건 패턴
        if amount_min is None:
            amount_patterns = [
                r'(\d+\.?\d*)\s*(억|만)\s*(이상|초과)',
                r'(\d+\.?\d*)\s*(억|만)\s*(이하|미만)',
            ]

            for pattern in amount_patterns:
                match = re.search(pattern, query)
                if match:
                    amount_value = float(match.group(1))
                    unit = match.group(2)
                    condition = match.group(3)

                    from src.utils.config import AMOUNT_UNITS
                    if unit == '억':
                        amount_value *= AMOUNT_UNITS['억']
                    else:
                        amount_value *= AMOUNT_UNITS['만']

                    if condition in ['이상', '초과']:
                        amount_min = int(amount_value)
                    else:
                        amount_max = int(amount_value)
                    break

        return amount_min, amount_max

    @staticmethod
    def filter_by_amount(
        orgs: list,
        amount_min: int | None = None,
        amount_max: int | None = None
    ) -> list:
        """기관 리스트를 금액으로 필터링합니다.

        Args:
            orgs: 기관 정보 리스트
            amount_min: 최소 금액
            amount_max: 최대 금액

        Returns:
            필터링된 기관 리스트
        """
        filtered = []

        for org in orgs:
            amount_numeric = getattr(org, 'amount_numeric', 0)

            if amount_min is not None and amount_numeric < amount_min:
                continue
            if amount_max is not None and amount_numeric > amount_max:
                continue

            filtered.append(org)

        return filtered
