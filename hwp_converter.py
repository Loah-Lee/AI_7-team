#!/usr/bin/env python3
"""
HWP to PDF Converter
LibreOffice를 사용하여 HWP/HWPX 파일을 PDF로 변환
"""

import subprocess
import sys
from pathlib import Path
import os

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
    
    def convert(self, hwp_path: str, output_dir: str = None) -> dict:
        """한글 및 기호가 포함된 파일명을 안전하게 PDF로 변환"""
        
        # 1. 절대 경로로 변환 (기호가 섞인 경로 문제를 최소화)
        hwp_path = Path(hwp_path).resolve()
        if not hwp_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {hwp_path}")
        
        if output_dir is None:
            output_dir = hwp_path.parent
        else:
            output_dir = Path(output_dir).resolve()
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. 인코딩 문제 방지를 위한 환경 변수 설정
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["LANG"] = "ko_KR.UTF-8"

        print(f"🔄 변환 시도 중: {hwp_path.name}")
        
        # 3. LibreOffice 호출 (리스트 형태로 전달하여 쉘 이스케이프 방지)
        cmd = [
            self.libreoffice_path,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(hwp_path)
        ]
        
        try:
            # shell=False (기본값)를 유지하여 특수기호가 쉘에 의해 해석되지 않도록 함
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
            
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice 오류: {result.stderr}")
            
            # 4. 변환된 PDF 파일 확인 로직 강화
            # LibreOffice는 파일명에 점이 여러개면 마지막 확장자만 바꿉니다.
            pdf_path = output_dir / (hwp_path.stem + ".pdf")
            
            if not pdf_path.exists():
                # 만약 stem 기반으로 못 찾는다면 대안으로 파일 목록에서 검색
                possible_files = list(output_dir.glob(f"{hwp_path.stem}.pdf"))
                if possible_files:
                    pdf_path = possible_files[0]
                else:
                    raise RuntimeError(f"PDF 파일 생성 확인 실패: {pdf_path.name}")
            
            print(f"✅ 변환 성공: {pdf_path.name}")
            
            return {
                'success': True,
                'input_file': str(hwp_path),
                'output_file': str(pdf_path),
                'size': pdf_path.stat().st_size
            }
        
        except subprocess.TimeoutExpired:
            raise RuntimeError("변환 시간 초과")
        except Exception as e:
            raise RuntimeError(f"변환 중 알 수 없는 오류: {e}")


def main():
    """메인 함수"""
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
            print("\n🎉 변환 작업 완료!")
            print(f"입력: {result['input_file']}")
            print(f"출력: {result['output_file']}")
    
    except Exception as e:
        print(f"❌ 오류: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
