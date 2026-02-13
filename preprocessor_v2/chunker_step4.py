#!/usr/bin/env python3
"""
Chunker Step 4: Section-Aware Chunking with kiwipiepy

Reads: output/step2_audited_{stem}.md (fallback: step1_parsed_{stem}.md)
Outputs: output/chunks/chunk_{NNNNN}.json

Features:
- Header boundary = MANDATORY split (# and ## trigger new chunks)
- Table integrity (consecutive | lines never split)
- Size limit with sentence-boundary splitting using kiwipiepy
- Overlap with last N sentences from previous chunk
- Page number tracking from <!-- page: N --> markers
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass

from kiwipiepy import Kiwi

# Parameters
CHUNK_SIZE = 1500  # characters
MIN_CHUNK_SIZE = 200  # characters
OVERLAP_SENTENCES = 2  # number of sentences to overlap

# Initialize Kiwi once at module level
kiwi = Kiwi()


@dataclass
class Section:
    """Represents a document section"""
    header_text: str
    header_level: int  # 1 or 2
    content_lines: List[str]
    page_start: int
    page_end: int


def split_sentences(text: str) -> List[str]:
    """
    Split text into sentences using kiwipiepy.
    
    Args:
        text: Input text (Korean or mixed Korean/English)
    
    Returns:
        List of sentence strings
    """
    if not text.strip():
        return []
    
    results = kiwi.split_into_sents(text)
    sentences = []
    for sent in results:
        sent_text = sent.text.strip()  # type: ignore
        if sent_text:
            sentences.append(sent_text)
    return sentences


def parse_frontmatter(text: str) -> Tuple[Dict, str]:
    """
    Extract YAML frontmatter and return (metadata, body).
    
    Args:
        text: Full markdown text
    
    Returns:
        (frontmatter_dict, body_text)
    """
    meta = {}
    body = text
    
    yaml_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if yaml_match:
        yaml_content = yaml_match.group(1)
        body = text[yaml_match.end():]
        
        for line in yaml_content.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip().strip('"\'')
    
    return meta, body


def is_table_line(line: str) -> bool:
    """Check if a line is part of a markdown table."""
    stripped = line.strip()
    return stripped.startswith('|') and stripped.endswith('|')


def extract_page_number(line: str) -> Optional[int]:
    """Extract page number from <!-- page: N --> marker."""
    match = re.match(r'<!--\s*page:\s*(\d+)\s*-->', line.strip())
    if match:
        return int(match.group(1))
    return None


def extract_header(line: str) -> Optional[Tuple[str, int]]:
    """
    Extract header text and level from a markdown header line.
    
    Returns:
        (header_text, level) or None if not a header
    """
    stripped = line.strip()
    if stripped.startswith('## '):
        return (stripped[3:].strip(), 2)
    elif stripped.startswith('# '):
        return (stripped[2:].strip(), 1)
    return None


def split_into_sections(body: str) -> List[Section]:
    """
    Split document body into sections at header boundaries.
    Track page numbers from <!-- page: N --> markers.
    
    Args:
        body: Document body (after frontmatter removal)
    
    Returns:
        List of Section objects
    """
    lines = body.split('\n')
    sections = []
    
    current_header = None
    current_level = 0
    current_content = []
    current_page_start = 1
    current_page = 1
    
    for line in lines:
        # Check for page marker
        page_num = extract_page_number(line)
        if page_num is not None:
            current_page = page_num
            if current_header is None:
                current_page_start = page_num
            continue  # Don't include page markers in content
        
        # Check for header
        header_info = extract_header(line)
        if header_info is not None:
            # Save previous section
            if current_header is not None and current_content:
                sections.append(Section(
                    header_text=current_header,
                    header_level=current_level,
                    content_lines=current_content,
                    page_start=current_page_start,
                    page_end=current_page
                ))
            
            # Start new section
            current_header, current_level = header_info
            current_content = [line]  # Include header in content
            current_page_start = current_page
        else:
            # Regular content line
            if current_header is None:
                # Content before any header - create a default section
                current_header = "Preamble"
                current_level = 0
            current_content.append(line)
    
    # Save last section
    if current_header is not None and current_content:
        sections.append(Section(
            header_text=current_header,
            header_level=current_level,
            content_lines=current_content,
            page_start=current_page_start,
            page_end=current_page
        ))
    
    return sections


def identify_blocks(lines: List[str]) -> List[Tuple[str, List[str]]]:
    """
    Identify table blocks and text blocks in content lines.
    
    Args:
        lines: Content lines
    
    Returns:
        List of (block_type, block_lines) tuples
        block_type is either 'table' or 'text'
    """
    blocks = []
    current_block_type = None
    current_block_lines = []
    
    for line in lines:
        is_table = is_table_line(line)
        block_type = 'table' if is_table else 'text'
        
        if block_type != current_block_type and current_block_lines:
            # Save previous block
            blocks.append((current_block_type, current_block_lines))
            current_block_lines = []
        
        current_block_type = block_type
        current_block_lines.append(line)
    
    # Save last block
    if current_block_lines:
        blocks.append((current_block_type, current_block_lines))
    
    return blocks


def create_chunks_from_section(
    section: Section,
    current_h1: str,
    current_h2: str,
    doc_meta: Dict
) -> List[Dict]:
    """
    Create chunks from a single section, respecting size limits and table integrity.
    
    Args:
        section: Section object to chunk
        current_h1: Current H1 context
        current_h2: Current H2 context
        doc_meta: Document metadata from frontmatter
    
    Returns:
        List of chunk dictionaries (without chunk_id assigned yet)
    """
    chunks = []
    
    # Identify blocks (tables vs text)
    blocks = identify_blocks(section.content_lines)
    
    # Calculate total content size
    total_content = '\n'.join(section.content_lines)
    
    # If entire section fits in one chunk, return it as-is
    if len(total_content) <= CHUNK_SIZE:
        chunk = {
            'content': total_content,
            'metadata': {
                'document_title': doc_meta.get('document_title', 'Unknown'),
                'source_file': doc_meta.get('source_file', 'Unknown'),
                'section_level1': current_h1,
                'section_level2': current_h2,
                'page_start': section.page_start,
                'page_end': section.page_end,
                'chunk_size': len(total_content),
                'created_at': datetime.now().isoformat()
            }
        }
        return [chunk]
    
    # Section is too large - need to split at sentence boundaries
    current_chunk_parts = []
    current_size = 0
    overlap_sentences_buffer = []
    
    for block_type, block_lines in blocks:
        block_text = '\n'.join(block_lines)
        block_size = len(block_text)
        
        if block_type == 'table':
            # Tables are atomic - never split
            if block_size > CHUNK_SIZE:
                # Single table larger than chunk size - it becomes its own chunk
                if current_chunk_parts:
                    # Save current chunk first
                    chunk_content = '\n'.join(current_chunk_parts)
                    if len(chunk_content) >= MIN_CHUNK_SIZE:
                        chunks.append({
                            'content': chunk_content,
                            'metadata': {
                                'document_title': doc_meta.get('document_title', 'Unknown'),
                                'source_file': doc_meta.get('source_file', 'Unknown'),
                                'section_level1': current_h1,
                                'section_level2': current_h2,
                                'page_start': section.page_start,
                                'page_end': section.page_end,
                                'chunk_size': len(chunk_content),
                                'created_at': datetime.now().isoformat()
                            }
                        })
                    current_chunk_parts = []
                    current_size = 0
                    overlap_sentences_buffer = []
                
                # Table becomes its own chunk
                chunks.append({
                    'content': block_text,
                    'metadata': {
                        'document_title': doc_meta.get('document_title', 'Unknown'),
                        'source_file': doc_meta.get('source_file', 'Unknown'),
                        'section_level1': current_h1,
                        'section_level2': current_h2,
                        'page_start': section.page_start,
                        'page_end': section.page_end,
                        'chunk_size': block_size,
                        'created_at': datetime.now().isoformat()
                    }
                })
            elif current_size + block_size > CHUNK_SIZE:
                # Table doesn't fit in current chunk - save current and start new
                if current_chunk_parts:
                    chunk_content = '\n'.join(current_chunk_parts)
                    if len(chunk_content) >= MIN_CHUNK_SIZE:
                        chunks.append({
                            'content': chunk_content,
                            'metadata': {
                                'document_title': doc_meta.get('document_title', 'Unknown'),
                                'source_file': doc_meta.get('source_file', 'Unknown'),
                                'section_level1': current_h1,
                                'section_level2': current_h2,
                                'page_start': section.page_start,
                                'page_end': section.page_end,
                                'chunk_size': len(chunk_content),
                                'created_at': datetime.now().isoformat()
                            }
                        })
                
                # Start new chunk with overlap + table
                current_chunk_parts = overlap_sentences_buffer.copy() if overlap_sentences_buffer else []
                current_chunk_parts.append(block_text)
                current_size = sum(len(p) for p in current_chunk_parts)
                overlap_sentences_buffer = []  # Tables don't contribute to sentence overlap
            else:
                # Table fits in current chunk
                current_chunk_parts.append(block_text)
                current_size += block_size
                overlap_sentences_buffer = []  # Reset after table
        
        else:  # block_type == 'text'
            # Split text into sentences
            sentences = split_sentences(block_text)
            
            for sentence in sentences:
                sent_size = len(sentence)
                
                if current_size + sent_size > CHUNK_SIZE and current_chunk_parts:
                    # Save current chunk
                    chunk_content = '\n'.join(current_chunk_parts)
                    if len(chunk_content) >= MIN_CHUNK_SIZE:
                        chunks.append({
                            'content': chunk_content,
                            'metadata': {
                                'document_title': doc_meta.get('document_title', 'Unknown'),
                                'source_file': doc_meta.get('source_file', 'Unknown'),
                                'section_level1': current_h1,
                                'section_level2': current_h2,
                                'page_start': section.page_start,
                                'page_end': section.page_end,
                                'chunk_size': len(chunk_content),
                                'created_at': datetime.now().isoformat()
                            }
                        })
                    
                    # Start new chunk with overlap
                    if len(overlap_sentences_buffer) >= OVERLAP_SENTENCES:
                        current_chunk_parts = overlap_sentences_buffer[-OVERLAP_SENTENCES:]
                    else:
                        current_chunk_parts = overlap_sentences_buffer.copy()
                    current_size = sum(len(s) for s in current_chunk_parts)
                    overlap_sentences_buffer = current_chunk_parts.copy()
                
                current_chunk_parts.append(sentence)
                current_size += sent_size
                
                # Update overlap buffer
                overlap_sentences_buffer.append(sentence)
                if len(overlap_sentences_buffer) > OVERLAP_SENTENCES * 2:
                    overlap_sentences_buffer = overlap_sentences_buffer[-OVERLAP_SENTENCES * 2:]
    
    # Save last chunk
    if current_chunk_parts:
        chunk_content = '\n'.join(current_chunk_parts)
        if len(chunk_content) >= MIN_CHUNK_SIZE:
            chunks.append({
                'content': chunk_content,
                'metadata': {
                    'document_title': doc_meta.get('document_title', 'Unknown'),
                    'source_file': doc_meta.get('source_file', 'Unknown'),
                    'section_level1': current_h1,
                    'section_level2': current_h2,
                    'page_start': section.page_start,
                    'page_end': section.page_end,
                    'chunk_size': len(chunk_content),
                    'created_at': datetime.now().isoformat()
                }
            })
    
    return chunks


def process_file(file_path: Path) -> List[Dict]:
    """
    Process a single markdown file into chunks.
    
    Args:
        file_path: Path to input markdown file
    
    Returns:
        List of chunk dictionaries (without chunk_id assigned)
    """
    print(f"📄 Processing: {file_path.name}")
    
    # Read file
    text = file_path.read_text(encoding='utf-8')
    print(f"   - Input size: {len(text):,} characters")
    
    # Parse frontmatter
    doc_meta, body = parse_frontmatter(text)
    
    # Split into sections
    sections = split_into_sections(body)
    print(f"   - Found {len(sections)} sections")
    
    # Track current H1/H2 context
    current_h1 = "N/A"
    current_h2 = "N/A"
    all_chunks = []
    
    for section in sections:
        # Update H1/H2 context
        if section.header_level == 1:
            current_h1 = section.header_text
            current_h2 = "N/A"
        elif section.header_level == 2:
            current_h2 = section.header_text
        elif section.header_level == 0:
            # Preamble - keep current context or set to N/A
            pass
        
        # Create chunks from section
        section_chunks = create_chunks_from_section(
            section, current_h1, current_h2, doc_meta
        )
        all_chunks.extend(section_chunks)
    
    all_chunks = _merge_small_chunks(all_chunks)
    print(f"   - Generated {len(all_chunks)} chunks")
    return all_chunks


def _merge_small_chunks(chunks: List[Dict]) -> List[Dict]:
    if len(chunks) <= 1:
        return chunks
    merged = [chunks[0]]
    for chunk in chunks[1:]:
        if chunk['metadata']['chunk_size'] < MIN_CHUNK_SIZE and merged:
            prev = merged[-1]
            prev['content'] = prev['content'] + '\n' + chunk['content']
            prev['metadata']['chunk_size'] = len(prev['content'])
            prev['metadata']['page_end'] = max(
                prev['metadata']['page_end'], chunk['metadata']['page_end']
            )
        else:
            merged.append(chunk)
    return merged


def process_all_files(file_paths: List[Path], output_dir: Path) -> List[Dict]:
    """
    Process all markdown files and save chunks with global chunk_id.
    
    Args:
        file_paths: List of input markdown file paths
        output_dir: Directory to save chunk JSON files
    
    Returns:
        List of all chunks with assigned chunk_id
    """
    all_chunks = []
    global_chunk_id = 0
    
    for file_path in file_paths:
        file_chunks = process_file(file_path)
        
        # Assign global chunk IDs and save
        for chunk in file_chunks:
            chunk['chunk_id'] = global_chunk_id
            
            # Save to file
            chunk_file = output_dir / f"chunk_{global_chunk_id:05d}.json"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, ensure_ascii=False, indent=2)
            
            all_chunks.append(chunk)
            global_chunk_id += 1
    
    return all_chunks


def print_statistics(chunks: List[Dict]):
    """Print chunking statistics."""
    if not chunks:
        print("⚠️  No chunks generated")
        return
    
    total_chunks = len(chunks)
    total_size = sum(c['metadata']['chunk_size'] for c in chunks)
    avg_size = total_size / total_chunks
    min_size = min(c['metadata']['chunk_size'] for c in chunks)
    max_size = max(c['metadata']['chunk_size'] for c in chunks)
    
    print("\n" + "="*60)
    print("📊 Chunking Statistics")
    print("="*60)
    print(f"Total chunks: {total_chunks}")
    print(f"Total content size: {total_size:,} characters")
    print(f"Average chunk size: {avg_size:.0f} characters")
    print(f"Min chunk size: {min_size} characters")
    print(f"Max chunk size: {max_size} characters")
    
    # Sample first chunk
    print("\n📌 First chunk sample:")
    print(f"Chunk ID: {chunks[0]['chunk_id']}")
    print(f"Content preview: {chunks[0]['content'][:150]}...")
    print(f"Metadata:")
    print(json.dumps(chunks[0]['metadata'], ensure_ascii=False, indent=2))
    
    print("\n✨ Chunker completed successfully!")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("✂️  CHUNKER STAGE (Step 4)")
    print("="*60 + "\n")
    
    input_dir = Path('output')
    output_dir = Path('output/chunks')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Look for step2_audited files first, fallback to step1_parsed
    final_files = sorted(input_dir.glob('step2_audited_*.md'))
    if not final_files:
        print("⚠️  No step2_audited_*.md files found, trying step1_parsed_*.md...")
        final_files = sorted(input_dir.glob('step1_parsed_*.md'))
    
    if not final_files:
        print("❌ No input files found (step2_audited_*.md or step1_parsed_*.md)")
        exit(1)
    
    print(f"Found {len(final_files)} files to process\n")
    
    # Process all files
    all_chunks = process_all_files(final_files, output_dir)
    
    # Print statistics
    print_statistics(all_chunks)
    print(f"\n📁 Output directory: {output_dir.absolute()}")
