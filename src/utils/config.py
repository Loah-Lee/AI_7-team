"""
프로젝트 전역 설정 모듈

프로젝트 루트, 데이터베이스 경로, 출력 경로 등을 중앙화하여 관리합니다.
"""

from pathlib import Path

# 프로젝트 루트: src/utils/config.py 기준으로 2단계 상위
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 주요 경로
CHROMA_PATH = str(PROJECT_ROOT / 'chroma_db')
OUTPUT_PATH = PROJECT_ROOT / 'output'
DATA_PATH = PROJECT_ROOT / 'data'
CHUNK_DIR = str(PROJECT_ROOT / 'output' / 'chunks')

# 임베딩 모델
EMBEDDING_MODEL = 'jhgan/ko-sroberta-multitask'

__all__ = [
    'PROJECT_ROOT',
    'CHROMA_PATH',
    'OUTPUT_PATH',
    'DATA_PATH',
    'CHUNK_DIR',
    'EMBEDDING_MODEL',
]
