"""회원가입, 인증, 공개 정보, 보안 헤더와 권한 관련 동작을 검증한다"""

import re

from flask import g

from marketplace.extensions import db
from marketplace.models import User

from .conftest import TEST_PASSWORD, login_as


def test_registration_hashes_password_and_starts_with_one_million(client, app):
    """가입 시 Argon2id 해시와 초기 잔액 100만 원이 저장되는지 확인한다"""
    response = client.post(
        "/register",
        data={
            "nickname": "새 회원",
            "login_id": "new_member",
            "password": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(login_id="new_member").one()
        assert user.nickname == "새 회원"
        assert user.password_hash != TEST_PASSWORD
        assert user.password_hash.startswith("$argon2id$")
        assert user.balance_krw == 1_000_000


def test_registration_with_real_csrf_token(client, app):
    """실제 발급된 CSRF 토큰으로 회원가입이 정상 완료되는지 확인한다"""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        page = client.get("/register")
        token_match = re.search(
            r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)
        )
        assert token_match is not None
        response = client.post(
            "/register",
            data={
                "csrf_token": token_match.group(1),
                "nickname": "CSRF 확인",
                "login_id": "csrf_member",
                "password": TEST_PASSWORD,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_registration_rejects_weak_password(client):
    """영문, 숫자, 특수문자 조건을 만족하지 않는 비밀번호를 거부하는지 확인한다"""
    response = client.post(
        "/register",
        data={"nickname": "회원", "login_id": "member", "password": "password"},
    )
    assert response.status_code == 400


def test_login_can_remember_id_and_keep_session(client, app, users):
    """아이디 기억과 로그인 상태 유지를 각각 안전한 쿠키로 처리하는지 확인한다"""
    with app.app_context():
        login_id = db.session.get(User, users["buyer"]).login_id
    response = client.post(
        "/login",
        data={
            "login_id": login_id,
            "password": TEST_PASSWORD,
            "remember_login_id": "1",
            "keep_signed_in": "1",
        },
    )
    cookies = "\n".join(response.headers.getlist("Set-Cookie"))
    assert response.status_code == 302
    assert "filemarket_login_id=buyer" in cookies
    assert "filemarket_remember=" in cookies
    assert "HttpOnly" in cookies
    assert "SameSite=Lax" in cookies

    # 30분 세션 쿠키만 없애도 remember 쿠키로 본인 프로필에 다시 접근해야 한다
    assert client.get_cookie(app.config["SESSION_COOKIE_NAME"]) is not None
    client.delete_cookie(app.config["SESSION_COOKIE_NAME"])
    assert client.get_cookie(app.config["SESSION_COOKIE_NAME"]) is None
    g.pop("_login_user", None)
    assert client.get("/profile").status_code == 200

    logout = client.post("/logout")
    cleared_cookies = "\n".join(logout.headers.getlist("Set-Cookie"))
    assert "filemarket_remember=;" in cleared_cookies

    login_page = client.get("/login").get_data(as_text=True)
    assert 'value="buyer"' in login_page
    assert 'name="remember_login_id" value="1" checked' in login_page


def test_login_without_keep_option_expires_with_session(client, app, users):
    """로그인 상태 유지를 선택하지 않으면 세션 쿠키 제거 후 다시 로그인을 요구하는지 확인한다"""
    login_as(client, users["buyer"])
    assert client.get_cookie(app.config["REMEMBER_COOKIE_NAME"]) is None
    assert client.get_cookie(app.config["SESSION_COOKIE_NAME"]) is not None
    client.delete_cookie(app.config["SESSION_COOKIE_NAME"])
    assert client.get_cookie(app.config["SESSION_COOKIE_NAME"]) is None
    g.pop("_login_user", None)
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_login_accepts_only_internal_next_url(client, users):
    """로그인 후 내부 경로로는 복귀하고 외부 주소로의 이동은 차단하는지 확인한다"""
    response = client.post(
        "/login?next=/products/example%23comments",
        data={"login_id": "buyer", "password": TEST_PASSWORD},
    )
    assert response.headers["Location"] == "/products/example#comments"

    client.post("/logout")
    blocked = client.post(
        "/login?next=https://example.com/phishing",
        data={"login_id": "buyer", "password": TEST_PASSWORD},
    )
    assert blocked.headers["Location"] == "/products"


def test_eight_character_mixed_password_is_accepted(client):
    """세 가지 문자 조건을 만족하는 정확히 8자 비밀번호를 허용하는지 확인한다"""
    response = client.post(
        "/register",
        data={"nickname": "여덟글자", "login_id": "eight_id", "password": "Abcd1!xy"},
    )
    assert response.status_code == 302


def test_duplicate_or_reserved_nickname_is_rejected(client):
    """중복, 관리자 사칭, HTML 문자가 포함된 닉네임을 거부하는지 확인한다"""
    first = client.post(
        "/register",
        data={"nickname": "안전 닉네임", "login_id": "safe_id1", "password": TEST_PASSWORD},
    )
    duplicate = client.post(
        "/register",
        data={"nickname": "안전  닉네임", "login_id": "safe_id2", "password": TEST_PASSWORD},
    )
    reserved = client.post(
        "/register",
        data={"nickname": "관리자123", "login_id": "safe_id3", "password": TEST_PASSWORD},
    )
    markup = client.post(
        "/register",
        data={"nickname": "<script>", "login_id": "safe_id4", "password": TEST_PASSWORD},
    )
    assert first.status_code == 302
    assert duplicate.status_code == 409
    assert reserved.status_code == 400
    assert markup.status_code == 400


def test_public_pages_expose_nickname_not_login_id(client, users):
    """다른 회원 화면에는 닉네임만 보이고 로그인 아이디는 숨겨지는지 확인한다"""
    login_as(client, users["seller"])
    response = client.get(f"/users/{users['buyer']}")
    assert "구매자" in response.get_data(as_text=True)
    assert "buyer" not in response.get_data(as_text=True)


def test_security_headers_are_set(client):
    """CSP, 프레임 차단, MIME 보호, 캐시 방지 헤더가 응답에 있는지 확인한다"""
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


def test_brand_opens_home_page_for_guest_and_product_list_for_authenticated_user(client, users):
    """비로그인은 소개 화면으로, 로그인 사용자는 파일마켓 로고로 상품 목록에 이동하는지 확인한다"""
    guest_response = client.get("/")
    guest_page = guest_response.get_data(as_text=True)
    assert guest_response.status_code == 200
    assert 'class="brand" href="/"' in guest_page
    assert "안전하게 연결되는" in guest_page

    login_as(client, users["buyer"])
    response = client.get("/", follow_redirects=True)
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'class="brand" href="/"' in page
    assert "상품 목록" in page
    assert "상품 등록" in page


def test_guest_can_browse_products_from_home_page(client):
    """비로그인 사용자가 메인 화면에서 공개 상품 목록으로 이동할 수 있는지 확인한다"""
    page = client.get("/").get_data(as_text=True)
    assert '<a class="button button-secondary" href="/products">상품 둘러보기</a>' in page


def test_balance_is_private_to_profile_page(client, users):
    """잔액은 공통 상품 화면에 노출되지 않고 본인 내 정보에만 보이는지 확인한다"""
    login_as(client, users["buyer"])
    products_page = client.get("/products").get_data(as_text=True)
    profile_page = client.get("/profile").get_data(as_text=True)
    assert "잔액 1,000,000원" not in products_page
    assert "현재 잔액 1,000,000원" in profile_page


def test_admin_route_rejects_regular_user(client, users):
    """일반 사용자가 관리자 URL을 직접 입력해도 403으로 거부되는지 확인한다"""
    login_as(client, users["buyer"])
    assert client.get("/admin").status_code == 403


def test_profile_output_escapes_xss(client, app, users):
    """소개글의 script 태그가 HTML로 실행되지 않고 문자로 표시되는지 확인한다"""
    with app.app_context():
        user = db.session.get(User, users["buyer"])
        user.bio = "<script>alert(1)</script>"
        db.session.commit()
    login_as(client, users["seller"])
    response = client.get(f"/users/{users['buyer']}")
    assert b"<script>" not in response.data
    assert b"&lt;script&gt;" in response.data
