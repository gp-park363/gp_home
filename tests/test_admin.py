import io
import re
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import Workbook, load_workbook
from PIL import Image
from sqlalchemy import select

from app.models import Inquiry, InquiryReply, LoginAttempt, Mold, PortfolioItem, User
from app.services import auth, mailer
from app.services import inquiry as inquiry_service
from tests.conftest import login

HX = {"HX-Request": "true"}


@pytest.fixture
def make_inquiry(db):
    def _make(title="화장품 단상자 문의", files=(), **kw):
        clean = {
            "company": "테스트상사",
            "name": "홍길동",
            "phone": "010-1234-5678",
            "email": "buyer@example.com",
            "position": "",
            "delivery_location": "",
            "title": title,
            "content": "본문",
            "quantity": "",
            "budget": "",
            "box_type": "lid",
            "width": 120,
            "depth": 80,
            "height": 40,
        } | kw
        inq = inquiry_service.create(db, clean, list(files))
        return inq

    return _make


# ── 로그인 ────────────────────────────────────────────────────
def test_admin_requires_login(client):
    r = client.get("/admin/inquiries/?status=received", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login?next=/admin/inquiries/%3Fstatus%3Dreceived"
    # htmx 요청은 로그인 화면으로 이동시킵니다
    r = client.get("/admin/inquiries/", headers=HX)
    assert r.status_code == 401 and r.headers["HX-Redirect"].startswith("/admin/login")


def test_login_and_logout(client, make_user):
    user = make_user(email="kim@goodpackage.test")
    r = login(client, " KIM@goodpackage.test ")
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    cookie = r.headers["set-cookie"]
    assert (
        "path=/admin" in cookie.lower()
        and "httponly" in cookie.lower()
        and "samesite=lax" in cookie.lower()
    )

    r = client.get("/admin/")
    assert r.status_code == 200 and user.name in r.text
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]

    client.post("/admin/logout")
    assert client.get("/admin/", follow_redirects=False).status_code == 303


def test_login_wrong_password(client, make_user):
    make_user()
    r = login(client, "sales@goodpackage.test", "wrong-password-1")
    assert r.status_code == 400 and "맞지 않습니다" in r.text


def test_inactive_user_cannot_login(client, make_user):
    make_user(is_active=False)
    assert login(client, "sales@goodpackage.test").status_code == 400


def test_login_lockout_after_failures(client, db, make_user):
    make_user()
    for _ in range(auth.MAX_FAILS_PER_EMAIL):
        login(client, "sales@goodpackage.test", "wrong-password-1")
    r = login(client, "sales@goodpackage.test")  # 비밀번호가 맞아도 막힘
    assert r.status_code == 400 and "15분" in r.text

    # 잠금 시간이 지나면 다시 로그인할 수 있습니다
    for a in db.scalars(select(LoginAttempt)):
        a.created_at = datetime.now(UTC) - auth.LOCK_WINDOW - timedelta(minutes=1)
    db.flush()
    assert login(client, "sales@goodpackage.test").status_code == 303


