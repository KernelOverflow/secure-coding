import io
import time
import uuid

from PIL import Image

from marketplace.extensions import db
from marketplace.models import MoneyTransaction, Product, User

from .conftest import TEST_PASSWORD, login_as


def test_csrf_rejects_state_change_without_token(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            "/register", data={"username": "csrf_user", "password": TEST_PASSWORD}
        )
        assert response.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_five_failed_logins_temporarily_lock_account(client, app, users):
    with app.app_context():
        username = db.session.get(User, users["buyer"]).username
    for _ in range(5):
        response = client.post(
            "/login", data={"username": username, "password": "Wrong!Pass123"}
        )
        assert response.status_code == 401
    with app.app_context():
        assert db.session.get(User, users["buyer"]).locked_until is not None


def test_disguised_image_upload_is_rejected(client, users):
    login_as(client, users["seller"])
    response = client.post(
        "/products/new",
        data={
            "title": "위장 파일",
            "description": "이미지가 아닌 파일을 업로드합니다.",
            "price": "10000",
            "image": (io.BytesIO(b"not-an-image"), "attack.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_valid_image_is_reencoded_with_random_filename(client, app, users):
    source = io.BytesIO()
    Image.new("RGB", (20, 20), color="green").save(source, format="JPEG", comment=b"metadata")
    source.seek(0)
    login_as(client, users["seller"])
    response = client.post(
        "/products/new",
        data={
            "title": "안전한 이미지",
            "description": "정상적인 상품 이미지입니다.",
            "price": "10000",
            "image": (source, "../../original.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(title="안전한 이미지").one()
        assert product.image_filename.endswith(".jpg")
        assert "original" not in product.image_filename


def test_three_distinct_reports_suspend_user(client, app, users):
    target = users["seller"]
    for reporter, reason in [
        (users["buyer"], "반복적으로 허위 상품을 등록했습니다."),
        (users["reporter1"], "대화에서 사기 거래를 유도했습니다."),
        (users["reporter2"], "여러 상품의 내용이 실제와 다릅니다."),
    ]:
        login_as(client, reporter)
        client.post(
            "/reports/new",
            data={"target_type": "user", "target_id": target, "reason": reason},
        )
    with app.app_context():
        assert db.session.get(User, target).status == "suspended"


def test_admin_reversal_records_new_adjustment(client, app, users):
    login_as(client, users["buyer"])
    client.post(
        f"/users/{users['seller']}/transfer",
        data={
            "amount": "50000",
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
            "note": "정정 예정 거래",
        },
    )
    with app.app_context():
        original_id = MoneyTransaction.query.filter_by(kind="transfer").one().id
    login_as(client, users["admin"])
    response = client.post(
        f"/admin/transactions/{original_id}/reverse",
        data={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "사용자의 오송금 신고를 확인하여 정정합니다.",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, users["buyer"]).balance_krw == 1_000_000
        assert db.session.get(User, users["seller"]).balance_krw == 1_000_000
        assert MoneyTransaction.query.filter_by(kind="adjustment", reference_id=original_id).count() == 1


def test_only_one_buyer_can_claim_product(client, app, users, product):
    for buyer_id in [users["buyer"], users["reporter1"]]:
        login_as(client, buyer_id)
        client.post(
            f"/products/{product}/purchase",
            data={
                "idempotency_key": str(uuid.uuid4()),
                "current_password": TEST_PASSWORD,
            },
        )
    with app.app_context():
        assert MoneyTransaction.query.filter_by(kind="purchase").count() == 1
        assert db.session.get(Product, product).status == "sold"


def test_search_of_one_thousand_products_completes_under_one_second(client, app, users):
    with app.app_context():
        db.session.bulk_save_objects(
            [
                Product(
                    title=f"성능 테스트 상품 {index}",
                    description="검색 성능 검증용 상품입니다.",
                    price_krw=10_000 + index,
                    seller_id=users["seller"],
                )
                for index in range(1000)
            ]
        )
        db.session.commit()
    started = time.perf_counter()
    response = client.get("/products?q=성능+테스트&min_price=10000&max_price=20000")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 1.0
