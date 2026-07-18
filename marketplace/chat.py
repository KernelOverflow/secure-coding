from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from flask import Blueprint, abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from flask_socketio import disconnect, emit, join_room
from flask_wtf.csrf import ValidationError as CsrfValidationError
from flask_wtf.csrf import validate_csrf
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .extensions import db, socketio
from .models import Conversation, Message, Product
from .security import ValidationError, validate_text, validate_uuid
from .services import add_audit_log


bp = Blueprint("chat", __name__, url_prefix="/conversations")
message_windows: dict[str, deque[float]] = defaultdict(deque)
message_window_lock = Lock()


def _can_access(conversation: Conversation) -> bool:
    return current_user.is_authenticated and (
        current_user.is_admin
        or current_user.id in {conversation.buyer_id, conversation.seller_id}
    )


def _socket_rate_allowed(user_id: str) -> bool:
    now = monotonic()
    with message_window_lock:
        window = message_windows[user_id]
        while window and now - window[0] > 10:
            window.popleft()
        if len(window) >= 10:
            return False
        window.append(now)
        return True


def _validate_socket_csrf(token: str | None) -> None:
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        validate_csrf(token)


@bp.get("")
@login_required
def list_conversations():
    items = (
        Conversation.query.filter(
            or_(
                Conversation.buyer_id == current_user.id,
                Conversation.seller_id == current_user.id,
            )
        )
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return render_template("chat/list.html", conversations=items)


@bp.post("/products/<product_id>/start")
@login_required
def start_conversation(product_id: str):
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product or product.status not in {"active", "sold"}:
        abort(404)
    if product.seller_id == current_user.id:
        flash("본인의 상품에는 문의 대화를 만들 수 없습니다.", "error")
        return redirect(url_for("products.view_product", product_id=product.id))

    conversation = Conversation.query.filter_by(
        product_id=product.id,
        buyer_id=current_user.id,
        seller_id=product.seller_id,
    ).first()
    if not conversation:
        conversation = Conversation(
            product_id=product.id,
            buyer_id=current_user.id,
            seller_id=product.seller_id,
        )
        db.session.add(conversation)
        try:
            db.session.flush()
            add_audit_log(
                "chat.conversation_created",
                "conversation",
                conversation.id,
                "상품 문의 대화 시작",
                actor_id=current_user.id,
            )
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            conversation = Conversation.query.filter_by(
                product_id=product.id,
                buyer_id=current_user.id,
                seller_id=product.seller_id,
            ).first()
    return redirect(url_for("chat.view_conversation", conversation_id=conversation.id))


@bp.get("/<conversation_id>")
@login_required
def view_conversation(conversation_id: str):
    conversation = db.session.get(
        Conversation, validate_uuid(conversation_id, "대화방 ID")
    )
    if not conversation:
        abort(404)
    if not _can_access(conversation):
        abort(403)
    messages = conversation.messages.order_by(Message.created_at.asc()).limit(500).all()
    return render_template(
        "chat/detail.html", conversation=conversation, messages=messages
    )


@socketio.on("connect")
def socket_connect(_auth=None):
    if not current_user.is_authenticated or current_user.status != "active":
        return False
    return True


@socketio.on("join_conversation")
def join_conversation_event(data):
    if not current_user.is_authenticated:
        disconnect()
        return
    try:
        _validate_socket_csrf((data or {}).get("csrf_token"))
        conversation_id = validate_uuid((data or {}).get("conversation_id"), "대화방 ID")
    except (CsrfValidationError, ValidationError):
        emit("chat_error", {"message": "유효하지 않은 대화방 참가 요청입니다."})
        return
    conversation = db.session.get(Conversation, conversation_id)
    if not conversation or not _can_access(conversation):
        emit("chat_error", {"message": "대화방 접근 권한이 없습니다."})
        return
    join_room(f"conversation:{conversation.id}")
    emit("conversation_joined", {"conversation_id": conversation.id})


@socketio.on("send_private_message")
def send_private_message_event(data):
    if not current_user.is_authenticated or current_user.status != "active":
        disconnect()
        return
    if not _socket_rate_allowed(current_user.id):
        emit("chat_error", {"message": "메시지를 너무 빠르게 보내고 있습니다."})
        return
    try:
        _validate_socket_csrf((data or {}).get("csrf_token"))
        conversation_id = validate_uuid((data or {}).get("conversation_id"), "대화방 ID")
        content = validate_text((data or {}).get("message", ""), "메시지", 1, 1000)
    except (CsrfValidationError, ValidationError):
        emit("chat_error", {"message": "메시지 형식이 올바르지 않습니다."})
        return
    conversation = db.session.get(Conversation, conversation_id)
    if not conversation or not _can_access(conversation):
        emit("chat_error", {"message": "대화방 접근 권한이 없습니다."})
        return

    message = Message(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        content=content,
    )
    db.session.add(message)
    db.session.commit()
    emit(
        "private_message",
        {
            "id": message.id,
            "conversation_id": conversation.id,
            "sender_id": current_user.id,
            "sender": current_user.username,
            "message": message.content,
            "created_at": message.created_at.isoformat(),
        },
        to=f"conversation:{conversation.id}",
    )
