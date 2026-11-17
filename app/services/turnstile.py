"""Cloudflare Turnstile(스팸 방지) 서버 검증."""

import json
import logging
import urllib.parse
import urllib.request

from app.config import TURNSTILE_TEST_SECRET_KEY, get_settings

log = logging.getLogger(__name__)
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify(token: str, ip: str = "") -> bool:
    s = get_settings()
    # 공식 테스트 키는 항상 통과하므로, 개발·테스트에서는 외부 호출 없이 통과시킵니다.
    if s.turnstile_secret_key == TURNSTILE_TEST_SECRET_KEY and not s.is_prod:
        return True
    if not token:
        return False
    body = urllib.parse.urlencode(
        {"secret": s.turnstile_secret_key, "response": token, "remoteip": ip}
    ).encode()
    try:
        with urllib.request.urlopen(VERIFY_URL, data=body, timeout=10) as res:
            return bool(json.load(res).get("success"))
    except OSError, ValueError:
        log.exception("Turnstile 검증 요청 실패")
        return False
