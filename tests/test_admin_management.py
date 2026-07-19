"""관리자가 플랫폼의 회원 콘텐츠, 댓글, 채팅, 구매와 전체 목록을 관리하는지 검증한다"""

import uuid
from pathlib import Path

from marketplace.extensions import db
from marketplace.models import (
    AuditLog,
    Conversation,
    Message,
    Product,
    ProductComment,
    Purchase,
    User,
)

from .conftest import TEST_PASSWORD, login_as


def test_admin_can_open_every_management_section(client, users):
    """관리자가 플랫폼 구성 요소별 관리 화면을 빠짐없이 열 수 있는지 확인한다"""
    login_as(client, users["admin"])
    for path in (
        "/admin",
        "/admin/users",
        "/admin/products",
        "/admin/comments",
        "/admin/reports",
        "/admin/purchases",
        "/admin/transactions",
        "/admin/conversations",
        "/admin/messages",
        "/admin/audit-logs",
    ):
        assert client.get(path).status_code == 200, path


def test_admin_hides_and_restores_product_comment(client, app, users, product):
    """일반 사용자는 댓글 관리가 불가능하고 관리자는 사유와 함께 숨김·복구하는지 확인한다"""
    with app.app_context():
        comment = ProductComment(
            product_id=product,
            author_id=users["buyer"],
            content="관리자 검토가 필요한 공개 댓글",
        )
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id

    login_as(client, users["seller"])
    denied = client.post(
        f"/admin/comments/{comment_id}/status",
        data={"status": "deleted", "reason": "권한 없는 관리 요청입니다"},
    )
    assert denied.status_code == 403

    login_as(client, users["admin"])
    hidden = client.post(
        f"/admin/comments/{comment_id}/status",
        data={"status": "deleted", "reason": "개인정보 노출 내용을 확인했습니다"},
    )
    assert hidden.status_code == 302
    with app.app_context():
        assert db.session.get(ProductComment, comment_id).status == "deleted"
        assert AuditLog.query.filter_by(
            action="admin.comment_status", target_id=comment_id
        ).count() == 1
    assert "관리자 검토가 필요한 공개 댓글" not in client.get(
        f"/products/{product}"
    ).get_data(as_text=True)

    restored = client.post(
        f"/admin/comments/{comment_id}/status",
        data={"status": "active", "reason": "검토 결과 공개 가능한 댓글입니다"},
    )
    assert restored.status_code == 302
    assert "관리자 검토가 필요한 공개 댓글" in client.get(
        f"/products/{product}"
    ).get_data(as_text=True)


def test_admin_hides_chat_message_but_preserves_original(client, app, users, product):
    """관리자가 채팅 원문을 삭제하지 않고 참여자 화면에서만 숨기는지 확인한다"""
    with app.app_context():
        conversation = Conversation(
            product_id=product,
            buyer_id=users["buyer"],
            seller_id=users["seller"],
        )
        db.session.add(conversation)
        db.session.flush()
        message = Message(
            conversation_id=conversation.id,
            sender_id=users["buyer"],
            content="관리자가 숨길 채팅 메시지",
        )
        db.session.add(message)
        db.session.commit()
        conversation_id = conversation.id
        message_id = message.id

    login_as(client, users["admin"])
    response = client.post(
        f"/admin/messages/{message_id}/status",
        data={"status": "deleted", "reason": "개인정보가 포함된 메시지입니다"},
    )
    assert response.status_code == 302
    with app.app_context():
        stored = db.session.get(Message, message_id)
        assert stored.content == "관리자가 숨길 채팅 메시지"
        assert stored.status == "deleted"
        assert AuditLog.query.filter_by(
            action="admin.message_status", target_id=message_id
        ).count() == 1

    login_as(client, users["buyer"])
    conversation_page = client.get(f"/conversations/{conversation_id}").get_data(
        as_text=True
    )
    assert "관리자가 숨길 채팅 메시지" not in conversation_page

    login_as(client, users["admin"])
    admin_page = client.get(
        f"/admin/messages?conversation_id={conversation_id}"
    ).get_data(as_text=True)
    assert "관리자가 숨길 채팅 메시지" in admin_page
    assert "숨김" in admin_page


def test_admin_resets_profile_content_and_removes_image_file(client, app, users):
    """관리자가 소개글과 프로필 사진 연결 및 실제 파일을 함께 초기화하는지 확인한다"""
    image_filename = f"{uuid.uuid4()}.jpg"
    with app.app_context():
        user = db.session.get(User, users["seller"])
        user.bio = "관리자가 초기화할 소개글"
        user.profile_image_filename = image_filename
        image_path = Path(app.config["UPLOAD_FOLDER"]) / image_filename
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"temporary-profile-image")
        db.session.commit()

    login_as(client, users["admin"])
    response = client.post(
        f"/admin/users/{users['seller']}/profile/reset",
        data={
            "reset_bio": "1",
            "reset_image": "1",
            "reason": "부적절한 프로필 콘텐츠를 확인했습니다",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        user = db.session.get(User, users["seller"])
        assert user.bio == ""
        assert user.profile_image_filename is None
        assert not (Path(app.config["UPLOAD_FOLDER"]) / image_filename).exists()
        assert AuditLog.query.filter_by(
            action="admin.user_profile_reset", target_id=users["seller"]
        ).count() == 1


def test_admin_can_review_purchase_linked_to_transaction(client, app, users, product):
    """관리자가 구매 상품, 참여자, 금액과 연결 거래를 별도 구매 화면에서 확인하는지 검사한다"""
    login_as(client, users["buyer"])
    purchase_response = client.post(
        f"/products/{product}/purchase",
        data={
            "idempotency_key": str(uuid.uuid4()),
            "current_password": TEST_PASSWORD,
        },
    )
    assert purchase_response.status_code == 302

    login_as(client, users["admin"])
    page = client.get("/admin/purchases").get_data(as_text=True)
    assert "테스트 노트북" in page
    assert "구매자" in page
    assert "판매자" in page
    assert "300,000원" in page
    with app.app_context():
        transaction_id = Purchase.query.one().transaction_id
    assert transaction_id in page


def test_admin_product_pagination_reaches_rows_after_first_fifty(
    client, app, users, product
):
    """관리 목록이 500개에서 잘리지 않고 페이지 이동으로 모든 상품에 접근되는지 확인한다"""
    with app.app_context():
        db.session.bulk_save_objects(
            [
                Product(
                    title=f"관리 페이지 상품 {index:02d}",
                    description="관리자 페이지 이동 검증용 상품입니다",
                    price_krw=10_000 + index,
                    seller_id=users["seller"],
                )
                for index in range(51)
            ]
        )
        db.session.commit()

    login_as(client, users["admin"])
    first_page = client.get("/admin/products").get_data(as_text=True)
    second_page = client.get("/admin/products?page=2").get_data(as_text=True)
    assert "1 / 2 페이지 · 전체 52개" in first_page
    assert "2 / 2 페이지 · 전체 52개" in second_page
    assert "이전" in second_page

    search_page = client.get(
        "/admin/products", query_string={"q": "관리 페이지 상품 17"}
    ).get_data(as_text=True)
    assert "관리 페이지 상품 17" in search_page
    assert "관리 페이지 상품 18" not in search_page

    wildcard_page = client.get(
        "/admin/products", query_string={"q": "%"}
    ).get_data(as_text=True)
    assert "관리 페이지 상품 17" not in wildcard_page
    assert client.get("/admin/products", query_string={"q": "가" * 101}).status_code == 400
