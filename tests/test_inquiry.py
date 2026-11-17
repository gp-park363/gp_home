import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.models import Inquiry
from app.services import inquiry as service
from app.services import inquiry_form as form
from app.services import mold_match, turnstile

HX = {"HX-Request": "true"}

VALID = {
    "box_type": "lid",
    "width": "120",
    "depth": "80",
    "height": "40",
    "material": "CCP",
    "weight": "350g",
    "printing": "4도인쇄",
    "title": "화장품 단상자 제작 문의",
    "content": "3,000개 제작 예정입니다.",
    "quantity": "3,000개",
    "budget": "200만원",
    "company": "테스트상사",
    "name": "홍길동",
    "phone": "01012345678",
    "email": "Buyer@Example.com",
    "position": "과장",
    "delivery_location": "경기 김포시",
    "agree": "y",
}


def submit(client, data=None, files=None, headers=None):
    return client.post(
        "/inquiry/", data={**VALID, **(data or {})}, files=files or [], headers=headers or {}
    )


# ── 검증 규칙 ─────────────────────────────────────────────────
def test_validate_ok_and_normalizes():
    clean, errors = form.validate(VALID)
    assert errors == {}
    assert clean["phone"] == "010-1234-5678"
    assert clean["email"] == "buyer@example.com"
    assert clean["width"] == 120
    assert clean["agree"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title", "", "요청 제목을 입력해 주세요."),
        ("phone", "12345", "연락처"),
        ("email", "nope", "이메일 주소"),
        ("width", "abc", "1~3000"),
        ("width", "0", "1~3000"),
        ("material", "골판지", "종이재질을 목록에서"),
        ("box_type", "zzz", "박스형태"),
        ("agree", "", "동의"),
    ],
)
def test_validate_errors(field, value, message):
    _, errors = form.validate({**VALID, field: value})
    assert message in errors[field]


def test_weight_depends_on_material():
    _, errors = form.validate({**VALID, "material": "아트지", "weight": "400g"})
    assert "weight" in errors
    _, errors = form.validate({**VALID, "material": "아트지", "weight": "선택안함"})
    assert "weight" not in errors


def test_seoul_phone_format():
    clean, _ = form.validate({**VALID, "phone": "02-123-4567"})
    assert clean["phone"] == "02-123-4567"


def test_optional_specs_can_be_empty():
    data = {k: v for k, v in VALID.items() if form.FIELD_MAP[k].step != 1}
    clean, errors = form.validate(data)
    assert errors == {}
    assert clean["box_type"] is None and clean["width"] is None


# ── 목형 추천 ─────────────────────────────────────────────────
def test_mold_match_tolerance_and_order(db, make_mold):
    exact = make_mold(width=120, depth=80, height=40)
    near = make_mold(width=125, depth=78, height=43)
    make_mold(width=150, depth=80, height=40)  # 가로 30mm 차이 → 제외
    make_mold(box_type="b", width=120, depth=80, height=40)  # 다른 형태
    make_mold(width=120, depth=80, height=40, is_active=False)  # 사용 안 함

    matches = mold_match.find_similar(db, "lid", 120, 80, 40)
    assert [m.mold.id for m in matches] == [exact.id, near.id]
    assert matches[0].exact and matches[1].diffs == (5, -2, 3)

    # 형태를 고르지 않으면 형태와 무관하게 찾습니다
    assert len(mold_match.find_similar(db, None, 120, 80, 40)) == 3


def test_tolerance_scales_with_size():
    assert mold_match.tolerance(50) == 10
    assert mold_match.tolerance(400) == 40


def test_molds_fragment(client, make_mold):
    make_mold(width=120, depth=80, height=40, code="M-1")
    r = client.get("/inquiry/molds", params={"box_type": "lid", "width": "120"})
    assert "모두 입력하면" in r.text
    r = client.get(
        "/inquiry/molds",
        params={"box_type": "lid", "width": "121", "depth": "80", "height": "40"},
    )
    assert "M-1" in r.text and 'name="mold_id"' in r.text
    r = client.get(
        "/inquiry/molds", params={"box_type": "b", "width": "121", "depth": "80", "height": "40"}
    )
    assert "보유 목형이 없습니다" in r.text


