#!/usr/bin/env python3
"""
HWP to PDF Converter
LibreOffice를 사용하여 HWP/HWPX 파일을 PDF로 변환

NFD 인코딩된 한글 파일명의 바이트 길이가 250B 이상이면
LibreOffice가 출력 파일 저장에 실패(0x507)하는 문제를 우회하기 위해
짧은 임시 이름으로 변환 후 NFC 정규화된 이름으로 리네임한다.
"""

import os
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path


class HWPConverter:
    """HWP 파일을 PDF로 변환"""

    def __init__(self):
        self.libreoffice_path = self._find_libreoffice()

    def _find_libreoffice(self) -> str:
        """LibreOffice 실행 파일 찾기"""
        possible_paths = [
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
            "/opt/libreoffice/program/soffice",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # PATH에서 찾기
        result = subprocess.run(['which', 'libreoffice'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()

        result = subprocess.run(['which', 'soffice'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()

        raise FileNotFoundError("LibreOffice를 찾을 수 없습니다")

    def convert(self, hwp_path: "str | Path", output_dir: "str | Path | None" = None) -> dict:
        """
        HWP/HWPX → PDF 변환.

        NFD 파일명 길이 문제를 우회하기 위해 항상 짧은 임시 심볼릭 링크로
        변환한 뒤, 결과 PDF를 NFC 정규화된 이름으로 리네임한다.

        Args:
            hwp_path: 원본 HWP 파일 경로
            output_dir: PDF 출력 디렉토리 (None이면 원본과 같은 디렉토리)

        Returns:
            dict: success, input_file, output_file, size
        """
        hwp_path = Path(hwp_path).resolve()
        if not hwp_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {hwp_path}")

        if output_dir is None:
            output_dir = hwp_path.parent
        else:
            output_dir = Path(output_dir).resolve()

        output_dir.mkdir(parents=True, exist_ok=True)

        nfc_stem = unicodedata.normalize('NFC', hwp_path.stem)
        final_pdf = output_dir / (nfc_stem + ".pdf")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["LANG"] = "ko_KR.UTF-8"

        print(f"🔄 변환 시도 중: {nfc_stem}.hwp")

        # NFD 바이트 길이 250B+ → LibreOffice impl_store 실패(0x507) 우회
        temp_id = uuid.uuid4().hex[:12]
        temp_link = output_dir / f"_cvt_{temp_id}.hwp"
        temp_pdf = output_dir / f"_cvt_{temp_id}.pdf"

        try:
            os.symlink(str(hwp_path), str(temp_link))

            cmd = [
                self.libreoffice_path,
                '--headless',
                '--convert-to', 'pdf',
                '--outdir', str(output_dir),
                str(temp_link),
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, env=env,
            )

            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice 오류: {result.stderr}")

            # 정확한 temp 파일만 확인 (mtime fallback 의도적으로 제거)
            if not temp_pdf.exists():
                stderr_msg = result.stderr.strip()
                raise RuntimeError(
                    f"PDF 파일 생성 실패: LibreOffice가 0을 반환했으나 "
                    f"'{temp_pdf.name}' 미생성. stderr: {stderr_msg}"
                )

            if final_pdf.exists():
                final_pdf.unlink()
            temp_pdf.rename(final_pdf)

            print(f"✅ 변환 성공: {final_pdf.name}")

            return {
                'success': True,
                'input_file': str(hwp_path),
                'output_file': str(final_pdf),
                'size': final_pdf.stat().st_size,
            }

        except subprocess.TimeoutExpired:
            raise RuntimeError("변환 시간 초과 (300s)")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"변환 중 오류: {e}")
        finally:
            if os.path.islink(str(temp_link)):
                os.unlink(str(temp_link))
            if temp_pdf.exists():
                temp_pdf.unlink()


def main():
    """CLI 진입점"""
    if len(sys.argv) < 2:
        print("사용법: python3 hwp_converter.py <input_hwp_path> [-o output_dir]")
        sys.exit(1)

    hwp_path = sys.argv[1]
    output_dir = None

    if '-o' in sys.argv:
        idx = sys.argv.index('-o')
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    try:
        converter = HWPConverter()
        result = converter.convert(hwp_path, output_dir)

        if result['success']:
            print(f"\n🎉 변환 작업 완료!")
            print(f"입력: {result['input_file']}")
            print(f"출력: {result['output_file']}")

    except Exception as e:
        print(f"❌ 오류: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
