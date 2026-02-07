#!/usr/bin/env python3
"""
Auditor & Reader Step 2-3: Text integrity & layout validation

Auditor: 오탈자 검증, 표 데이터 무결성 확인
Reader: 시각적 레이아웃 분석, 메타데이터 추출 (표지 제목)
"""

import re
from pathlib import Path
from typing import Tuple, List
import fitz  # PyMuPDF
from datetime import datetime

class Auditor:
    """텍스트 무결성 검증"""
    
    @staticmethod
    def fix_header_levels(text: str) -> str:
        """헤더 레벨을 2레벨 이내로 정규화"""
        lines = text.split('\n')
        normalized = []
        
        for line in lines:
            # 헤더 3레벨 이상을 2레벨로 제한
            if line.startswith('###'):
                line = '##' + line.lstrip('#')[2:]
            normalized.append(line)
        
        return '\n'.join(normalized)
    
    @staticmethod
    def fix_spacing_artifacts(text: str) -> str:
        """파싱 과정에서 발생한 띄어쓰기 오류 수정"""
        # 예: "제 안 요 청 서" -> "제안요청서"
        text = re.sub(r'([가-힣])\s+(?=[가-힣])', r'\1', text)
        
        # 불필요한 중복 공백 제거
        text = re.sub(r' {2,}', ' ', text)
        
        return text
    
    @staticmethod
    def validate_tables(original_pdf: str, parsed_md: str) -> str:
        """표 데이터 검증"""
        doc = fitz.open(original_pdf)
        table_count = 0
        
        for page in doc:
            tables = page.find_tables()
            if tables.tables:
                table_count += len(tables.tables)
        
        doc.close()
        
        # 표 언급 카운트
        table_mentions = parsed_md.count('|')  # 마크다운 테이블
        
        print(f"   📊 Table check: Detected {table_count} tables in PDF")
        print(f"      Markdown tables: {table_mentions // 4 if table_mentions > 0 else 0} (approx)")
        
        return parsed_md
    
    @staticmethod
    def audit(input_file: str, pdf_file: str, output_file: str) -> str:
        """감수 작업 수행"""
        print("🔍 Auditor: 텍스트 무결성 검증 중...")
        
        # 파싱된 텍스트 读取
        text = Path(input_file).read_text(encoding='utf-8')
        
        # 1. 헤더 레벨 정규화
        text = Auditor.fix_header_levels(text)
        print("   ✓ Header levels normalized to max 2 levels")
        
        # 2. 띄어쓰기 아티팩트 수정
        text = Auditor.fix_spacing_artifacts(text)
        print("   ✓ Spacing artifacts fixed")
        
        # 3. 표 데이터 검증
        text = Auditor.validate_tables(pdf_file, text)
        
        # 4. 결과 저장
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(text, encoding='utf-8')
        
        return text


