"""상품 소유권, 구매 원자성, 직접 송금, 중복 처리와 가격 변조 방어를 검증한다"""

import uuid

from marketplace.extensions import db
from marketplace.models import MoneyTransaction, Product, ProductComment, Purchase, User

from .conftest import TEST_PASSWORD, login_as


def test_only_owner_can_edit_product(client, users, product):
    """구매자가 판매자 상품 수정 URL에 접근하면 403인지 확인한다"""
    login_as(client, users["buyer"])
    assert client.get(f"/products/{product}/edit").status_code == 403


def test_product_status_uses_same_korean_label_on_user_pages(client, users, product):
    """상품 목록, 상세, 내 상품에서 내부 상태 active 대신 판매 중을 표시하는지 확인한다"""
    login_as(client, users["seller"])
    for path in ("/products", f"/products/{product}", "/products/mine"):
        page = client.get(path).get_data(as_text=True)
        assert "판매 중" in page
        assert ">active<" not in page


def test_product_status_button_and_badge_follow_current_status(client, users, product):
    """판매 상태에 따라 변경 버튼과 배지의 색상 클래스가 함께 바뀐는지 확인한다"""
    login_as(client, users["seller"])

    active_page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'class="status status-active">판매 중</span>' in active_page
    assert 'class="button button-muted" type="submit">판매 완료로 변경' in active_page
    active_mine_page = client.get("/products/mine").get_data(as_text=True)
    assert 'class="button button-muted" type="submit">판매 완료로 변경' in active_mine_page
    assert 'class="button button-secondary"' in active_mine_page
    assert '>수정</a>' in active_mine_page
    assert 'class="button button-danger" type="submit">삭제' in active_mine_page

    response = client.post(f"/products/{product}/status", data={"status": "sold"})
    assert response.status_code == 302

    # 판매 완료는 판매자에게 되돌릴 수 없는 상태이므로 상태 전환 버튼이 더 이상 보이지 않는다
    sold_page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'class="status status-sold">판매 완료</span>' in sold_page
    assert "판매 중으로 변경" not in sold_page
    sold_mine_page = client.get("/products/mine").get_data(as_text=True)
    assert "판매 중으로 변경" not in sold_mine_page

    # 되돌리려는 시도 자체도 서버에서 거부한다
    reverse_attempt = client.post(f"/products/{product}/status", data={"status": "active"})
    assert reverse_attempt.status_code == 403

    # 관리자는 돈이 오가지 않는 상태 표시를 양방향으로 바로잡을 수 있다
    login_as(client, users["admin"])
    admin_sold_page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'class="button button-secondary" type="submit">판매 중으로 변경' in admin_sold_page
    admin_response = client.post(f"/products/{product}/status", data={"status": "active"})
    assert admin_response.status_code == 302
    reactivated_page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'class="status status-active">판매 중</span>' in reactivated_page


