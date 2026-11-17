"""관리자 견적 처리: 목록 검색, 답변 발송, 내부 메모, 상태·담당 변경, 삭제."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.content import INQUIRY_STATUSES
from app.models import Inquiry, InquiryReply, InquiryReplyFile, User
from app.services import mailer, storage
from app.services.inquiry import KST, mail_env
from app.services.inquiry_form import ALLOWED_EXTENSIONS

log = logging.getLogger(__name__)

REPLY_MAX_FILES = 3
REPLY_MAX_TOTAL = 20 * 1024 * 1024  # 메일 첨부 합계 한도 (메일 서버 대부분 25MB)
OPEN_STATUSES = ("received", "in_progress")


# ── 목록 ─────────────────────────────────────────────────────
@dataclass
class Filters:
    status: str = ""
    assignee: str = ""  # "" 전체 / "me" / "none" / 사용자 ID
    start: date | None = None
    end: date | None = None
    q: str = ""

    def query(self, user: User, *, with_status: bool = True) -> Select:
        stmt = select(Inquiry)
        if with_status and self.status in INQUIRY_STATUSES:
            stmt = stmt.where(Inquiry.status == self.status)
        if self.assignee == "me":
            stmt = stmt.where(Inquiry.assignee_id == user.id)
        elif self.assignee == "none":
            stmt = stmt.where(Inquiry.assignee_id.is_(None))
        elif self.assignee.isdigit():
            stmt = stmt.where(Inquiry.assignee_id == int(self.assignee))
        if self.start:
            stmt = stmt.where(Inquiry.created_at >= _kst_midnight(self.start))
        if self.end:
            stmt = stmt.where(Inquiry.created_at < _kst_midnight(self.end + timedelta(days=1)))
        if q := self.q.strip():
            # 연락처·이메일은 암호화돼 검색할 수 없습니다.
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Inquiry.number.ilike(like),
                    Inquiry.title.ilike(like),
                    Inquiry.company.ilike(like),
                    Inquiry.name.ilike(like),
                )
            )
        return stmt

    def status_counts(self, db: Session, user: User) -> dict[str, int]:
        q = self.query(user, with_status=False).subquery()
        rows = db.execute(select(q.c.status, func.count()).group_by(q.c.status)).all()
        counts = dict(rows)
        counts[""] = sum(counts.values())
        return counts


def _kst_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=KST)


# ── 처리 이력 ────────────────────────────────────────────────
def _log(db: Session, inq: Inquiry, user: User, body: str) -> InquiryReply:
    entry = InquiryReply(kind="event", body=body, author_id=user.id, author_name=user.name)
    inq.replies.append(entry)
    db.flush()
    return entry


def change_status(db: Session, inq: Inquiry, user: User, status: str) -> bool:
    if status not in INQUIRY_STATUSES or status == inq.status:
        return False
    before = inq.status_label
    inq.status = status
    _log(db, inq, user, f"상태 변경: {before} → {inq.status_label}")
    return True


def assign(db: Session, inq: Inquiry, user: User, assignee: User | None) -> bool:
    if (assignee.id if assignee else None) == inq.assignee_id:
        return False
    inq.assignee = assignee
    _log(db, inq, user, f"담당 지정: {assignee.name}" if assignee else "담당 해제")
    return True


def add_memo(db: Session, inq: Inquiry, user: User, body: str) -> InquiryReply:
    memo = InquiryReply(kind="memo", body=body, author_id=user.id, author_name=user.name)
    inq.replies.append(memo)
    db.flush()
    return memo


def check_reply_files(files: list[tuple[str, int]]) -> str | None:
    """files: (파일명, 크기)."""
    if len(files) > REPLY_MAX_FILES:
        return f"답변 첨부는 최대 {REPLY_MAX_FILES}개입니다."
    for name, _ in files:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            return f"{name}: 첨부할 수 없는 형식입니다."
    if sum(size for _, size in files) > REPLY_MAX_TOTAL:
        return "첨부 합계가 20MB를 넘습니다. 큰 파일은 나눠 보내 주세요."
    return None


def add_reply(
    db: Session,
    inq: Inquiry,
    user: User,
    body: str,
    files: list[tuple[str, str, int, str]] = (),
) -> InquiryReply:
    """고객 답변 저장. 상태를 답변완료로 바꾸고, 담당이 없으면 작성자를 담당으로 지정합니다.

    files: (원본 이름, 저장 경로, 크기, content-type). 메일 발송은 send_reply()로 따로 합니다.
    """
    reply = InquiryReply(kind="reply", body=body, author_id=user.id, author_name=user.name)
    for name, path, size, ctype in files:
        reply.files.append(
            InquiryReplyFile(original_name=name, path=path, size=size, content_type=ctype)
        )
    inq.replies.append(reply)
    if inq.assignee_id is None:
        assign(db, inq, user, user)
    if inq.status in OPEN_STATUSES:
        change_status(db, inq, user, "answered")
    inq.answered_at = datetime.now(UTC)
    db.flush()
    return reply


def send_reply(inq: Inquiry, reply: InquiryReply, author: User | None) -> bool:
    """답변 메일 발송. 성공하면 emailed_at을 기록합니다 (커밋은 호출한 쪽에서)."""
    s = get_settings()
    body = mail_env.get_template("emails/inquiry_reply.txt").render(
        inq=inq,
        reply=reply,
        settings=s,
        received_at=inq.created_at.astimezone(KST),
    )
    attachments = [
        (f.original_name, storage.private_path(f.path).read_bytes(), f.content_type)
        for f in reply.files
    ]
    ok = mailer.send(
        [inq.email],
        f"[좋은상자] 견적문의 답변드립니다 (접수번호 {inq.number})",
        body,
        reply_to=author.email if author else None,
        attachments=attachments,
    )
    if ok:
        reply.emailed_at = datetime.now(UTC)
    else:
        log.warning("답변 메일 실패: 견적 %s 답변 %s", inq.number, reply.id)
    return ok


def delete(db: Session, inq: Inquiry) -> list[str]:
    """견적을 지우고, 커밋 뒤 지울 첨부 파일(고객·답변) 경로를 돌려줍니다."""
    paths = [f.path for f in inq.files] + [f.path for r in inq.replies for f in r.files]
    db.delete(inq)
    db.flush()
    return paths
