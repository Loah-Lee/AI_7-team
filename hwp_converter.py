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
        """HWP 파일을 PDF로 변환"""
        
        hwp_path = Path(hwp_path)
        if not hwp_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {hwp_path}")
        
        if output_dir is None:
            output_dir = str(hwp_path.parent)
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        print(f"HWP → PDF 변환 중: {hwp_path.name}")
        
        # LibreOffice 호출
        cmd = [
            self.libreoffice_path,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
            str(hwp_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise RuntimeError(f"변환 실패: {result.stderr}")
            
            # 변환된 PDF 파일 찾기
            pdf_name = hwp_path.stem + '.pdf'
            pdf_path = Path(output_dir) / pdf_name
            
            if not pdf_path.exists():
                raise RuntimeError("PDF 파일이 생성되지 않았습니다")
            
            print(f"✅ 변환 완료: {pdf_path}")
            print(f"   파일 크기: {pdf_path.stat().st_size / (1024*1024):.2f} MB")
            
            return {
                'success': True,
                'input_file': str(hwp_path),
                'output_file': str(pdf_path),
                'size': pdf_path.stat().st_size
            }
        
        except subprocess.TimeoutExpired:
            raise RuntimeError("변환 타임아웃 (5분 초과)")
        except Exception as e:
            raise RuntimeError(f"변환 중 오류: {e}")


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
