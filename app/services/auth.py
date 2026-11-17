"""관리자 로그인: argon2 비밀번호, 세션 쿠키, 로그인 실패 제한.

세션 쿠키(서명된 itsdangerous 쿠키)에는 사용자 ID와 session_version만 담습니다.
비밀번호를 바꾸거나 계정을 끄면 session_version이 올라가 기존 로그인이 모두 풀립니다.
"""

from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt, User

SESSION_COOKIE = "gp_admin"
SESSION_MAX_AGE = 8 * 3600  # 마지막 요청 후 8시간이 지나면 다시 로그인

# 실패 제한: 최근 LOCK_WINDOW 동안 계정별 5회, IP별 20회 실패하면 잠시 막습니다.
LOCK_WINDOW = timedelta(minutes=15)
MAX_FAILS_PER_EMAIL = 5
MAX_FAILS_PER_IP = 20
ATTEMPT_RETENTION = timedelta(days=90)

MIN_PASSWORD_LEN = 10

_hasher = PasswordHasher()
# 없는 계정으로 로그인할 때도 같은 시간이 걸리게 하는 더미 해시
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_problem(password: str, confirm: str | None = None) -> str | None:
    if len(password) < MIN_PASSWORD_LEN:
        return f"비밀번호는 {MIN_PASSWORD_LEN}자 이상으로 정해 주세요."
    if password.isdigit() or password.isalpha():
        return "비밀번호에 문자와 숫자(또는 기호)를 섞어 주세요."
    if confirm is not None and password != confirm:
        return "비밀번호 확인이 일치하지 않습니다."
    return None


def verify_password(user: User | None, password: str) -> bool:
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except VerificationError, InvalidHashError:
        return False
    return user is not None


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.session_version += 1


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_locked(db: Session, email: str, ip: str, now: datetime | None = None) -> bool:
    since = (now or datetime.now(UTC)) - LOCK_WINDOW
    fails = select(func.count()).where(~LoginAttempt.success, LoginAttempt.created_at > since)

    # 계정별 실패는 마지막 성공 이후만 셉니다.
    last_ok = db.scalar(
        select(func.max(LoginAttempt.created_at)).where(
            LoginAttempt.email == email, LoginAttempt.success
        )
    )
    by_email = fails.where(LoginAttempt.email == email)
    if last_ok:
        by_email = by_email.where(LoginAttempt.created_at > last_ok)
    if db.scalar(by_email) >= MAX_FAILS_PER_EMAIL:
        return True
    return db.scalar(fails.where(LoginAttempt.ip == ip)) >= MAX_FAILS_PER_IP


class LoginLocked(Exception):
    pass


def authenticate(db: Session, email: str, password: str, ip: str) -> User | None:
    """성공하면 User, 실패하면 None. 잠긴 상태면 LoginLocked. 커밋은 호출한 쪽에서 합니다."""
    email = normalize_email(email)[:200]
    ip = ip[:45]
    if is_locked(db, email, ip):
        raise LoginLocked
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(user, password) and user.is_active
    db.add(LoginAttempt(email=email, ip=ip, success=ok))
    if not ok:
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < datetime.now(UTC) - ATTEMPT_RETENTION)
    )
    return user


def session_payload(user: User) -> dict:
    return {"uid": user.id, "ver": user.session_version}


def user_from_session(db: Session, session: dict) -> User | None:
    uid, ver = session.get("uid"), session.get("ver")
    if not isinstance(uid, int):
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active or user.session_version != ver:
        return None
    return user
