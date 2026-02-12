#!/usr/bin/env python3
"""
ChromaDB 재구축 스크립트
"""

import os
import sys
import shutil
from pathlib import Path

# 스크립트 위치 기반 경로 설정
script_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(script_dir))

from dotenv import load_dotenv
load_dotenv()

from src.utils.config import get_default_db_path, get_data_dir


def main():
    """DB를 재구축합니다."""
    db_path = get_default_db_path()
    data_dir = get_data_dir()
    
    print("=" * 60)
    print("ChromaDB 재구축")
    print("=" * 60)
    print(f"DB 경로: {db_path}")
    print(f"데이터 경로: {data_dir}")
    
    # 기존 DB 삭제 확인
    if Path(db_path).exists():
        response = input(f"\n'{db_path}'를 삭제하고 재구축하시겠습니까? (y/N): ")
        if response.lower() == 'y':
            shutil.rmtree(db_path)
            print("✅ 기존 DB 삭제 완료")
        else:
            print("❌ 취소되었습니다.")
            return
    
    # 챗봇 초기화 (새 DB 생성)
    from src.graph.workflow import RAGChatbotV17
    chatbot = RAGChatbotV17(data_dir=str(data_dir))
    
    print("\n" + "=" * 60)
    print("재구축 완료!")
    print("=" * 60)
    print(f"등록 기관: {len(chatbot.vector_store.org_registry)}개")
    print(f"청크 수: {chatbot.vector_store.count}")


if __name__ == "__main__":
    main()
