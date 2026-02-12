#!/usr/bin/env python3
"""
텍스트 정규화 모듈

텍스트 데이터를 정리하고 정규화합니다.
"""

from __future__ import annotations

import re
from typing import Any


class TextCleaner:
    """텍스트 정규화 및 전처리를 수행하는 클래스."""

    # 한국어 불용어
    STOP_WORDS = {
        '이다', '하다', '되다', '있다', '없다', '같다', '아니다',
        '이', '그', '저', '것', '등', '및', '또는', '혹은'
    }

    def __init__(
        self,
        normalize_newlines: bool = True,
        remove_extra_spaces: bool = True,
        remove_special_chars: bool = False,
        min_line_length: int = 0
    ):
        """텍스트 클리너를 초기화합니다.

        Args:
            normalize_newlines: 연속 줄바꿈 정리 여부
            remove_extra_spaces: 연속 공백 제거 여부
            remove_special_chars: 특수 문자 제거 여부
            min_line_length: 최소 줄 길이
        """
        self.normalize_newlines = normalize_newlines
        self.remove_extra_spaces = remove_extra_spaces
        self.remove_special_chars = remove_special_chars
        self.min_line_length = min_line_length

    def clean(self, text: str) -> str:
        """텍스트를 정리합니다.

        Args:
            text: 정리할 텍스트

        Returns:
            정리된 텍스트
        """
        if not text:
            return ""

        cleaned = text

        if self.normalize_newlines:
            cleaned = self._normalize_newlines(cleaned)

        if self.remove_extra_spaces:
            cleaned = self._remove_extra_spaces(cleaned)

        if self.remove_special_chars:
            cleaned = self._remove_special_chars(cleaned)

        cleaned = self._filter_lines(cleaned)

        return cleaned.strip()

    def _normalize_newlines(self, text: str) -> str:
        """연속된 줄바꿈을 정리합니다.

        Args:
            text: 정리할 텍스트

        Returns:
            정리된 텍스트
        """
        return re.sub(r'\n{3,}', '\n\n', text)

    def _remove_extra_spaces(self, text: str) -> str:
        """연속된 공백을 제거합니다.

        Args:
            text: 정리할 텍스트

        Returns:
            정리된 텍스트
        """
        # 공백 2개 이상을 1개로 변환
        text = re.sub(r' +', ' ', text)
        # 탭을 공백으로 변환
        text = text.replace('\t', ' ')
        return text

    def _remove_special_chars(self, text: str) -> str:
        """특수 문자를 제거합니다.

        Args:
            text: 정리할 텍스트

        Returns:
            정리된 텍스트
        """
        # HTML 태그 제거
        text = re.sub(r'<[^>]+>', '', text)
        # 특수 문자 제거 (한글, 영어, 숫자, 공백, 문장부호만 유지)
        text = re.sub(r'[^\w\s\.\,\!\?\-\/\:\(\)]', '', text)
        return text

    def _filter_lines(self, text: str) -> str:
        """최소 길이 미만의 줄을 제거합니다.

        Args:
            text: 정리할 텍스트

        Returns:
            정리된 텍스트
        """
        if self.min_line_length <= 0:
            return text

        lines = text.split('\n')
        filtered = [
            line for line in lines
            if len(line.strip()) >= self.min_line_length or not line.strip()
        ]
        return '\n'.join(filtered)

    def extract_sentences(self, text: str) -> list[str]:
        """텍스트에서 문장을 추출합니다.

        Args:
            text: 텍스트

        Returns:
            문장 리스트
        """
        # 문장 종결 패턴
        sentence_endings = re.compile(r'(?<=[.!?])\s+(?=[가-힣A-Z])')
        sentences = sentence_endings.split(text)
        return [s.strip() for s in sentences if s.strip()]

    def extract_keywords(self, text: str, min_length: int = 2) -> list[str]:
        """텍스트에서 키워드를 추출합니다.

        Args:
            text: 텍스트
            min_length: 최소 키워드 길이

        Returns:
            키워드 리스트
        """
        # 명사 추출 (간단한 정규식 기반)
        words = re.findall(r'[가-힣]{2,}', text)
        # 불용어 제거
        keywords = [w for w in words if w not in self.STOP_WORDS and len(w) >= min_length]
        # 빈도수 기반 정렬
        from collections import Counter
        counter = Counter(keywords)
        return [word for word, _ in counter.most_common(20)]
