"""CSRF, 로그인 잠금, 이미지, 신고, 거래 정정, 동시 구매와 검색 성능을 검증한다"""

import io
import time
import uuid
from pathlib import Path

from PIL import Image

from marketplace.extensions import db
from marketplace.models import MoneyTransaction, Product, User

from .conftest import TEST_PASSWORD, login_as


def test_csrf_rejects_state_change_without_token(client, app):
    """CSRF 토큰 없이 상태를 바꾸는 POST 요청이 400으로 거부되는지 확인한다"""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            "/register",
            data={
                "nickname": "CSRF 회원",
                "login_id": "csrf_user",
                "password": TEST_PASSWORD,
            },
        )
        assert response.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_five_failed_logins_temporarily_lock_account(client, app, users):
    """같은 계정의 로그인 실패가 다섯 번 쌓이면 임시 잠금되는지 확인한다"""
    with app.app_context():
        login_id = db.session.get(User, users["buyer"]).login_id
    for _ in range(5):
        response = client.post(
            "/login", data={"login_id": login_id, "password": "Wrong!Pass123"}
        )
        assert response.status_code == 401
    with app.app_context():
        assert db.session.get(User, users["buyer"]).locked_until is not None


def test_disguised_image_upload_is_rejected(client, users):
    """jpg 확장자로 위장한 일반 파일을 실제 이미지 검사에서 거부하는지 확인한다"""
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
    """정상 이미지가 UUID 파일명으로 재인코딩되고 상품 목록과 내 상품에 나오는지 확인한다"""
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
        image_filename = product.image_filename
    list_page = client.get("/products").get_data(as_text=True)
    assert f'/uploads/{image_filename}' in list_page
    assert 'class="product-card-image"' in list_page
    assert 'loading="lazy"' in list_page

    my_products_page = client.get("/products/mine").get_data(as_text=True)
    assert f'/uploads/{image_filename}' in my_products_page
    assert 'class="product-card-image"' in my_products_page
    assert 'loading="lazy"' in my_products_page


def test_profile_image_is_reencoded_displayed_and_deleted(client, app, users):
    """프로필 사진이 안전한 파일명으로 저장·공개·삭제되는지 확인한다"""
    source = io.BytesIO()
    Image.new("RGB", (40, 40), color="orange").save(source, format="PNG")
    source.seek(0)
    login_as(client, users["buyer"])
    response = client.post(
        "/profile",
        data={
            "bio": "프로필 사진을 등록했습니다.",
            "profile_image": (source, "../../my-profile.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, users["buyer"])
        image_filename = user.profile_image_filename
        assert image_filename.endswith(".png")
        assert "my-profile" not in image_filename
        image_path = app.config["UPLOAD_FOLDER"] + "/" + image_filename

    own_profile = client.get("/profile").get_data(as_text=True)
    assert f"/users/profile-images/{image_filename}" in own_profile
    assert client.get(f"/users/profile-images/{image_filename}").status_code == 200

    # 다른 회원의 공개 프로필에도 닉네임과 함께 사진이 표시되어야 한다
    login_as(client, users["seller"])
    public_profile = client.get(f"/users/{users['buyer']}").get_data(as_text=True)
    assert f"/users/profile-images/{image_filename}" in public_profile

    login_as(client, users["buyer"])
    removed = client.post(
        "/profile",
        data={"bio": "프로필 사진을 삭제했습니다.", "remove_profile_image": "1"},
    )
    assert removed.status_code == 302
    with app.app_context():
        assert db.session.get(User, users["buyer"]).profile_image_filename is None
    assert not Path(image_path).exists()
    assert client.get(f"/users/profile-images/{image_filename}").status_code == 404


def test_disguised_profile_image_is_rejected(client, app, users):
    """이미지로 위장한 프로필 파일을 거부하고 DB를 변경하지 않는지 확인한다"""
    login_as(client, users["buyer"])
    response = client.post(
        "/profile",
        data={
            "bio": "변경되면 안 됩니다.",
            "profile_image": (io.BytesIO(b"not-an-image"), "attack.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    with app.app_context():
        user = db.session.get(User, users["buyer"])
        assert user.profile_image_filename is None
        assert user.bio == ""


def test_image_allows_empty_product_description(client, app, users):
    """정상 상품 사진이 있으면 빈 설명으로도 등록할 수 있는지 확인한다"""
    source = io.BytesIO()
    Image.new("RGB", (20, 20), color="blue").save(source, format="PNG")
    source.seek(0)
    login_as(client, users["seller"])
    response = client.post(
        "/products/new",
        data={
            "title": "사진으로 설명하는 상품",
            "description": "",
            "price": "25000",
            "image": (source, "product.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(title="사진으로 설명하는 상품").one()
        assert product.description == ""
        assert product.image_filename.endswith(".png")


def test_product_requires_an_image_or_description(client, app, users):
    """사진과 설명이 모두 없는 정보 부족 상품을 저장하지 않는지 확인한다"""
    login_as(client, users["seller"])
    response = client.post(
        "/products/new",
        data={"title": "정보 없는 상품", "description": "", "price": "25000"},
    )
    assert response.status_code == 400
    with app.app_context():
        assert Product.query.filter_by(title="정보 없는 상품").count() == 0


def test_three_distinct_reports_suspend_user(client, app, users):
    """서로 다른 세 명이 사용자를 신고하면 일반 계정이 임시 정지되는지 확인한다"""
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
    """관리자 정정이 원본 삭제 대신 반대 방향 adjustment 거래를 만드는지 확인한다"""
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
    """두 구매자가 동시에 요청해도 한 명만 상품을 선점하고 결제하는지 확인한다"""
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
    """상품 1,000개 환경의 검색 응답이 목표 시간 1초 안에 끝나는지 확인한다"""
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
