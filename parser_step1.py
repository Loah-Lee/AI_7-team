#!/usr/bin/env python3
print("--- SCRIPT START ---")
"""
Parser Step 1: PDF to Markdown conversion using pymupdf
- 표(table) 인식률 개선을 위해 PyMuPDF(fitz) 직접 사용
- 헤더는 최대 2레벨(#, ##)로 제한
"""

import fitz  # PyMuPDF
from pathlib import Path
import pandas as pd

def parse_pdf_to_markdown(pdf_path: str, output_path: str) -> None:
    """PDF를 마크다운으로 변환 (테이블 인식 개선)"""
    
    print(f"📄 Parsing: {pdf_path}")
    
    try:
        doc = fitz.open(pdf_path)
        md_text = ""
        
        for page_num, page in enumerate(doc):
            # 1. 테이블 추출 및 변환
            tables = page.find_tables()
            if tables.tables:
                print(f"   - Found {len(tables.tables)} tables on page {page_num + 1}")
            
            # 2. 일반 텍스트 추출 (테이블 영역 제외)
            text_blocks = page.get_text("blocks")
            
            # 테이블 영역 bbox 계산
            table_bboxes = [table.bbox for table in tables]

            # 텍스트 블록이 테이블 안에 있는지 확인
            non_table_text = []
            for block in text_blocks:
                is_in_table = False
                for bbox in table_bboxes:
                    # 블록이 테이블 경계 상자 내에 있는지 확인
                    if fitz.Rect(block[:4]).intersects(bbox):
                        is_in_table = True
                        break
                if not is_in_table:
                    non_table_text.append(block[4].strip())

            # 페이지 텍스트와 테이블을 순서대로 조합
            md_text += f"\n\n[page: {page_num + 1}]\n\n"
            md_text += "\n".join(non_table_text)
            
            for i, table in enumerate(tables.tables):
                df = table.to_pandas()
                # 테이블 마크다운 변환
                if not df.empty:
                    md_text += f"\n\n**Table {page_num + 1}-{i+1}**\n"
                    md_text += df.to_markdown(index=False)
                    md_text += "\n"

        # 헤더 레벨 정규화 (3레벨 이상을 2레벨로 제한)
        lines = md_text.split('\n')
        normalized_lines = []
        
        for line in lines:
            if line.startswith('###'):
                # ### 이상을 ##로 변환
                line = '##' + line[3:]
            normalized_lines.append(line)
        
        normalized_md = '\n'.join(normalized_lines)
        
        # 결과물 저장
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(normalized_md, encoding='utf-8')
        
        # 통계 출력
        page_count = len(md_text.split('[page:')) - 1
        word_count = len(normalized_md.split())
        
        print(f"✅ Parsing complete!")
        print(f"   Output: {output_path}")
        print(f"   Size: {len(normalized_md):,} characters")
        print(f"   Words: {word_count:,}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == '__main__':
    # 모든 PDF 파일에 대해 파싱 수행
    pdf_dir = Path('output/temp_pdf')
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    
    for pdf_file in pdf_dir.glob('*.pdf'):
        output_md_path = output_dir / f'step1_parsed_{pdf_file.stem}.md'
        parse_pdf_to_markdown(str(pdf_file), str(output_md_path))
        print(f"\n✨ Parser 작업 완료: {output_md_path}")
