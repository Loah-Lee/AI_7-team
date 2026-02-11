# 입찰메이트 v17 사용법

## 빠른 시작

```bash
# 1. 가상 환경 생성
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 또
.\venv\Scripts\activate  # Windows

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 입력

# 4. 실행
python -m app.main
```

## Streamlit 웹 버전

```bash
streamlit run app/main.py
```

## CLI 버전

```bash
python -m src.graph.workflow
```

## DB 재구축

```bash
python scripts/rebuild_db.py
```

## 테스트

```bash
python tests/test_conversation.py
```