def test_guest_sees_disabled_comment_form_and_login_link(client, app, product):
    """비로그인 사용자에게 댓글 폼을 비활성화하고 로그인 링크를 제공하는지 확인한다"""
    page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'id="comment-content-disabled"' in page
    assert "disabled" in page
    assert "로그인 후 댓글을 작성할 수 있습니다" in page
    assert f"/login?next=/products/{product}%23comments" in page

    response = client.post(
        f"/products/{product}/comments", data={"content": "익명 댓글"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    with app.app_context():
        assert ProductComment.query.count() == 0


def test_logged_in_user_can_comment_and_output_is_escaped(client, app, users, product):
    """로그인 회원의 댓글을 저장하고 HTML은 실행되지 않게 출력하는지 확인한다"""
    login_as(client, users["buyer"])
    response = client.post(
        f"/products/{product}/comments",
        data={"content": "<script>alert(1)</script> 상품 문의"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("#comments")
    with app.app_context():
        comment = ProductComment.query.one()
        assert comment.author_id == users["buyer"]

    client.post("/logout")
    page = client.get(f"/products/{product}")
    assert b"<script>" not in page.data
    assert b"&lt;script&gt;" in page.data


def test_only_comment_author_or_admin_can_delete_comment(client, app, users, product):
    """상품 판매자는 타인의 댓글을 지울 수 없고 작성자와 관리자는 삭제할 수 있는지 확인한다"""
    with app.app_context():
        comment = ProductComment(
            product_id=product,
            author_id=users["buyer"],
            content="작성자만 삭제할 수 있는 댓글",
        )
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id

    login_as(client, users["seller"])
    denied = client.post(f"/products/{product}/comments/{comment_id}/delete")
    assert denied.status_code == 403

    login_as(client, users["buyer"])
    comment_page = client.get(f"/products/{product}").get_data(as_text=True)
    assert 'data-confirm-message="댓글을 삭제하면 복구할 수 없습니다."' in comment_page
    deleted = client.post(f"/products/{product}/comments/{comment_id}/delete")
    assert deleted.status_code == 302
    with app.app_context():
        assert db.session.get(ProductComment, comment_id).status == "deleted"

        admin_target = ProductComment(
            product_id=product,
            author_id=users["buyer"],
            content="관리자가 삭제할 수 있는 댓글",
        )
        db.session.add(admin_target)
        db.session.commit()
        admin_target_id = admin_target.id

    login_as(client, users["admin"])
    admin_deleted = client.post(
        f"/products/{product}/comments/{admin_target_id}/delete"
    )
    assert admin_deleted.status_code == 302
    with app.app_context():
        assert db.session.get(ProductComment, admin_target_id).status == "deleted"


def test_purchase_moves_balance_and_marks_product_sold(client, app, users, product):
    """구매 후 양쪽 잔액, 판매 상태, 구매와 거래 기록이 함께 바뀌는지 확인한다"""
    login_as(client, users["buyer"])
    key = str(uuid.uuid4())
    response = client.post(
        f"/products/{product}/purchase",
        data={"idempotency_key": key, "current_password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    with app.app_context():
        buyer = db.session.get(User, users["buyer"])
        seller = db.session.get(User, users["seller"])
        item = db.session.get(Product, product)
        assert buyer.balance_krw == 700_000
        assert seller.balance_krw == 1_300_000
        assert item.status == "sold"
        assert Purchase.query.filter_by(product_id=product).count() == 1
        assert MoneyTransaction.query.filter_by(idempotency_key=key).count() == 1


def test_duplicate_purchase_key_does_not_charge_twice(client, app, users, product):
    """같은 구매 키를 다시 보내도 구매자 잔액이 한 번만 차감되는지 확인한다"""
    login_as(client, users["buyer"])
    key = str(uuid.uuid4())
    data = {"idempotency_key": key, "current_password": TEST_PASSWORD}
    client.post(f"/products/{product}/purchase", data=data)
    client.post(f"/products/{product}/purchase", data=data)
    with app.app_context():
        buyer = db.session.get(User, users["buyer"])
        assert buyer.balance_krw == 700_000
        assert MoneyTransaction.query.filter_by(idempotency_key=key).count() == 1


def test_direct_transfer_rejects_negative_and_moves_valid_amount(client, app, users):
    """음수 송금은 거부하고 정상 송금은 양쪽 잔액에 정확히 반영되는지 확인한다"""
    login_as(client, users["buyer"])
    invalid = client.post(
        f"/users/{users['seller']}/transfer",
        data={
            "amount": "-1",
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
        },
    )
    assert invalid.status_code == 302
    client.post(
        f"/users/{users['seller']}/transfer",
        data={
            "amount": "50000",
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
            "note": "거래 대금",
        },
    )
    with app.app_context():
        assert db.session.get(User, users["buyer"]).balance_krw == 950_000
        assert db.session.get(User, users["seller"]).balance_krw == 1_050_000


def test_server_uses_database_price_not_submitted_price(client, app, users, product):
    """폼 가격을 1원으로 바꿔도 서버가 DB 상품 가격으로 결제하는지 확인한다"""
    login_as(client, users["buyer"])
    client.post(
        f"/products/{product}/purchase",
        data={
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
            "price": "1",
        },
    )
    with app.app_context():
        assert db.session.get(User, users["buyer"]).balance_krw == 700_000
