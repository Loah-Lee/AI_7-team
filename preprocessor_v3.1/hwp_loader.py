"""HWP 문서 로더 (크로스 플랫폼).

Windows: pyhwpx (COM 기반) 사용
macOS/Linux: olefile + zlib로 HWP 5.x OLE2 바이너리에서 직접 텍스트 추출
"""

from __future__ import annotations

import re
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

from langchain_core.documents import Document

# HWP 5.x 확장형 제어 문자: 4 x uint16 (8바이트) 차지
# 1-3: 확장 제어, 4-9: 탭·그림·표 등 인라인 개체, 11-12: 구역·단 정의, 14-23: 각종 제어
_EXTENDED_CTRL_CHARS = (
    frozenset(range(1, 10)) | frozenset(range(11, 13)) | frozenset(range(14, 24))
)
# 단일 제어 문자: 1 x uint16 (2바이트) — 0, 10(LF), 13(CR), 24-31
# 그 중 10, 13만 의미 있는 줄바꿈


def _extract_text_olefile(file_path: Path) -> str:
    """olefile을 사용하여 HWP 5.x 파일에서 텍스트를 추출한다."""
    import olefile

    f = olefile.OleFileIO(str(file_path))
    streams = f.listdir()

    text_parts: list[str] = []

    for entry in sorted(streams):
        if entry[0] != "BodyText":
            continue

        data = f.openstream("/".join(entry)).read()
        try:
            data = zlib.decompress(data, -15)
        except zlib.error:
            pass

        i = 0
        while i < len(data) - 4:
            header = struct.unpack_from("<I", data, i)[0]
            tag_id = header & 0x3FF
            size = (header >> 20) & 0xFFF

            if size == 0xFFF:
                if i + 8 <= len(data):
                    size = struct.unpack_from("<I", data, i + 4)[0]
                    i += 8
                else:
                    break
            else:
                i += 4

            # HWPTAG_PARA_TEXT = 67
            if tag_id == 67 and i + size <= len(data):
                chars: list[str] = []
                j = 0
                while j < size - 1:
                    ch = struct.unpack_from("<H", data, i + j)[0]
                    j += 2

                    if ch in _EXTENDED_CTRL_CHARS:
                        # 확장 제어 문자: 추가 3 x uint16 (6바이트) 스킵
                        j += 6
                    elif ch < 32:
                        # 단일 제어 문자
                        if ch in (10, 13):
                            chars.append("\n")
                    elif 0xD800 <= ch <= 0xDFFF:
                        pass  # surrogate 스킵
                    else:
                        chars.append(chr(ch))

                para = "".join(chars).strip()
                if para:
                    text_parts.append(para)

            i += size

    f.close()

    full_text = "\n".join(text_parts)

    # 연속 빈 줄 정리
    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()

    return full_text


def load_hwp(file_path: str | Path) -> list[Document]:
    """HWP 파일을 로드하여 LangChain Document 리스트로 반환한다.

    Args:
        file_path: HWP 파일 경로.

    Returns:
        Document 리스트.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    # Windows에서는 pyhwpx, 아닌 경우 olefile 기반 추출
    if sys.platform == "win32":
        try:
            from pyhwpx import HWPExtractor

            extractor = HWPExtractor(str(file_path))
            text = extractor.get_text()
        except ImportError:
            text = _extract_text_olefile(file_path)
    else:
        text = _extract_text_olefile(file_path)

    if not text.strip():
        return []

    return [
        Document(
            page_content=text,
            metadata={
                "source": unicodedata.normalize("NFC", file_path.name),
                "file_type": "hwp",
            },
        )
    ]
