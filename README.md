# 좋은상자 홈페이지 (goodpackage.co.kr)

WordPress → FastAPI + htmx 개편 프로젝트입니다. 설계는 [좋은상자_홈페이지_개편_기획서.md](좋은상자_홈페이지_개편_기획서.md)를 따릅니다.

## 구성

| 영역 | 사용 기술 |
| --- | --- |
| 웹 | FastAPI + Jinja2, Uvicorn (Python 3.15) |
| 화면 | htmx 2, Alpine.js 3 (`app/static/js`에 포함), Tailwind CSS 4 (standalone CLI, Node 불필요) |
| DB | PostgreSQL 16, SQLAlchemy 2, Alembic, `pg_trgm` |
| 실행 | Docker Compose: `web`, `db`, `nginx`, `css`(Tailwind 감시), `mailpit`(로컬 메일함) |

## 처음 시작하기

필요한 것: Docker, [uv](https://docs.astral.sh/uv/), make

```bash
make setup      # .env 생성, 의존성 설치
make up         # 개발 환경 기동
make migrate    # DB 마이그레이션 적용
make seed-showroom  # 현 사이트 쇼룸 37건을 로컬 DB·var/media로 가져오기 (반복 실행 가능)
make import-molds f=scripts/data/sample_molds.csv  # 목형 추천 확인용 샘플 목형 (SAMPLE-xxx)
make create-admin   # 관리자 계정 만들기 (비밀번호 분실 시 같은 이메일로 다시 실행)
```

관리자 화면은 `/admin/`입니다. 첫 관리자 계정만 `make create-admin`으로 만들고, 나머지 계정은 관리자 화면 '계정'에서 추가합니다(임시 비밀번호 발급).

- 영업: 견적 처리(답변 메일·내부 메모·상태·담당), 목형 관리(엑셀 일괄 등록·내려받기)
- 관리자: 그 밖에 쇼룸 편집, 계정 관리, 견적 삭제
- 로그인 실패가 15분 안에 계정별 5회 또는 IP별 20회면 잠시 막습니다. 마지막 요청 후 8시간이 지나면 다시 로그인합니다.

견적 접수 메일(고객 확인·담당자 알림)은 Mailpit에서 확인합니다. 담당자 수신 주소는 `.env`의 `STAFF_NOTIFY_EMAILS`입니다.

테스트는 개발 DB 이름 뒤에 `_test`를 붙인 DB(예: `goodpackage_test`)를 자동으로 만들어 쓰며, 테스트마다 롤백합니다.

- 사이트: http://localhost:8000 (Nginx 경유. 포트는 `.env`의 `WEB_PORT`)
- 메일함(Mailpit): http://localhost:8025
- API 문서: http://localhost:8000/docs (운영에서는 꺼짐)

다른 프로젝트와 포트가 겹치면 `.env`에서 `WEB_PORT`, `DB_PORT`와 `DATABASE_URL`의 포트를 바꿉니다.

`app/` 아래의 코드와 템플릿은 저장하면 바로 반영됩니다(uvicorn `--reload`, Tailwind `--watch`).

## 자주 쓰는 명령

```bash
make help                      # 전체 목록
make logs s=web                # 로그
make revision m="add inquiries"  # 모델 변경 후 마이그레이션 생성
make migrate
make test                      # pytest (db 컨테이너가 떠 있어야 함)
make lint / make fmt           # ruff
make psql                      # DB 콘솔
```

## 디렉터리

```
app/
  main.py, config.py, db.py, templating.py
  models/      SQLAlchemy 모델 (새 모듈은 models/__init__.py에서 import)
  routers/     pages, inquiry, board, portfolio, admin
  services/    mold_match, mailer, storage, auth
  templates/   base, pages, partials(htmx 조각), admin
  static/      css(input.css → app.css 빌드), js, img
migrations/    Alembic
scripts/       seed_showroom.py, import_molds.py, update_cloudflare_ips.sh, fetch_static_images.py,
               (예정) wp_import.py, backup.sh
tests/
deploy/        docker-compose.yml(로컬), docker-compose.prod.yml(운영), nginx/
var/           로컬 업로드·덤프 (git 제외)
```

## 운영 구성 로컬 점검 (기획서 6장)

```bash
make prod-up     # .env.prod-local, 자체 서명 인증서를 만들고 운영 Compose로 기동
                 # → https://localhost (인증서 경고는 무시)
make prod-down
```

운영 Compose는 Nginx가 정적 파일을 서빙하고, `/_private/`(견적 첨부)는 외부에서 직접 열 수 없습니다(`X-Accel-Redirect` 전용). 도메인이 아닌 Host로 들어온 요청은 응답 없이 끊습니다.

## 운영 서버 배포 메모

1. `.env.example`을 `.env`로 복사한 뒤 `APP_ENV=prod`, `SECRET_KEY`, `DATA_KEYS`, `POSTGRES_PASSWORD`, SMTP, `STAFF_NOTIFY_EMAILS`, Turnstile 운영 키를 채웁니다.
   `DATA_KEYS`(연락처·이메일 암호화 키)를 잃으면 저장된 개인정보를 복구할 수 없으므로 서버 밖에도 따로 보관합니다.
2. Cloudflare Origin 인증서를 `deploy/certs/origin.pem`, `origin.key`로 둡니다.
3. 업로드 폴더를 만듭니다: `sudo mkdir -p /data/media/{public,private} && sudo chown -R 1000 /data/media`
4. `docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build`
5. `docker compose ... exec web alembic upgrade head`

Cloudflare IP 대역이 바뀌면 `scripts/update_cloudflare_ips.sh`를 실행해 `deploy/nginx/cloudflare-ips.conf`를 갱신하고, 서버 방화벽 규칙도 같은 목록으로 맞춥니다.
