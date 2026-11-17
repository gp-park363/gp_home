def test_home_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "좋은상자" in res.text
    assert "/static/js/htmx.min.js" in res.text


def test_healthz_checks_db(client):
    res = client.get("/healthz")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "ok"}


def test_cf_connecting_ip_is_trusted():
    from starlette.requests import Request

    from app.templating import client_ip

    req = Request(
        {
            "type": "http",
            "headers": [(b"cf-connecting-ip", b"1.2.3.4")],
            "client": ("10.0.0.1", 1),
        }
    )
    assert client_ip(req) == "1.2.3.4"
