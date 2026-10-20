from django.test import Client


def test_health_is_public(client: Client) -> None:
    assert client.get("/health").json() == {"status": "ok", "version": "vývoj"}


def test_pages_require_login(client: Client, db: None) -> None:
    for url in ("/", "/password/", "/password/done/"):
        response = client.get(url)
        assert response.status_code == 302, url
        assert response["Location"].startswith("/login/"), url


def test_admin_requires_login(client: Client, db: None) -> None:
    response = client.get("/admin/")
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


def test_login_page_is_czech(client: Client, db: None) -> None:
    html = client.get("/login/").content.decode()
    assert '<html lang="cs">' in html and "Přihlášení" in html


def test_logged_in_user_sees_app(auth_client: Client) -> None:
    response = auth_client.get("/", follow=True)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Odhlásit" in html and "Pronájmy" in html


def test_csrf_enforced(db: None) -> None:
    strict = Client(enforce_csrf_checks=True)
    assert strict.post("/login/", {"username": "x", "password": "y"}).status_code == 403


def test_password_change(auth_client: Client) -> None:
    page = auth_client.get("/password/").content.decode()
    assert "Změna hesla" in page
    response = auth_client.post(
        "/password/",
        {
            "old_password": "tajne-heslo-123",
            "new_password1": "Nove-Heslo-456",
            "new_password2": "Nove-Heslo-456",
        },
    )
    assert response["Location"] == "/password/done/"
    assert Client().login(username="pronajmy", password="Nove-Heslo-456")
    weak = auth_client.post(
        "/password/",
        {
            "old_password": "Nove-Heslo-456",
            "new_password1": "12345678",
            "new_password2": "12345678",
        },
    ).content.decode()
    assert "aria-invalid" in weak


def test_bad_host_shows_czech_hint(settings: object) -> None:
    settings.DEBUG = False  # type: ignore[attr-defined]
    settings.ALLOWED_HOSTS = ["192.168.88.108"]  # type: ignore[attr-defined]
    client = Client(raise_request_exception=False)
    response = client.get("/login/", HTTP_HOST="192.168.1.50:8080")
    assert response.status_code == 400
    assert "PRONAJMY_URL" in response.content.decode()
