"""견적 접수: 접수번호 발급, 저장, 알림 메일."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, StrictUndefined
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.content import COMPANY
from app.models import Inquiry, InquiryFile, InquirySpec
from app.services import mailer
from app.services.inquiry_form import SPEC_FIELDS
from app.templating import templates

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
COMPLETE_MAX_AGE = 24 * 3600  # 접수 완료 화면 링크 유효 시간
# 메일 본문(일반 텍스트)용: HTML 이스케이프 없이 렌더링
mail_env = Environment(
    loader=templates.env.loader,
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)
mail_env.globals.update(company=COMPANY)
_NULLABLE_SPECS = {"box_type", "width", "depth", "height"}  # 비면 NULL, 나머지는 ""


def next_number(db: Session, now: datetime | None = None) -> str:
    """접수번호 YYMMDD-NNN (한국 날짜 기준, 날마다 001부터).

    트랜잭션 단위 advisory lock으로 동시 접수 시 번호가 겹치지 않게 합니다.
    """
    day = (now or datetime.now(UTC)).astimezone(KST).strftime("%y%m%d")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('inquiry_number'))"))
    last = db.scalar(select(func.max(Inquiry.number)).where(Inquiry.number.like(f"{day}-%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{day}-{seq:03d}"


def create(
    db: Session,
    clean: dict,
    files: list[tuple[str, str, int, str]],
    *,
    ip: str = "",
    user_agent: str = "",
    portfolio_item_id: int | None = None,
) -> Inquiry:
    """files: (원본 이름, 저장 경로, 크기, content-type). 커밋은 호출한 쪽에서 합니다."""
    inq = Inquiry(
        number=next_number(db),
        company=clean["company"],
        name=clean["name"],
        phone=clean["phone"],
        email=clean["email"],
        position=clean["position"],
        delivery_location=clean["delivery_location"],
        title=clean["title"],
        content=clean["content"],
        quantity=clean["quantity"],
        budget=clean["budget"],
        mold_id=clean.get("mold_id"),
        portfolio_item_id=portfolio_item_id,
        privacy_agreed_at=datetime.now(UTC),
        ip=ip[:45],
        user_agent=user_agent[:300],
    )
    inq.spec = InquirySpec(
        **{k: clean.get(k) or (None if k in _NULLABLE_SPECS else "") for k in SPEC_FIELDS}
    )
    for name, path, size, ctype in files:
        inq.files.append(InquiryFile(original_name=name, path=path, size=size, content_type=ctype))
    db.add(inq)
    db.flush()
    return inq


# ── 접수 완료 화면 링크 ──────────────────────────────────────
def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="inquiry-complete")


def complete_token(inquiry_id: int) -> str:
    return _signer().dumps(inquiry_id)


def read_complete_token(token: str) -> int | None:
    try:
        return int(_signer().loads(token, max_age=COMPLETE_MAX_AGE))
    except BadSignature, ValueError, TypeError:
        return None


# ── 알림 메일 ────────────────────────────────────────────────
def _session() -> Session:
    """알림용 새 세션 (테스트에서는 테스트 세션으로 바꿉니다)."""
    from app.db import SessionLocal

    return SessionLocal()


def notify(inquiry_id: int) -> None:
    """고객 확인 메일 + 담당자 알림. 응답 후 백그라운드에서 새 세션으로 실행합니다."""
    s = get_settings()
    with _session() as db:
        inq = db.get(Inquiry, inquiry_id)
        if inq is None:
            log.error("알림 대상 견적 없음: %s", inquiry_id)
            return
        ctx = {"inq": inq, "settings": s, "received_at": inq.created_at.astimezone(KST)}
        render = mail_env.get_template
        mailer.send(
            [inq.email],
            f"[좋은상자] 견적문의가 접수되었습니다 (접수번호 {inq.number})",
            render("emails/inquiry_customer.txt").render(ctx),
        )
        mailer.send(
            s.staff_notify_emails,
            f"[견적접수 {inq.number}] {inq.company} — {inq.title}",
            render("emails/inquiry_staff.txt").render(ctx),
            reply_to=inq.email,
        )
        if s.alimtalk_enabled:
            log.info("알림톡 발송 예정 기능 (견적 %s)", inq.number)
