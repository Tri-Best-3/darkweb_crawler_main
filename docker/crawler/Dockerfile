FROM python:3.10-slim

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (빌드 툴 등)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        python3-dev \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 의존성 설치
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# 소스 코드 복사 (Docker Context는 프로젝트 루트로 설정 예정)
COPY . /app/

# Scrapy 설정
ENV SCRAPY_SETTINGS_MODULE=tricrawl.settings

# 실행 권한 설정 (Logs 디렉토리 생성)
RUN mkdir -p /app/tricrawl/logs

# 기본 커맨드 (재정의 가능)
CMD ["scrapy", "list"]
