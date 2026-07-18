from marketplace.extensions import db
from marketplace.models import User

from .conftest import TEST_PASSWORD, login_as


def test_registration_hashes_password_and_starts_with_one_million(client, app):
    response = client.post(
        "/register",
        data={"username": "new_member", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username="new_member").one()
        assert user.password_hash != TEST_PASSWORD
        assert user.password_hash.startswith("$argon2id$")
        assert user.balance_krw == 1_000_000


def test_registration_rejects_weak_password(client):
    response = client.post(
        "/register", data={"username": "member", "password": "password"}
    )
    assert response.status_code == 400


def test_security_headers_are_set(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


def test_admin_route_rejects_regular_user(client, users):
    login_as(client, users["buyer"])
    assert client.get("/admin").status_code == 403


def test_profile_output_escapes_xss(client, app, users):
    with app.app_context():
        user = db.session.get(User, users["buyer"])
        user.bio = "<script>alert(1)</script>"
        db.session.commit()
    login_as(client, users["seller"])
    response = client.get(f"/users/{users['buyer']}")
    assert b"<script>" not in response.data
    assert b"&lt;script&gt;" in response.data