# ── 화면·htmx 조각 ────────────────────────────────────────────
def test_form_page(client, make_portfolio):
    make_portfolio(box_type="sabari", thumb_path="portfolio/x.webp")
    r = client.get("/inquiry/")
    assert r.status_code == 200
    assert "<title>견적문의 | " in r.text
    assert r.text.count('name="box_type"') == 12
    assert "/media/portfolio/x.webp" in r.text  # 싸바리형 카드 사진
    assert "cf-turnstile" in r.text


def test_form_prefill_from_portfolio(client, make_portfolio):
    item = make_portfolio(name="홍삼 선물상자", code="GP9", box_type="cover", material="아트지")
    r = client.get(f"/inquiry/?portfolio={item.id}")
    assert 'value="cover" checked' in r.text.replace('class="mold-key peer sr-only" ', "")
    assert "[참고 사례] 홍삼 선물상자(GP9)" in r.text
    assert f'name="portfolio_item_id" value="{item.id}"' in r.text


def test_field_validation_fragment(client):
    r = client.post(
        "/inquiry/validate", data={"email": "bad"}, headers={**HX, "HX-Trigger-Name": "email"}
    )
    assert 'id="err-email"' in r.text and "형식" in r.text
    r = client.post(
        "/inquiry/validate",
        data={"email": "a@b.co"},
        headers={**HX, "HX-Trigger-Name": "email"},
    )
    assert re.search(r'id="err-email"[^>]*></p>', r.text)


def test_step_validation(client):
    r = client.post("/inquiry/step/1", data={"width": "x"}, headers=HX)
    assert '"inquiry-invalid"' in r.headers["HX-Trigger"]
    assert 'id="err-width" class="field-err' in r.text and 'hx-swap-oob="true"' in r.text

    r = client.post("/inquiry/step/2", data={"title": "제목"}, headers=HX)
    assert r.headers["HX-Trigger"] == '{"inquiry-step": {"step": 3}}'


def test_weight_options_fragment(client):
    r = client.get("/inquiry/weights", params={"material": "아트지"})
    assert "150g" in r.text and "400g" not in r.text
    r = client.get("/inquiry/weights", params={"material": ""})
    assert "disabled" in r.text


# ── 접수 ──────────────────────────────────────────────────────
def test_submit_creates_inquiry(client, db, outbox, make_mold, _media_tmp):
    mold = make_mold()
    files = [
        ("files", ("디자인 시안.pdf", b"%PDF-1.4 test", "application/pdf")),
        ("files", ("photo.JPG", b"\xff\xd8 jpeg", "image/jpeg")),
    ]
    r = submit(client, {"mold_id": str(mold.id)}, files=files, headers=HX)
    assert r.status_code == 200
    assert r.headers["HX-Redirect"].startswith("/inquiry/complete?t=")

    inq = db.scalar(select(Inquiry))
    assert re.fullmatch(r"\d{6}-001", inq.number)
    assert inq.phone == "010-1234-5678" and inq.email == "buyer@example.com"
    assert inq.spec.box_type == "lid" and inq.spec.weight == "350g"
    assert inq.mold_id == mold.id and inq.privacy_agreed_at
    assert [f.original_name for f in inq.files] == ["디자인 시안.pdf", "photo.JPG"]
    for f in inq.files:
        assert (_media_tmp / "private" / f.path).read_bytes()
        assert f.path.startswith("inquiries/") and "시안" not in f.path

    # 연락처·이메일은 DB에 평문으로 남지 않습니다
    raw = db.execute(text("SELECT phone, email FROM inquiries")).one()
    assert "010" not in raw.phone and "example" not in raw.email

    # 고객 확인 메일 + 담당자 알림
    subjects = [m["Subject"] for m in outbox]
    assert any(inq.number in s and "접수되었습니다" in s for s in subjects)
    customer = next(m for m in outbox if m["To"] == "buyer@example.com")
    assert "맞뚜껑형" in customer.get_content() and "&" not in customer["Subject"]

    # 접수 완료 화면
    page = client.get(r.headers["HX-Redirect"])
    assert inq.number in page.text and "bu***@example.com" in page.text


