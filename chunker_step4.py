#!/usr/bin/env python3
"""
Chunker Step 4: Semantic Chunking with metadata

- Semantic Chunking: 문장 단위로 분할하되, 앞뒤 청크와 overlap 유지
- 메타데이터: {문서명, 상위 계층명, 페이지 번호}를 각 청크에 포함
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

class MetaExtractor:
    """메타데이터 추출"""
    
    @staticmethod
    def extract_from_yaml(text: str) -> Dict:
        """YAML 프론트매터에서 메타데이터 추출"""
        meta = {}
        yaml_match = re.match(r'---\n(.*?)\n---', text, re.DOTALL)
        
        if yaml_match:
            yaml_content = yaml_match.group(1)
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    meta[key.strip()] = value.strip().strip('"\'')
        
        return meta
    
    @staticmethod
    def find_section_headers(text: str) -> List[Tuple[int, str, int]]:
        """섹션 헤더 찾기: (위치, 헤더명, 레벨)"""
        headers = []
        lines = text.split('\n')
        char_pos = 0
        
        for line_num, line in enumerate(lines):
            if line.startswith('# ') or line.startswith('## '):
                level = 1 if line.startswith('# ') else 2
                header_name = line.lstrip('# ').strip()
                headers.append((char_pos, header_name, level))
            
            char_pos += len(line) + 1  # +1 for \n
        
        return headers
    
    @staticmethod
    def get_section_for_position(pos: int, headers: List[Tuple[int, str, int]]) -> Dict:
        """주어진 위치의 섹션 메타데이터 반환"""
        relevant_headers = [(h, l) for h, n, l in headers if h <= pos]
        
        meta = {}
        if relevant_headers:
            h1_headers = [(h, n) for h, n, l in headers if h <= pos and l == 1]
            h2_headers = [(h, n) for h, n, l in headers if h <= pos and l == 2]
            
            if h1_headers:
                meta['section_level1'] = h1_headers[-1][1]
            if h2_headers:
                meta['section_level2'] = h2_headers[-1][1]
        
        return meta


class SemanticChunker:
    """시맨틱 청킹"""
    
    @staticmethod
    def split_into_sentences(text: str) -> List[str]:
        """텍스트를 문장 단위로 분할"""
        # 마크다운 형식 제거
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*|__', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        
        # 문장 분할 (한글, 영어 기준)
        text = re.sub(r'([.!?。！？\n])\s+', r'\1\n', text)
        sentences = text.split('\n')
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]
        
        return sentences
    
    @staticmethod
    def create_chunks(
        text: str,
        chunk_size: int = 1000,  # characters
        overlap_size: int = 100,
        min_chunk_size: int = 200
    ) -> List[Dict]:
        """시맨틱 청킹 수행"""
        
        # 메타데이터 추출
        doc_meta = MetaExtractor.extract_from_yaml(text)
        headers = MetaExtractor.find_section_headers(text)
        
        # 본문만 추출 (frontmatter 제거)
        body = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
        
        # 문장 단위로 분할
        sentences = SemanticChunker.split_into_sentences(body)
        
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_start_pos = 0
        
        for sent_idx, sentence in enumerate(sentences):
            sent_size = len(sentence)
            
            # 청크 크기 초과시 저장
            if current_size + sent_size > chunk_size and current_chunk:
                chunk_text = ' '.join(current_chunk)
                
                if len(chunk_text) >= min_chunk_size:
                    # 섹션 메타데이터 추출
                    section_meta = MetaExtractor.get_section_for_position(
                        chunk_start_pos, headers
                    )
                    
                    chunk_obj = {
                        'chunk_id': len(chunks),
                        'content': chunk_text,
                        'metadata': {
                            'document_title': doc_meta.get('document_title', 'Unknown'),
                            'document_type': doc_meta.get('document_type', 'Unknown'),
                            'section_level1': section_meta.get('section_level1', 'N/A'),
                            'section_level2': section_meta.get('section_level2', 'N/A'),
                            'chunk_size': len(chunk_text),
                            'created_at': datetime.now().isoformat()
                        }
                    }
                    chunks.append(chunk_obj)
                
                # 겹침 설정 (overlap)
                if len(current_chunk) > 1:
                    # 마지막 문장들을 다음 청크 시작으로
                    current_chunk = current_chunk[-2:]
                    current_size = sum(len(s) for s in current_chunk) + 2
                else:
                    current_chunk = []
                    current_size = 0
                
                chunk_start_pos += sent_size
            
            current_chunk.append(sentence)
            current_size += sent_size + 1
        
        # 마지막 청크 처리
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            if len(chunk_text) >= min_chunk_size:
                section_meta = MetaExtractor.get_section_for_position(
                    chunk_start_pos, headers
                )
                
                chunk_obj = {
                    'chunk_id': len(chunks),
                    'content': chunk_text,
                    'metadata': {
                        'document_title': doc_meta.get('document_title', 'Unknown'),
                        'document_type': doc_meta.get('document_type', 'Unknown'),
                        'section_level1': section_meta.get('section_level1', 'N/A'),
                        'section_level2': section_meta.get('section_level2', 'N/A'),
                        'chunk_size': len(chunk_text),
                        'created_at': datetime.now().isoformat()
                    }
                }
                chunks.append(chunk_obj)
        
        return chunks


def main():
    """Chunker 실행"""
    
    print("\n" + "="*60)
    print("✂️  CHUNKER STAGE (Step 4)")
    print("="*60 + "\n")
    
    input_dir = Path('output')
    output_dir = Path('output/chunks')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    final_files = list(input_dir.glob('step3_final_*.md'))
    
    if not final_files:
        print("⚠️ 처리할 최종 마크다운 파일이 없습니다.")
        return

    all_chunks = []
    total_chunks_count = 0

    for input_file in final_files:
        print(f"📄 처리 중인 문서: {input_file.name}")
        
        # 입력 파일 읽기
        text = input_file.read_text(encoding='utf-8')
        print(f"   - 입력 크기: {len(text):,} characters")
        
        # 청킹 수행
        print("   - Semantic Chunking 진행 중...")
        chunks = SemanticChunker.create_chunks(
            text,
            chunk_size=1500,
            overlap_size=100,
            min_chunk_size=300
        )
        
        print(f"   - 생성된 청크: {len(chunks)}개")
        
        # 각 청크에 고유 ID 부여 및 저장
        for chunk in chunks:
            chunk['chunk_id'] += total_chunks_count
            chunk_file = output_dir / f"chunk_{chunk['chunk_id']:05d}.json"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, ensure_ascii=False, indent=2)
            all_chunks.append(chunk)

        total_chunks_count += len(chunks)

    # 전체 통계
    total_chars = sum(len(c['content']) for c in all_chunks)
    avg_chunk_size = total_chars / total_chunks_count if total_chunks_count > 0 else 0
    
    print("\n" + "="*60)
    print("📊 전체 청킹 통계")
    print("="*60)
    print(f"총 처리된 파일 수: {len(final_files)}")
    print(f"생성된 총 청크 수: {total_chunks_count}")
    print(f"평균 청크 크기: {avg_chunk_size:.0f} characters")
    print(f"총 콘텐츠 크기: {total_chars:,} characters")
    print(f"출력 디렉토리: {output_dir}")
    
    # 메타데이터 샘플 출력
    if all_chunks:
        print("\n📌 첫 번째 청크 메타데이터 샘플:")
        print(json.dumps(all_chunks[0]['metadata'], ensure_ascii=False, indent=2))
    
    print("\n✨ Chunker 단계 완료!")
    
    return all_chunks


if __name__ == '__main__':
    main()
