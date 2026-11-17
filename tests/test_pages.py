import pytest

PAGES = [
    ("/", None, ["제품포장은", "모든 공정을 한곳에서", "031-985-8601"]),
    ("/company/", "회사소개", ["연혁", "2010.01", "조직도", "품질관리팀", "좋은상자 제2공장"]),
    ("/process/", "제작과정", ["01.", "싸바리형", "벨벳코팅", "탈지", "KPP 파렛트"]),
    ("/facilities/", "보유장비", ["인쇄기", "RYOBI RMGT 6도 3대", "SDS 이지샘플러"]),
]


@pytest.mark.parametrize(("path", "title", "texts"), PAGES)
def test_static_page_renders(client, path, title, texts):
    res = client.get(path)
    assert res.status_code == 200
    html = res.text
    if title:
        assert f"<title>{title} | 좋은상자" in html
    for t in texts:
        assert t in html, t
    # 공통 레이아웃
    assert 'aria-label="주 메뉴"' in html
    assert "(주)좋은상자" in html


@pytest.mark.parametrize(
    ("path", "label"),
    [("/company/", "회사소개"), ("/process/", "기술소개"), ("/facilities/", "기술소개")],
)
def test_nav_marks_current_section(client, path, label):
    html = client.get(path).text
    assert f'aria-current="page">{label}</a>' in html


def test_static_images_exist(client):
    for name in ["logo", "hero", "company-bg", "process-bg", "facilities-bg", "fac-printer"]:
        assert client.get(f"/static/img/{name}.webp").status_code == 200, name


def test_recent_inquiries_partial(client):
    res = client.get("/partials/recent-inquiries", headers={"HX-Request": "true"})
    assert res.status_code == 200
    assert "<html" not in res.text  # 조각만 반환
