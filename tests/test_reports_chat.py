"""신고 임계값과 상품별 비공개 1:1 채팅의 HTTP·Socket 권한을 검증한다"""

from marketplace.extensions import db, socketio
from marketplace.models import Conversation, Message, Product, Report

from .conftest import login_as


def _report(client, reporter_id, target_type, target_id, reason):
    """지정한 테스트 사용자로 로그인해 신고 요청을 보내는 반복 작업을 줄인다"""
    login_as(client, reporter_id)
    return client.post(
        "/reports/new",
        data={"target_type": target_type, "target_id": target_id, "reason": reason},
    )


def test_three_distinct_reports_hide_product(client, app, users, product):
    """서로 다른 세 명의 상품 신고가 누적되면 상품이 숨김 상태가 되는지 확인한다"""
    _report(client, users["buyer"], "product", product, "상품 내용이 허위인 것 같습니다.")
    _report(client, users["reporter1"], "product", product, "사진과 설명이 일치하지 않습니다.")
    _report(client, users["reporter2"], "product", product, "판매가 금지된 상품으로 보입니다.")
    with app.app_context():
        assert db.session.get(Product, product).status == "hidden"
        assert Report.query.filter_by(target_id=product).count() == 3


def test_duplicate_report_is_rejected(client, app, users, product):
    """같은 사용자가 동일 상품을 반복 신고해 임계값을 올릴 수 없는지 확인한다"""
    _report(client, users["buyer"], "product", product, "첫 번째 상세 신고 사유입니다.")
    _report(client, users["buyer"], "product", product, "두 번째 상세 신고 사유입니다.")
    with app.app_context():
        assert Report.query.filter_by(reporter_id=users["buyer"], target_id=product).count() == 1


def test_conversation_is_unique_and_private(client, app, users, product):
    """상품 문의방은 한 개만 만들어지고 제3자의 HTTP 접근은 403인지 확인한다"""
    login_as(client, users["buyer"])
    first = client.post(f"/conversations/products/{product}/start")
    second = client.post(f"/conversations/products/{product}/start")
    assert first.status_code == 302
    assert second.status_code == 302
    with app.app_context():
        conversation = Conversation.query.filter_by(product_id=product).one()
        conversation_id = conversation.id
    login_as(client, users["reporter1"])
    assert client.get(f"/conversations/{conversation_id}").status_code == 403


def test_conversation_list_shows_product_image_preview(client, app, users, product):
    """대화 목록에서 문의 상품의 이미지 미리보기를 확인할 수 있는지 검사한다"""
    image_filename = "11111111-1111-4111-8111-111111111111.jpg"
    with app.app_context():
        item = db.session.get(Product, product)
        item.image_filename = image_filename
        db.session.add(
            Conversation(
                product_id=product,
                buyer_id=users["buyer"],
                seller_id=users["seller"],
            )
        )
        db.session.commit()

    login_as(client, users["buyer"])
    page = client.get("/conversations").get_data(as_text=True)
    assert f'/uploads/{image_filename}' in page
    assert 'class="product-card-image"' in page
    assert 'loading="lazy"' in page


def test_chat_aligns_own_messages_right_and_other_messages_left(
    client, app, users, product
):
    """본인 메시지와 상대방 메시지에 서로 다른 정렬 클래스를 적용하는지 확인한다"""
    with app.app_context():
        conversation = Conversation(
            product_id=product,
            buyer_id=users["buyer"],
            seller_id=users["seller"],
        )
        db.session.add(conversation)
        db.session.flush()
        db.session.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    sender_id=users["seller"],
                    content="상대방이 보낸 메시지",
                ),
                Message(
                    conversation_id=conversation.id,
                    sender_id=users["buyer"],
                    content="내가 보낸 메시지",
                ),
            ]
        )
        db.session.commit()
        conversation_id = conversation.id

    login_as(client, users["buyer"])
    page = client.get(f"/conversations/{conversation_id}").get_data(as_text=True)
    assert f'data-current-user-id="{users["buyer"]}"' in page
    assert 'class="message message-other"' in page
    assert 'class="message message-own"' in page


def test_socket_rejects_nonparticipant_and_accepts_participant(client, app, users, product):
    """Socket room도 제3자는 거부하고 실제 참여자만 참가와 전송이 가능한지 확인한다"""
    login_as(client, users["buyer"])
    client.post(f"/conversations/products/{product}/start")
    with app.app_context():
        conversation_id = Conversation.query.filter_by(product_id=product).one().id

    buyer_socket = socketio.test_client(app, flask_test_client=client)
    assert buyer_socket.is_connected()
    buyer_socket.emit(
        "join_conversation", {"conversation_id": conversation_id, "csrf_token": "test"}
    )
    buyer_socket.emit(
        "send_private_message",
        {"conversation_id": conversation_id, "csrf_token": "test", "message": "안녕하세요"},
    )
    received = buyer_socket.get_received()
    assert any(item["name"] == "private_message" for item in received), received
    private_message = next(item for item in received if item["name"] == "private_message")
    assert private_message["args"][0]["sender"] == "구매자"
    assert "buyer" not in private_message["args"][0].values()
    buyer_socket.disconnect()

    login_as(client, users["reporter1"])
    other_socket = socketio.test_client(app, flask_test_client=client)
    other_socket.emit(
        "join_conversation", {"conversation_id": conversation_id, "csrf_token": "test"}
    )
    assert any(item["name"] == "chat_error" for item in other_socket.get_received())
    other_socket.disconnect()