def test_staff_mail_when_configured(client, outbox, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "staff_notify_emails", ["sales@example.com"])
    submit(client, {"title": "R&D 샘플 박스"}, headers=HX)
    staff = next(m for m in outbox if m["To"] == "sales@example.com")
    assert staff["Reply-To"] == "buyer@example.com"
    body = staff.get_content()
    assert "R&D 샘플 박스" in body and "010-1234-5678" in body


def test_submit_errors_go_back_to_step(client, db):
    r = submit(client, {"title": "", "email": "x"}, headers=HX)
    assert r.headers["HX-Trigger"] == '{"inquiry-invalid": {"step": 2}}'
    assert "요청 제목을 입력해 주세요." in r.text and "이메일 주소 형식" in r.text
    assert db.scalar(select(Inquiry)) is None


def test_submit_without_htmx_rerenders(client):
    r = submit(client, {"company": ""})
    assert r.status_code == 422
    assert "업체명을 입력해 주세요." in r.text
    assert 'value="테스트상사"' not in r.text and 'value="홍길동"' in r.text


def test_submit_without_htmx_redirects(client):
    r = client.post("/inquiry/", data=VALID, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/inquiry/complete")


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ([("files", (f"{i}.png", b"x", "image/png")) for i in range(6)], "최대 5개"),
        ([("files", ("big.pdf", b"0" * (form.MAX_FILE_SIZE + 1), "application/pdf"))], "9MB"),
        ([("files", ("run.exe", b"MZ", "application/octet-stream"))], "형식"),
    ],
)
def test_file_limits(client, db, files, message):
    r = submit(client, files=files, headers=HX)
    assert message in r.text
    assert '"step": 2' in r.headers["HX-Trigger"]
    assert db.scalar(select(Inquiry)) is None


def test_five_files_of_9mb_accepted(client, db):
    blob = b"0" * form.MAX_FILE_SIZE
    files = [("files", (f"{i}.pdf", blob, "application/pdf")) for i in range(5)]
    r = submit(client, files=files, headers=HX)
    assert "HX-Redirect" in r.headers
    assert len(db.scalar(select(Inquiry)).files) == 5


def test_turnstile_failure(client, db, monkeypatch):
    monkeypatch.setattr(turnstile, "verify", lambda token, ip="": False)
    r = submit(client, headers=HX)
    assert "자동 등록 방지" in r.text
    assert db.scalar(select(Inquiry)) is None


def test_honeypot(client, db):
    r = submit(client, {"homepage": "http://spam"}, headers=HX)
    assert "접수할 수 없습니다" in r.text
    assert db.scalar(select(Inquiry)) is None


def test_unknown_mold_rejected(client):
    r = submit(client, {"mold_id": "999999"}, headers=HX)
    assert "목형을 찾을 수 없습니다" in r.text


def test_number_sequence_per_day(db):
    now = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)  # 한국 시간 18일 00시
    first = service.next_number(db, now)
    assert first == "261118-001"
    db.add(Inquiry(number=first, company="a", name="b", phone="1", email="e", title="t"))
    db.flush()
    assert service.next_number(db, now) == "261118-002"


def test_complete_token_rejects_tampering(client):
    r = client.get("/inquiry/complete?t=forged", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/inquiry/"


def test_recent_inquiries_widget(client):
    submit(client, {"title": "최근 문의 제목"}, headers=HX)
    r = client.get("/partials/recent-inquiries")
    assert "최근 문의 제목" in r.text and ">N<" in r.text
    assert "홍길동" not in r.text  # 제목·날짜 외에는 노출하지 않습니다
