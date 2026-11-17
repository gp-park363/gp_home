"""메일 발송 (SMTP). 로컬은 Mailpit이 받습니다.

발송 실패는 접수 자체를 막지 않도록 로그만 남깁니다. 응답 후 BackgroundTasks로 호출합니다.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.config import get_settings

log = logging.getLogger(__name__)


# (파일명, 내용, content-type)
Attachment = tuple[str, bytes, str]


def build(
    to: list[str],
    subject: str,
    text: str,
    reply_to: str | None = None,
    attachments: list[Attachment] = (),
) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.mail_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="goodpackage.co.kr")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    for name, data, ctype in attachments:
        main, _, sub = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=name)
    return msg


def deliver(msg: EmailMessage) -> bool:
    s = get_settings()
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except OSError, smtplib.SMTPException:
        log.exception("메일 발송 실패: %s → %s", msg["Subject"], msg["To"])
        return False


def send(
    to: list[str],
    subject: str,
    text: str,
    reply_to: str | None = None,
    attachments: list[Attachment] = (),
) -> bool:
    if not to:
        log.warning("수신자가 없어 메일을 보내지 않음: %s", subject)
        return False
    return deliver(build(to, subject, text, reply_to, attachments))
