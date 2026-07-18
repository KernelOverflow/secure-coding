from marketplace.extensions import db, socketio
from marketplace.models import Conversation, Product, Report

from .conftest import login_as


def _report(client, reporter_id, target_type, target_id, reason):
    login_as(client, reporter_id)
    return client.post(
        "/reports/new",
        data={"target_type": target_type, "target_id": target_id, "reason": reason},
    )


def test_three_distinct_reports_hide_product(client, app, users, product):
    _report(client, users["buyer"], "product", product, "상품 내용이 허위인 것 같습니다.")
    _report(client, users["reporter1"], "product", product, "사진과 설명이 일치하지 않습니다.")
    _report(client, users["reporter2"], "product", product, "판매가 금지된 상품으로 보입니다.")
    with app.app_context():
        assert db.session.get(Product, product).status == "hidden"
        assert Report.query.filter_by(target_id=product).count() == 3


def test_duplicate_report_is_rejected(client, app, users, product):
    _report(client, users["buyer"], "product", product, "첫 번째 상세 신고 사유입니다.")
    _report(client, users["buyer"], "product", product, "두 번째 상세 신고 사유입니다.")
    with app.app_context():
        assert Report.query.filter_by(reporter_id=users["buyer"], target_id=product).count() == 1


def test_conversation_is_unique_and_private(client, app, users, product):
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


def test_socket_rejects_nonparticipant_and_accepts_participant(client, app, users, product):
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
    buyer_socket.disconnect()

    login_as(client, users["reporter1"])
    other_socket = socketio.test_client(app, flask_test_client=client)
    other_socket.emit(
        "join_conversation", {"conversation_id": conversation_id, "csrf_token": "test"}
    )
    assert any(item["name"] == "chat_error" for item in other_socket.get_received())
    other_socket.disconnect()