def test_login_next_only_inside_admin(client, make_user):
    make_user()
    r = client.post(
        "/admin/login",
        data={"email": "sales@goodpackage.test", "password": "test-pass-123", "next": "//evil.com"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/admin/"


def test_password_change_logs_out_other_sessions(client, db, staff):
    from fastapi.testclient import TestClient

    from app.main import app

    other = TestClient(app)
    login(other, staff.email)
    assert other.get("/admin/", follow_redirects=False).status_code == 200

    r = client.post(
        "/admin/password",
        data={"current": "test-pass-123", "new": "new-pass-4567", "confirm": "new-pass-4567"},
    )
    assert "바꿨습니다" in r.text
    assert client.get("/admin/", follow_redirects=False).status_code == 200  # 지금 브라우저는 유지
    assert other.get("/admin/", follow_redirects=False).status_code == 303  # 다른 기기는 해제


def test_password_rules(client, staff):
    r = client.post(
        "/admin/password", data={"current": "test-pass-123", "new": "short", "confirm": "short"}
    )
    assert r.status_code == 400 and "10자" in r.text


def test_cross_site_post_rejected(client, staff, make_inquiry):
    inq = make_inquiry()
    r = client.post(
        f"/admin/inquiries/{inq.id}/status",
        data={"status": "closed"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert inq.status == "received"


def test_sales_cannot_use_admin_only(client, staff, make_inquiry):
    assert client.get("/admin/users/").status_code == 403
    assert client.get("/admin/showroom/").status_code == 403
    inq = make_inquiry()
    assert client.post(f"/admin/inquiries/{inq.id}/delete").status_code == 403


# ── 견적 목록 ─────────────────────────────────────────────────
def test_inquiry_list_filters(client, db, staff, make_user, make_inquiry):
    other = make_user(email="other@goodpackage.test", name="박영업")
    a = make_inquiry(title="홍삼 선물세트 상자", company="정관장상사")
    b = make_inquiry(title="화장품 단상자")
    b.assignee_id, b.status = staff.id, "in_progress"
    c = make_inquiry(title="택배 박스")
    c.assignee_id = other.id
    old = make_inquiry(title="작년 문의")
    old.created_at = datetime(2025, 1, 5, 3, tzinfo=UTC)
    db.flush()

    def titles(**params):
        r = client.get("/admin/inquiries/", params=params, headers=HX)
        return set(re.findall(r'truncate font-medium text-ink">([^<]+)<', r.text))

    assert titles() == {a.title, b.title, c.title, old.title}
    assert titles(status="in_progress") == {b.title}
    assert titles(assignee="me") == {b.title}
    assert titles(assignee="none") == {a.title, old.title}
    assert titles(assignee=str(other.id)) == {c.title}
    assert titles(q="정관장") == {a.title}
    assert titles(q=a.number) == {a.title}
    assert titles(start="2025-01-01", end="2025-01-05") == {old.title}

    # 상태 탭 건수는 다른 필터를 적용한 값입니다
    r = client.get("/admin/inquiries/", params={"assignee": "me"}, headers=HX)
    assert re.search(r"상담중 <span[^>]*>1<", r.text)
    # 전체 화면은 필터 폼 포함
    r = client.get("/admin/inquiries/?q=정관장")
    assert 'id="inq-filters"' in r.text and 'value="정관장"' in r.text


def test_inquiry_list_pagination(client, staff, make_inquiry):
    for n in range(23):
        make_inquiry(title=f"문의 {n}")
    r = client.get("/admin/inquiries/?page=2")
    assert "2 / 2 쪽 · 23건" in r.text
    assert r.text.count('href="/admin/inquiries/') >= 3


def test_dashboard(client, staff, make_inquiry):
    make_inquiry(title="미지정 문의")
    r = client.get("/admin/")
    assert "미지정 문의" in r.text and "오늘 접수" in r.text


# ── 견적 상세·처리 ────────────────────────────────────────────
def test_inquiry_detail_shows_decrypted_contact(client, staff, make_inquiry):
    inq = make_inquiry()
    r = client.get(f"/admin/inquiries/{inq.id}")
    assert r.status_code == 200
    assert "010-1234-5678" in r.text and "buyer@example.com" in r.text
    assert "맞뚜껑형" in r.text and "120×80×40" in r.text
    assert client.get("/admin/inquiries/999999").status_code == 404


def test_status_and_assignee_change_logged(client, db, staff, make_inquiry):
    inq = make_inquiry()
    r = client.post(f"/admin/inquiries/{inq.id}/status", data={"status": "in_progress"}, headers=HX)
    assert "상태 변경: 접수 → 상담중" in r.text
    assert 'id="inq-status-badge" hx-swap-oob="true"' in r.text
    r = client.post(
        f"/admin/inquiries/{inq.id}/assignee", data={"assignee_id": str(staff.id)}, headers=HX
    )
    assert f"담당 지정: {staff.name}" in r.text
    db.refresh(inq)
    assert inq.status == "in_progress" and inq.assignee_id == staff.id
    # 같은 값이면 기록하지 않습니다
    client.post(f"/admin/inquiries/{inq.id}/status", data={"status": "in_progress"}, headers=HX)
    assert len([r for r in inq.replies if r.kind == "event"]) == 2


def test_memo_is_not_emailed(client, db, staff, outbox, make_inquiry):
    inq = make_inquiry()
    r = client.post(
        f"/admin/inquiries/{inq.id}/replies",
        data={"kind": "memo", "body": "단가 확인 필요"},
        headers=HX,
    )
    assert "단가 확인 필요" in r.text and r.headers["HX-Trigger"] == "composer-reset"
    assert outbox == []
    db.refresh(inq)
    assert inq.status == "received"


def test_reply_sends_mail_with_attachment(client, db, staff, outbox, make_inquiry):
    inq = make_inquiry()
    pdf = ("files", ("견적서.pdf", b"%PDF-1.4 quote", "application/pdf"))
    r = client.post(
        f"/admin/inquiries/{inq.id}/replies",
        data={"kind": "reply", "body": "단가는 개당 500원입니다."},
        files=[pdf],
        headers=HX,
    )
    assert "✓ 메일 발송" in r.text and "견적서.pdf" in r.text

    mail = outbox[-1]
    assert mail["To"] == "buyer@example.com" and mail["Reply-To"] == staff.email
    assert inq.number in mail["Subject"]
    body = mail.get_body(("plain",)).get_content()
    assert "단가는 개당 500원입니다." in body and "김영업" in body
    att = next(mail.iter_attachments())
    assert att.get_filename() == "견적서.pdf" and att.get_content() == b"%PDF-1.4 quote"

    db.refresh(inq)
    assert inq.status == "answered" and inq.answered_at
    assert inq.assignee_id == staff.id  # 담당이 없으면 답변한 사람이 담당
    reply = next(x for x in inq.replies if x.kind == "reply")
    assert reply.emailed_at and reply.files[0].path.startswith("replies/")

    # 답변 첨부도 로그인한 직원만 받을 수 있습니다
    url = f"/admin/inquiries/{inq.id}/reply-files/{reply.files[0].id}"
    assert client.get(url).content == b"%PDF-1.4 quote"


def test_reply_mail_failure_can_resend(client, db, staff, outbox, make_inquiry, monkeypatch):
    inq = make_inquiry()
    monkeypatch.setattr(mailer, "deliver", lambda msg: False)
    r = client.post(
        f"/admin/inquiries/{inq.id}/replies", data={"kind": "reply", "body": "답변"}, headers=HX
    )
    assert "메일 발송에 실패" in r.text and "다시 보내기" in r.text
    reply = db.scalar(select(InquiryReply).where(InquiryReply.kind == "reply"))
    assert reply.emailed_at is None

    monkeypatch.setattr(mailer, "deliver", lambda msg: outbox.append(msg) or True)
    r = client.post(f"/admin/inquiries/{inq.id}/replies/{reply.id}/resend", headers=HX)
    assert "✓ 메일 발송" in r.text and len(outbox) == 1


def test_reply_validation(client, staff, outbox, make_inquiry):
    inq = make_inquiry()
    r = client.post(
        f"/admin/inquiries/{inq.id}/replies", data={"kind": "reply", "body": " "}, headers=HX
    )
    assert "내용을 입력해 주세요" in r.text and r.headers["HX-Retarget"] == "#composer-error"
    exe = ("files", ("run.exe", b"MZ", "application/octet-stream"))
    r = client.post(
        f"/admin/inquiries/{inq.id}/replies",
        data={"kind": "reply", "body": "답변"},
        files=[exe],
        headers=HX,
    )
    assert "형식" in r.text and outbox == []


def test_customer_file_download_requires_login(client, db, make_user, make_inquiry):
    from app.services import storage

    path = storage.save_private(io.BytesIO(b"design"), "시안.ai", "inquiries")
    inq = make_inquiry(files=[("시안.ai", path, 6, "application/postscript")])
    url = f"/admin/inquiries/{inq.id}/files/{inq.files[0].id}"
    assert client.get(url, follow_redirects=False).status_code == 303

    user = make_user()
    login(client, user.email)
    r = client.get(url)
    assert r.content == b"design" and "attachment" in r.headers["content-disposition"]
    # 다른 견적 번호로는 받을 수 없습니다
    other = make_inquiry()
    assert client.get(f"/admin/inquiries/{other.id}/files/{inq.files[0].id}").status_code == 404


def test_download_uses_x_accel_in_prod(monkeypatch):
    from app.config import get_settings
    from app.services import storage

    monkeypatch.setattr(get_settings(), "app_env", "prod")
    r = storage.download_response("inquiries/2026/11/abc.pdf", "견적 시안.pdf", "application/pdf")
    assert r.headers["X-Accel-Redirect"] == "/_private/inquiries/2026/11/abc.pdf"
    assert "filename*=UTF-8''%EA%B2%AC" in r.headers["Content-Disposition"]


def test_admin_can_delete_inquiry(client, db, admin, make_inquiry, _media_tmp):
    from app.services import storage

    path = storage.save_private(io.BytesIO(b"x"), "a.pdf", "inquiries")
    inq = make_inquiry(files=[("a.pdf", path, 1, "application/pdf")])
    r = client.post(f"/admin/inquiries/{inq.id}/delete", headers=HX)
    assert r.headers["HX-Redirect"] == "/admin/inquiries/"
    assert db.get(Inquiry, inq.id) is None
    assert not (_media_tmp / "private" / path).exists()


# ── 목형 ──────────────────────────────────────────────────────
def test_mold_create_edit_delete(client, db, staff):
    data = {"code": "M-100", "box_type": "lid", "width": "120", "depth": "80", "height": "40"}
    r = client.post("/admin/molds/", data=data | {"active": "y"}, headers=HX)
    assert "M-100" in r.text and r.headers["HX-Trigger"] == "mold-created"
    mold = db.scalar(select(Mold).where(Mold.code == "M-100"))

    r = client.post("/admin/molds/", data=data, headers=HX)
    assert "이미 있습니다" in r.text and r.headers["HX-Retarget"] == "#new-mold-error"

    r = client.post(f"/admin/molds/{mold.id}", data=data | {"width": "abc"}, headers=HX)
    assert "숫자가 아닙니다" in r.text and 'name="width" value="abc"' in r.text
    r = client.post(f"/admin/molds/{mold.id}", data=data | {"width": "130"}, headers=HX)
    assert "130×80×40" in r.text and "사용 안 함" in r.text  # 체크 해제 = 사용 안 함
    db.refresh(mold)
    assert mold.width == 130 and not mold.is_active

    assert client.delete(f"/admin/molds/{mold.id}", headers=HX).text == ""
    assert db.get(Mold, mold.id) is None


def test_mold_list_search(client, staff, make_mold):
    make_mold(code="A-1", width=120, depth=80, height=40, memo="화장품")
    make_mold(code="B-2", width=300, depth=200, height=100)
    r = client.get("/admin/molds/?q=122x80x38", headers=HX)
    assert "A-1" in r.text and "B-2" not in r.text
    r = client.get("/admin/molds/?q=화장품", headers=HX)
    assert "A-1" in r.text and "B-2" not in r.text


def _xlsx(rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_mold_excel_import(client, db, staff, make_mold):
    make_mold(code="K-1", width=10, depth=10, height=10)
    data = _xlsx(
        [
            ["목형번호", "박스형태", "가로", "세로", "높이", "메모", "사용"],
            ["K-1", "맞뚜껑형", 120, 80, 40, "덮어씀", "Y"],
            ["K-2", "b", "200", "150", "100", "", "N"],
            [None, "G형", 50.0, 50, 50, None, None],
        ]
    )
    r = client.post(
        "/admin/molds/import", files={"file": ("목형.xlsx", data, "application/octet-stream")}
    )
    assert "추가 2건, 갱신 1건" in r.text and r.headers["HX-Trigger"] == "molds-imported"
    k1 = db.scalar(select(Mold).where(Mold.code == "K-1"))
    assert (k1.width, k1.memo) == (120, "덮어씀")
    assert not db.scalar(select(Mold).where(Mold.code == "K-2")).is_active


def test_mold_import_all_or_nothing(client, db, staff):
    data = "code,box_type,width,depth,height\nX-1,lid,10,10,10\nX-2,없는형태,10,10,10\n".encode()
    r = client.post("/admin/molds/import", files={"file": ("m.csv", data, "text/csv")})
    assert "오류 1건" in r.text and "3행" in r.text
    assert db.scalar(select(Mold).where(Mold.code == "X-1")) is None


def test_mold_import_cp949_csv_and_bad_header(client, staff):
    data = "목형번호,박스형태,가로,세로,높이\nC-1,싸바리형,10,10,10\n".encode("cp949")
    r = client.post("/admin/molds/import", files={"file": ("m.csv", data, "text/csv")})
    assert "추가 1건" in r.text
    r = client.post("/admin/molds/import", files={"file": ("m.csv", b"a,b\n1,2\n", "text/csv")})
    assert "열 이름이 필요합니다" in r.text
    r = client.post("/admin/molds/import", files={"file": ("m.txt", b"x", "text/plain")})
    assert "xlsx" in r.text


def test_mold_export_roundtrip(client, staff, make_mold):
    make_mold(code="E-1", memo="메모")
    r = client.get("/admin/molds/export.xlsx")
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][:5] == ("목형번호", "박스형태", "가로", "세로", "높이")
    assert ("E-1", "맞뚜껑형", 120, 80, 40, "메모", "Y") in rows


# ── 쇼룸 (관리자) ─────────────────────────────────────────────
def _png(w=1200, h=600):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "red").save(buf, "PNG")
    return buf.getvalue()


def test_showroom_create_with_images(client, db, admin, _media_tmp):
    form = {"name": "새 선물상자", "code": "GP2001", "box_type": "lid", "industry": "food"}
    files = [
        ("thumb", ("t.png", _png(), "image/png")),
        ("images", ("a.png", _png(2400, 1200), "image/png")),
        ("images", ("b.png", _png(), "image/png")),
    ]
    r = client.post("/admin/showroom/new", data=form | {"is_published": "y"}, files=files)
    assert r.status_code == 200 and "저장했습니다" in r.text
    item = db.scalar(select(PortfolioItem).where(PortfolioItem.code == "GP2001"))
    assert len(item.images) == 2 and item.images[0].width == 1600  # 큰 사진은 줄임
    with Image.open(_media_tmp / "public" / item.thumb_path) as im:
        assert im.size == (800, 600) and im.format == "WEBP"
    assert client.get(f"/portfolio/{item.id}").status_code == 200


def test_showroom_validation_and_bad_image(client, db, admin):
    r = client.post("/admin/showroom/new", data={"name": "", "box_type": "x", "industry": "food"})
    assert r.status_code == 422 and "품명을 입력해 주세요" in r.text
    r = client.post(
        "/admin/showroom/new",
        data={"name": "상자", "box_type": "lid", "industry": "food"},
        files=[("images", ("fake.png", b"not image", "image/png"))],
    )
    assert r.status_code == 422 and "읽을 수 없습니다" in r.text
    assert db.scalar(select(PortfolioItem)) is None


def test_showroom_image_order_delete_and_publish(client, db, admin, make_portfolio):
    item = make_portfolio(images=3)
    first, second, third = item.images
    r = client.post(f"/admin/showroom/{item.id}/images/{second.id}/move?dir=up", headers=HX)
    assert r.text.index(second.url) < r.text.index(first.url)
    client.post(f"/admin/showroom/{item.id}/images/{third.id}/delete", headers=HX)
    db.refresh(item)
    assert [i.id for i in item.images] == [second.id, first.id]

    r = client.post(f"/admin/showroom/{item.id}/publish", headers=HX)
    assert "숨김" in r.text
    assert client.get(f"/portfolio/{item.id}").status_code == 404


def test_showroom_delete(client, db, admin, make_portfolio):
    item = make_portfolio()
    r = client.post(f"/admin/showroom/{item.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and db.get(PortfolioItem, item.id) is None


# ── 계정 (관리자) ─────────────────────────────────────────────
def test_admin_creates_user_with_temp_password(client, db, admin):
    r = client.post(
        "/admin/users/", data={"email": "New@GoodPackage.test", "name": "최신입", "role": "sales"}
    )
    temp = re.search(r"select-all\">([^<]+)<", r.text).group(1)
    user = db.scalar(select(User).where(User.email == "new@goodpackage.test"))
    assert user.role == "sales" and auth.verify_password(user, temp)

    r = client.post("/admin/users/", data={"email": "new@goodpackage.test", "name": "x"})
    assert "이미 등록된" in r.text


def test_admin_deactivates_user_and_session_ends(client, db, admin, make_user):
    from fastapi.testclient import TestClient

    from app.main import app

    target = make_user()
    other = TestClient(app)
    login(other, target.email)
    client.post(f"/admin/users/{target.id}", data={"name": target.name, "role": "sales"})
    assert other.get("/admin/", follow_redirects=False).status_code == 303


def test_admin_cannot_demote_self(client, db, admin):
    r = client.post(
        f"/admin/users/{admin.id}", data={"name": admin.name, "role": "sales", "is_active": "y"}
    )
    assert "바꿀 수 없습니다" in r.text
    db.refresh(admin)
    assert admin.role == "admin"


def test_reset_password(client, db, admin, make_user):
    target = make_user()
    r = client.post(f"/admin/users/{target.id}/reset")
    temp = re.search(r"select-all\">([^<]+)<", r.text).group(1)
    db.refresh(target)
    assert auth.verify_password(target, temp)
