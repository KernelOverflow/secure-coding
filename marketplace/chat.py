"""상품별 구매자와 판매자의 비공개 1:1 채팅방과 Socket.IO 이벤트를 처리한다"""

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


# 최근 전송 시각을 사용자별 deque에 보관해 10초당 10개로 메시지를 제한한다
bp = Blueprint("chat", __name__, url_prefix="/conversations")
message_windows: dict[str, deque[float]] = defaultdict(deque)
# 여러 스레드가 같은 전송 기록을 동시에 바꾸지 않도록 Lock으로 보호한다
message_window_lock = Lock()


def _is_participant(conversation: Conversation) -> bool:
    """현재 사용자가 이 대화의 실제 구매자 또는 판매자인지 확인한다"""
    return current_user.is_authenticated and current_user.id in {
        conversation.buyer_id,
        conversation.seller_id,
    }


def _can_access(conversation: Conversation) -> bool:
    """열람은 참여자와 관리자 모두에게 허용한다. 메시지 전송은 실제 참여자만 가능하며 관리자라고
    자동으로 열리지 않으므로 전송 권한을 확인할 때는 이 함수 대신 _is_participant를 사용한다"""
    return current_user.is_authenticated and (
        current_user.is_admin or _is_participant(conversation)
    )


def _socket_rate_allowed(user_id: str) -> bool:
    """사용자의 최근 10초 메시지가 10개 미만일 때만 새 전송을 허용한다"""
    now = monotonic()
    with message_window_lock:
        window = message_windows[user_id]
        # 현재 시각에서 10초보다 오래된 기록은 제한 계산에서 제거한다
        while window and now - window[0] > 10:
            window.popleft()
        if len(window) >= 10:
            return False
        window.append(now)
        return True


def _validate_socket_csrf(token: str | None) -> None:
    """Socket 이벤트도 HTTP 폼과 같은 세션 CSRF 토큰으로 요청 위조를 검사한다"""
    if current_app.config.get("WTF_CSRF_ENABLED", True):
        validate_csrf(token)


@bp.get("")
@login_required
def list_conversations():
    """현재 사용자가 구매자 또는 판매자로 참여한 대화방만 보여준다"""
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
    """상품, 구매자, 판매자 조합에 해당하는 대화방을 하나만 생성한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product or product.status not in {"active", "sold"}:
        abort(404)
    if product.seller_id == current_user.id:
        flash("본인의 상품에는 문의 대화를 만들 수 없습니다.", "error")
        return redirect(url_for("products.view_product", product_id=product.id))

    # 이미 같은 상품 문의방이 있으면 새 방을 만들지 않고 기존 방을 사용한다
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
            # 동시 요청이 같은 방을 만들었다면 롤백 후 먼저 생성된 방을 다시 조회한다
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
    """권한이 있는 참여자에게 대화 내용 최대 500개를 시간순으로 보여준다"""
    conversation = db.session.get(
        Conversation, validate_uuid(conversation_id, "대화방 ID")
    )
    if not conversation:
        abort(404)
    if not _can_access(conversation):
        abort(403)
    # 관리자가 숨긴 메시지는 참여자 화면과 이후 새로고침에서 다시 노출하지 않는다
    messages = (
        conversation.messages.filter_by(status="active")
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )
    return render_template(
        "chat/detail.html",
        conversation=conversation,
        messages=messages,
        is_participant=_is_participant(conversation),
    )


@socketio.on("connect")
def socket_connect(_auth=None):
    """활성 로그인 세션이 있는 사용자만 Socket.IO 연결을 받아들인다"""
    if not current_user.is_authenticated or current_user.status != "active":
        return False
    return True


@socketio.on("join_conversation")
def join_conversation_event(data):
    """CSRF와 참여 권한을 확인한 뒤 해당 대화방 Socket room에 참가시킨다"""
    if not current_user.is_authenticated:
        disconnect()
        return
    # 클라이언트가 보낸 사용자 ID는 믿지 않고 서버 로그인 세션과 대화방 UUID만 사용한다
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
    # 대화별 room 이름을 분리해 다른 상품의 메시지가 섞이지 않게 한다
    join_room(f"conversation:{conversation.id}")
    emit("conversation_joined", {"conversation_id": conversation.id})


@socketio.on("send_private_message")
def send_private_message_event(data):
    """메시지 형식과 권한을 검사해 저장하고 해당 대화 참여자에게만 전송한다"""
    if not current_user.is_authenticated or current_user.status != "active":
        disconnect()
        return
    # 짧은 시간에 반복 전송하는 도배 요청은 DB에 저장하기 전에 거부한다
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
    # 관리자도 실제 구매자·판매자가 아니면 열람만 가능하고 남의 대화에 메시지를 보낼 수는 없다
    if not conversation or not _is_participant(conversation):
        emit("chat_error", {"message": "대화 참여자만 메시지를 보낼 수 있습니다."})
        return

    # 발신자는 클라이언트 값이 아니라 검증된 current_user로 고정해 사칭을 막는다
    message = Message(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        content=content,
    )
    db.session.add(message)
    db.session.commit()
    # 저장된 내용을 해당 conversation room에만 보내 실시간 화면을 갱신한다
    emit(
        "private_message",
        {
            "id": message.id,
            "conversation_id": conversation.id,
            "sender_id": current_user.id,
            "sender": current_user.nickname,
            "sender_avatar_url": (
                url_for("users.profile_image", filename=current_user.profile_image_filename)
                if current_user.profile_image_filename
                else None
            ),
            "message": message.content,
            "created_at": message.created_at.isoformat(),
        },
        to=f"conversation:{conversation.id}",
    )
