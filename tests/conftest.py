"""모든 자동 테스트가 함께 사용할 임시 앱, DB, 사용자, 상품 준비 함수를 정의한다"""

import pytest

from marketplace import create_app
from marketplace.extensions import db
from marketplace.models import Product, User
from marketplace.security import hash_password, nickname_key, normalize_login_id


# 테스트에서만 사용하는 고정 비밀번호로 실제 서비스 계정과는 관계가 없다
TEST_PASSWORD = "Secure!Pass123"


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """실제 DB와 업로드를 건드리지 않는 세션 범위 테스트 앱을 만든다"""
    test_root = tmp_path_factory.mktemp("secure-coding-tests")
    database_path = test_root / "test.db"
    upload_path = test_root / "uploads"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-that-is-long-enough-123456",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "UPLOAD_FOLDER": str(upload_path),
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "SESSION_COOKIE_SECURE": False,
        }
    )
    return application


@pytest.fixture(autouse=True)
def clean_database(app):
    """각 테스트 전후에 테이블을 새로 만들어 테스트끼리 데이터가 섞이지 않게 한다"""
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """브라우저 요청을 흉내 낼 Flask 테스트 클라이언트를 반환한다"""
    return app.test_client()


@pytest.fixture()
def users(app):
    """판매자, 구매자, 신고자 두 명, 관리자를 만들고 각 UUID를 반환한다"""
    with app.app_context():
        seller = User(
            login_id="seller",
            login_id_normalized=normalize_login_id("seller"),
            nickname="판매자",
            nickname_normalized=nickname_key("판매자"),
            password_hash=hash_password(TEST_PASSWORD),
        )
        buyer = User(
            login_id="buyer",
            login_id_normalized=normalize_login_id("buyer"),
            nickname="구매자",
            nickname_normalized=nickname_key("구매자"),
            password_hash=hash_password(TEST_PASSWORD),
        )
        reporter1 = User(
            login_id="reporter1",
            login_id_normalized=normalize_login_id("reporter1"),
            nickname="신고자1",
            nickname_normalized=nickname_key("신고자1"),
            password_hash=hash_password(TEST_PASSWORD),
        )
        reporter2 = User(
            login_id="reporter2",
            login_id_normalized=normalize_login_id("reporter2"),
            nickname="신고자2",
            nickname_normalized=nickname_key("신고자2"),
            password_hash=hash_password(TEST_PASSWORD),
        )
        admin = User(
            login_id="administrator",
            login_id_normalized=normalize_login_id("administrator"),
            nickname="관리자",
            nickname_normalized=nickname_key("관리자"),
            password_hash=hash_password(TEST_PASSWORD),
            role="admin",
        )
        db.session.add_all([seller, buyer, reporter1, reporter2, admin])
        db.session.commit()
        return {
            "seller": seller.id,
            "buyer": buyer.id,
            "reporter1": reporter1.id,
            "reporter2": reporter2.id,
            "admin": admin.id,
        }


@pytest.fixture()
def product(app, users):
    """구매와 권한 테스트에 사용할 판매 중 상품 하나를 만든다"""
    with app.app_context():
        item = Product(
            title="테스트 노트북",
            description="정상 작동하는 중고 노트북입니다.",
            price_krw=300_000,
            seller_id=users["seller"],
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def login_as(client, user_id):
    """기존 세션을 로그아웃한 뒤 지정한 테스트 사용자로 로그인한다"""
    client.post("/logout")
    with client.application.app_context():
        login_id = db.session.get(User, user_id).login_id
    response = client.post(
        "/login", data={"login_id": login_id, "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