class Reader:
    """시각적 레이아웃 분석 및 메타데이터 추출"""
    
    @staticmethod
    def extract_cover_title(pdf_path: str) -> str:
        """표지에서 공식 문서명 추출 (가장 큰 폰트 기준)"""
        doc = fitz.open(pdf_path)
        page = doc[0]  # 첫 페이지만 분석

        # 폰트 크기 기준으로 가장 중요한 텍스트 블록 찾기
        blocks = page.get_text("dict")["blocks"]
        largest_text = ""
        largest_size = 0.0

        for block in blocks:
            if block["type"] == 0:  # 텍스트 블록
                for line in block["lines"]:
                    for span in line["spans"]:
                        text_content = span["text"].strip()
                        font_size = span["size"]
                        
                        # 가장 큰 폰트 사이즈를 가진 텍스트를 제목으로 간주
                        # 너무 짧거나 긴 텍스트는 노이즈로 간주하여 제외
                        if font_size > largest_size and 10 < len(text_content) < 150:
                            largest_size = font_size
                            largest_text = text_content
                        # 폰트 크기가 비슷한 경우, 더 긴 텍스트를 선택 (부제목 등 방지)
                        elif abs(font_size - largest_size) < 1 and len(text_content) > len(largest_text):
                             largest_text = text_content

        doc.close()
        
        if not largest_text:
             # Fallback: 만약 위 로직으로 제목을 못찾으면 기존 로직(가장 긴 블록) 사용
             blocks = page.get_text("blocks")
             for block in blocks:
                 text_content = block[4].strip()
                 if 10 < len(text_content) < 150 and len(text_content) > len(largest_text):
                     largest_text = text_content
        
        # 후처리
        title = largest_text.strip()
        title = re.sub(r'\s+', ' ', title)  # 중복 공백 제거
        title = re.sub(r'^\d+\.\s*', '', title) # 숫자 리스트 제거

        return title if title else "Unknown Document"
    
    @staticmethod
    def validate_headers_visually(pdf_path: str) -> List[Tuple[str, float]]:
        """시각적 분석을 통해 헤더 후보 추출: (텍스트, 폰트 크기)"""
        doc = fitz.open(pdf_path)
        header_candidates = []
        
        for page_num in range(min(len(doc), 10)):  # Analyze first 10 pages for headers
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            fontsize = span["size"]
                            text = span["text"].strip()
                            
                            # 폰트 크기와 텍스트 길이를 기준으로 헤더 후보 선정
                            if fontsize > 13 and len(text) > 3 and len(text) < 100:
                                # 중복 추가 방지
                                if not any(text in t for t, s in header_candidates):
                                     header_candidates.append((text, fontsize))
        
        doc.close()
        # 폰트 크기 순으로 정렬하여 중요도 높은 헤더가 앞에 오도록 함
        header_candidates.sort(key=lambda x: x[1], reverse=True)
        return header_candidates

    @staticmethod
    def apply_headers_to_text(text: str, headers: List[Tuple[str, float]]) -> str:
        """텍스트에 마크다운 헤더 태그 적용"""
        lines = text.split('\n')
        new_lines = []
        header_map = {h[0]: h[1] for h in headers}
        
        for line in lines:
            clean_line = line.strip()
            if clean_line in header_map:
                fontsize = header_map[clean_line]
                if fontsize > 15: # Level 1 Header threshold
                    new_lines.append(f"# {clean_line}")
                elif fontsize > 13: # Level 2 Header threshold
                    new_lines.append(f"## {clean_line}")
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        return '\n'.join(new_lines)

    @staticmethod
    def read_and_extract_metadata(pdf_path: str, parsed_md: str, output_file: str) -> str:
        """Reader 작업: 시각적 검증, 헤더 적용 및 메타데이터 추가"""
        print("👁️  Reader: 시각적 레이아웃 분석 중...")
        
        # 표지 제목 추출
        title = Reader.extract_cover_title(pdf_path)
        print(f"   ✓ Document title extracted: '{title}'")
        
        # 헤더 후보 시각적 검증
        header_candidates = Reader.validate_headers_visually(pdf_path)
        print(f"   ✓ Visual header validation: {len(header_candidates)} candidates found")
        
        # 텍스트에 헤더 적용
        text_with_headers = Reader.apply_headers_to_text(parsed_md, header_candidates)
        print(f"   ✓ Markdown headers applied based on visual analysis.")

        # 메타데이터 추가
        metadata = f"---\ndocument_title: \"{title}\"\ndocument_type: \"Request for Proposal\"\nsubmitted_date: \"{datetime.now().strftime('%Y-%m-%d')}\"\n---\n\n"
        final_text = metadata + text_with_headers
        
        # 결과 저장
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(final_text, encoding='utf-8')
        
        return final_text


def main():
    """Auditor & Reader 실행"""
    
    print("\n" + "="*60)
    print("📋 AUDITOR & READER STAGE (Step 2-3)")
    print("="*60 + "\n")
    
    # 처리할 파일 목록 가져오기
    parsed_dir = Path('output')
    pdf_dir = Path('output/temp_pdf')
    
    # 'step1_parsed_*.md' 형식의 파일들을 찾습니다.
    parsed_files = list(parsed_dir.glob('step1_parsed_*.md'))
    
    if not parsed_files:
        print("⚠️ 처리할 파싱된 마크다운 파일이 없습니다.")
        return

    for parsed_md_path in parsed_files:
        # 원본 PDF 파일 경로를 생성합니다. (e.g., step1_parsed_sample1.md -> sample1.pdf)
        file_stem = parsed_md_path.stem.replace('step1_parsed_', '')
        pdf_path = pdf_dir / f"{file_stem}.pdf"
        
        if not pdf_path.exists():
            print(f"⚠️ 원본 PDF 파일을 찾을 수 없습니다: {pdf_path}. 이 파일은 건너뜁니다.")
            continue

        print(f"🔄 processing: {parsed_md_path.name}")

        audited_md = parsed_dir / f"step2_audited_{file_stem}.md"
        final_md = parsed_dir / f"step3_final_{file_stem}.md"

        # Auditor 실행
        audited_text = Auditor.audit(str(parsed_md_path), str(pdf_path), str(audited_md))
        print(f"  ✅ Auditor 완료 → {audited_md.name}")
        
        # Reader 실행
        final_text = Reader.read_and_extract_metadata(str(pdf_path), audited_text, str(final_md))
        print(f"  ✅ Reader 완료 → {final_md.name}\n")
    
    print("\n✨ Auditor & Reader 단계 완료!")


if __name__ == '__main__':
    main()
