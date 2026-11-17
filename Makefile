# 좋은상자 개발 명령 모음. `make help`로 목록 확인.
SHELL := /bin/bash

export UID := $(shell id -u)
export GID := $(shell id -g)

DC      := docker compose --env-file .env -f deploy/docker-compose.yml
# 운영 구성 로컬 점검용: .env.prod-local (make prod-env로 생성), 업로드는 var/media-prod
PROD_ENV := .env.prod-local
DC_PROD  := ENV_FILE=$(PROD_ENV) MEDIA_DIR=$(CURDIR)/var/media-prod \
            docker compose --env-file $(PROD_ENV) -f deploy/docker-compose.prod.yml

.DEFAULT_GOAL := help

.PHONY: help
help: ## 명령 목록
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── 준비 ────────────────────────────────────────────────
.PHONY: setup
setup: ## 최초 1회: .env 생성, 의존성 설치, 업로드 폴더 생성
	@test -f .env || (cp .env.example .env && echo ".env 생성됨 — 포트 충돌 시 WEB_PORT/DB_PORT를 수정하세요")
	mkdir -p var/media/public var/media/private
	uv sync

# ── 로컬 개발 ───────────────────────────────────────────
.PHONY: up down logs ps build
up: ## 개발 환경 기동 (web, db, nginx, css, mailpit)
	$(DC) up -d --build
	@source .env && echo "사이트: http://localhost:$${WEB_PORT:-8000}   메일함: http://localhost:$${MAILPIT_PORT:-8025}"

down: ## 개발 환경 중지
	$(DC) down

logs: ## 로그 보기 (예: make logs s=web)
	$(DC) logs -f $(s)

ps: ## 컨테이너 상태
	$(DC) ps

build: ## 이미지 재빌드
	$(DC) build

# ── DB ──────────────────────────────────────────────────
.PHONY: migrate create-admin import-molds revision seed-showroom psql db-reset
migrate: ## 마이그레이션 적용
	$(DC) exec web alembic upgrade head

create-admin: ## 관리자 계정 만들기·비밀번호 복구 (대화형)
	$(DC) exec web python -m scripts.create_user

import-molds: ## 목형 엑셀·CSV 가져오기 (예: make import-molds f=scripts/data/sample_molds.csv)
	@test -n "$(f)" || (echo '사용법: make import-molds f=파일.csv' && exit 1)
	$(DC) exec web python -m scripts.import_molds $(f)

revision: ## 마이그레이션 생성 (예: make revision m="add inquiries")
	@test -n "$(m)" || (echo '사용법: make revision m="설명"' && exit 1)
	$(DC) exec web alembic revision --autogenerate -m "$(m)"

seed-showroom: ## 현 사이트 쇼룸을 로컬 DB로 가져오기 (반복 실행 가능)
	$(DC) exec web python -m scripts.seed_showroom

psql: ## DB 콘솔
	$(DC) exec db sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'

db-reset: ## 로컬 DB 초기화 (데이터 삭제 후 마이그레이션)
	@read -p "로컬 DB 데이터를 모두 지웁니다. 계속할까요? [y/N] " a && [ "$$a" = y ]
	$(DC) down
	docker volume rm goodpackage_pgdata
	$(DC) up -d --build
	$(DC) exec web alembic upgrade head

# ── 품질 ────────────────────────────────────────────────
.PHONY: test lint fmt shell
test: ## 테스트 (db 컨테이너가 떠 있어야 함)
	uv run pytest

lint: ## 린트
	uv run ruff check .
	uv run ruff format --check .

fmt: ## 자동 정리
	uv run ruff check --fix .
	uv run ruff format .

shell: ## web 컨테이너 셸
	$(DC) exec web bash

# ── 운영 구성 로컬 점검 (기획서 6장) ─────────────────────
.PHONY: prod-env certs-local prod-up prod-down prod-logs
prod-env: ## 로컬 점검용 운영 .env 생성 (APP_ENV=prod, 무작위 비밀값)
	@if [ -f $(PROD_ENV) ]; then echo "$(PROD_ENV) 이미 있음"; else \
	  sed -e "s/^APP_ENV=.*/APP_ENV=prod/" \
	      -e "s#^SITE_URL=.*#SITE_URL=https://localhost#" \
	      -e "s/^SECRET_KEY=.*/SECRET_KEY=$$(openssl rand -hex 32)/" \
	      -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 16)/" \
	      -e "s#^DATA_KEYS=.*#DATA_KEYS=$$(openssl rand -base64 32 | tr '+/' '-_')#" \
	      .env.example > $(PROD_ENV) && echo "$(PROD_ENV) 생성됨"; fi

certs-local: ## 로컬 점검용 자체 서명 인증서 (운영은 Cloudflare Origin 인증서)
	@if [ -f deploy/certs/origin.pem ]; then echo "인증서 이미 있음"; else \
	  mkdir -p deploy/certs && \
	  openssl req -x509 -nodes -newkey rsa:2048 -days 30 -subj "/CN=localhost" \
	    -keyout deploy/certs/origin.key -out deploy/certs/origin.pem 2>/dev/null && \
	  echo "인증서 생성됨"; fi

prod-up: prod-env certs-local ## 운영용 Compose를 로컬에서 기동 (https://localhost)
	mkdir -p var/media-prod/public var/media-prod/private
	$(DC_PROD) up -d --build --wait
	$(DC_PROD) exec web alembic upgrade head

prod-down: ## 운영용 Compose 중지
	$(DC_PROD) down

prod-logs: ## 운영용 Compose 로그
	$(DC_PROD) logs -f $(s)
