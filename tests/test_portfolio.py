from app.routers.portfolio import PAGE_SIZE

HX = {"HX-Request": "true"}


def test_list_shows_published_items_only(client, make_portfolio):
    make_portfolio(name="공개 상자")
    make_portfolio(name="비공개 상자", is_published=False)
    html = client.get("/portfolio/").text
    assert "공개 상자" in html
    assert "비공개 상자" not in html
    assert "<title>쇼룸 | 좋은상자" in html


def test_filter_by_box_type_and_industry(client, make_portfolio):
    make_portfolio(name="싸바리 식품", box_type="sabari", industry="food")
    make_portfolio(name="싸바리 화장품", box_type="sabari", industry="cosmetics")
    make_portfolio(name="G형 식품", box_type="g", industry="food")

    html = client.get("/portfolio/?box_type=sabari").text
    assert "싸바리 식품" in html and "싸바리 화장품" in html and "G형 식품" not in html

    html = client.get("/portfolio/?box_type=sabari&industry=food").text
    assert "싸바리 식품" in html and "싸바리 화장품" not in html


def test_unknown_filter_value_is_ignored(client, make_portfolio):
    make_portfolio(name="아무 상자")
    res = client.get("/portfolio/?box_type=<script>")
    assert res.status_code == 200
    assert "아무 상자" in res.text
    assert "<script>" not in res.text


def test_htmx_filter_returns_fragment(client, make_portfolio):
    make_portfolio()
    html = client.get("/portfolio/?box_type=lid", headers=HX).text
    assert "<html" not in html
    assert "박스형태" in html  # 필터 영역 포함


def test_htmx_history_restore_returns_full_page(client, make_portfolio):
    make_portfolio()
    headers = {**HX, "HX-History-Restore-Request": "true"}
    assert "<html" in client.get("/portfolio/?box_type=lid", headers=headers).text


def test_infinite_scroll_pages(client, make_portfolio):
    for n in range(PAGE_SIZE + 3):
        make_portfolio(name=f"상자{n:02d}")
    first = client.get("/portfolio/").text
    assert first.count("<article") == PAGE_SIZE
    assert 'hx-trigger="revealed"' in first

    second = client.get("/portfolio/?page=2", headers=HX).text
    assert second.count("<article") == 3
    assert 'hx-trigger="revealed"' not in second  # 마지막 묶음
    assert "<html" not in second


def test_detail_shows_specs_and_quote_link(client, make_portfolio):
    item = make_portfolio(
        name="홍삼 선물상자", code="GP9999", material="아트지", description="자석으로 닫는 상자"
    )
    res = client.get(f"/portfolio/{item.id}")
    assert res.status_code == 200
    html = res.text
    for text in ["홍삼 선물상자", "GP9999", "아트지", "자석으로 닫는 상자", "맞뚜껑형", "식품"]:
        assert text in html, text
    assert f"/inquiry/?portfolio={item.id}" in html


def test_detail_hides_unpublished_and_missing(client, make_portfolio):
    hidden = make_portfolio(is_published=False)
    assert client.get(f"/portfolio/{hidden.id}").status_code == 404
    assert client.get("/portfolio/999999").status_code == 404


def test_related_items_share_box_type(client, make_portfolio):
    item = make_portfolio(name="기준", box_type="g")
    make_portfolio(name="같은형태", box_type="g")
    make_portfolio(name="다른형태", box_type="sleeve")
    html = client.get(f"/portfolio/{item.id}").text
    assert "같은형태" in html and "다른형태" not in html


def test_wp_post_url_redirects_permanently(client, make_portfolio):
    item = make_portfolio(wp_post_id=1506)
    res = client.get("/?p=1506", follow_redirects=False)
    assert res.status_code == 301
    assert res.headers["location"] == f"/portfolio/{item.id}"
    # 모르는 글 ID는 메인 화면
    assert client.get("/?p=1", follow_redirects=False).status_code == 200
