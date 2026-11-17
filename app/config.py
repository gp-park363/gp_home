"""환경 설정. 값은 .env 또는 환경 변수에서 읽습니다 (로컬/운영 구분은 APP_ENV)."""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

DEV_SECRET = "dev-only-insecure-secret"
# 개발·테스트 전용 개인정보 암호화 키 (운영에서는 DATA_KEYS 필수)
DEV_DATA_KEY = "Z29vZHBhY2thZ2UtZGV2LW9ubHktZGF0YS1rZXktMzI="

# Cloudflare 공식 테스트 키 (항상 통과)
TURNSTILE_TEST_SITE_KEY = "1x00000000000000000000AA"
TURNSTILE_TEST_SECRET_KEY = "1x0000000000000000000000000000000AA"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    site_url: str = "http://localhost:8000"
    secret_key: str = DEV_SECRET
    # 연락처·이메일 암호화 키 (Fernet). 쉼표로 여러 개를 두면
    # 첫 키로 암호화하고 모든 키로 복호화합니다.
    # 키 교체: 새 키를 맨 앞에 추가 → 재암호화 → 옛 키 제거. 키를 잃으면 복구할 수 없습니다.
    data_keys: str = DEV_DATA_KEY

    database_url: str = "postgresql+psycopg://goodpackage:goodpackage@localhost:5432/goodpackage"

    # 업로드 저장 위치: public(쇼룸 이미지, Nginx 직접 서빙) / private(견적 첨부, 권한 확인 후 전달)
    media_root: Path = BASE_DIR.parent / "var" / "media"

    # 메일 (로컬은 Mailpit이 가로챔)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    mail_from: str = "좋은상자 <no-reply@goodpackage.co.kr>"
    staff_notify_emails: list[str] = []

    turnstile_site_key: str = TURNSTILE_TEST_SITE_KEY
    turnstile_secret_key: str = TURNSTILE_TEST_SECRET_KEY

    # 카카오 알림톡: 비활성 시 로그 출력으로 대체
    alimtalk_enabled: bool = False

    naver_map_client_id: str = ""
    kakao_channel_id: str = ""

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def media_public(self) -> Path:
        return self.media_root / "public"

    @property
    def media_private(self) -> Path:
        return self.media_root / "private"

    @model_validator(mode="after")
    def _check_prod(self) -> Settings:
        if self.is_prod:
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                raise ValueError("운영 환경에서는 32자 이상의 SECRET_KEY가 필요합니다.")
            if DEV_DATA_KEY in self.data_keys:
                raise ValueError("운영 환경에서는 DATA_KEYS를 새로 만들어 설정해야 합니다.")
            # 로컬에서 운영 구성을 점검할 때는 테스트 키를 쓰므로 경고만 남깁니다.
            if self.turnstile_secret_key == TURNSTILE_TEST_SECRET_KEY:
                logging.getLogger(__name__).warning("Turnstile 테스트 키 사용 중 — 운영 키로 교체")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
