import pytest

from marketplace import create_app
from marketplace.extensions import db
from marketplace.models import Product, User
from marketplace.security import hash_password


TEST_PASSWORD = "Secure!Pass123"


@pytest.fixture(scope="session")
def app(tmp_path_factory):
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
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def users(app):
    with app.app_context():
        seller = User(username="seller", password_hash=hash_password(TEST_PASSWORD))
        buyer = User(username="buyer", password_hash=hash_password(TEST_PASSWORD))
        reporter1 = User(username="reporter1", password_hash=hash_password(TEST_PASSWORD))
        reporter2 = User(username="reporter2", password_hash=hash_password(TEST_PASSWORD))
        admin = User(
            username="administrator",
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
    client.post("/logout")
    with client.application.app_context():
        username = db.session.get(User, user_id).username
    response = client.post(
        "/login", data={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
