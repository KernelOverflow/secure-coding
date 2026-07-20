"""관리자가 회원, 상품, 신고, 거래, 채팅과 감사 기록을 관리하는 기능이다"""

import uuid
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db, limiter
from .models import (
    AuditLog,
    Conversation,
    Message,
    MoneyTransaction,
    Product,
    ProductComment,
    Purchase,
    Report,
    User,
    utc_now,
)
from .security import ValidationError, delete_uploaded_image, validate_text, validate_uuid
from .services import TransactionError, add_audit_log, reverse_transaction


# 모든 관리자 URL에 /admin 접두사를 붙여 일반 기능과 구분한다
bp = Blueprint("admin", __name__, url_prefix="/admin")
ADMIN_PAGE_SIZE = 50


def admin_required(view):
    """로그인과 관리자 역할을 모두 확인하는 공통 접근 제어 장식자이다"""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        """원래 화면 함수를 실행하기 전에 관리자 역할을 확인한다"""
        # URL을 직접 입력해도 관리자 역할이 아니면 즉시 403으로 거부한다
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _paginate(query):
    """관리자가 데이터 개수와 관계없이 모든 행에 접근할 수 있도록 50개씩 나눈다"""
    page = request.args.get("page", 1, type=int) or 1
    return query.paginate(
        page=max(page, 1), per_page=ADMIN_PAGE_SIZE, error_out=False
    )


def _search_term() -> str:
    """관리 목록 검색어를 공백 정리 후 최대 100자로 제한한다"""
    try:
        return validate_text(request.args.get("q", ""), "검색어", 0, 100)
    except ValidationError:
        abort(400)


@bp.get("")
@admin_required
def dashboard():
    """관리 대상별 개수를 모아 관리자 대시보드에 보여준다"""
    counts = {
        "users": User.query.count(),
        "products": Product.query.count(),
        "pending_reports": Report.query.filter_by(status="pending").count(),
        "transactions": MoneyTransaction.query.count(),
        "conversations": Conversation.query.count(),
        "comments": ProductComment.query.count(),
        "messages": Message.query.count(),
        "purchases": Purchase.query.count(),
    }
    return render_template("admin/dashboard.html", counts=counts)


@bp.get("/users")
@admin_required
def users():
    """전체 회원을 검색하고 최근 가입 순서대로 페이지를 나눠 보여준다"""
    query = User.query
    search = _search_term()
    if search:
        query = query.filter(
            or_(
                User.nickname.contains(search, autoescape=True),
                User.login_id.contains(search, autoescape=True),
            )
        )
    pagination = _paginate(query.order_by(User.created_at.desc()))
    return render_template(
        "admin/users.html", users=pagination.items, pagination=pagination, search=search
    )


@bp.post("/users/<user_id>/status")
@admin_required
@limiter.limit("30 per minute")
def update_user_status(user_id: str):
    """관리자 사유와 함께 회원을 활성, 임시 정지 또는 차단 상태로 변경한다"""
    user = db.session.get(User, validate_uuid(user_id, "사용자 ID"))
    if not user:
        abort(404)
    status = request.form.get("status")
    if status not in {"active", "suspended", "banned"}:
        abort(400)
    try:
        reason = validate_text(request.form.get("reason", ""), "조치 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.users"))
    # 현재 관리자가 자기 계정을 정지해 관리 기능을 잃는 실수를 막는다
    if user.id == current_user.id and status != "active":
        flash("현재 관리자 계정은 정지할 수 없습니다.", "error")
        return redirect(url_for("admin.users"))
    # 상태 변경과 감사 로그를 같은 DB 작업으로 저장한다
    user.status = status
    add_audit_log(
        "admin.user_status",
        "user",
        user.id,
        f"{status}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("회원 상태를 변경했습니다.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<user_id>/profile/reset")
@admin_required
@limiter.limit("30 per minute")
def reset_user_profile(user_id: str):
    """관리자 사유와 함께 회원 소개글이나 프로필 사진을 안전하게 초기화한다"""
    user = db.session.get(User, validate_uuid(user_id, "사용자 ID"))
    if not user:
        abort(404)
    # 관리자 화면에서는 본인 행의 초기화 폼 자체를 노출하지 않으므로, 직접 요청도 함께 막는다
    if user.id == current_user.id:
        abort(403)
    reset_bio = request.form.get("reset_bio") == "1"
    reset_image = request.form.get("reset_image") == "1"
    if not reset_bio and not reset_image:
        flash("초기화할 프로필 항목을 선택해 주세요.", "error")
        return redirect(url_for("admin.users"))
    try:
        reason = validate_text(request.form.get("reason", ""), "조치 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.users"))

    previous_image = user.profile_image_filename
    if reset_bio:
        user.bio = ""
    if reset_image:
        user.profile_image_filename = None
    targets = ", ".join(
        name for enabled, name in ((reset_bio, "소개글"), (reset_image, "프로필 사진")) if enabled
    )
    add_audit_log(
        "admin.user_profile_reset",
        "user",
        user.id,
        f"{targets}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    if reset_image and previous_image:
        delete_uploaded_image(previous_image)
    flash("회원 프로필 항목을 초기화했습니다.", "success")
    return redirect(url_for("admin.users"))


@bp.get("/products")
@admin_required
def products():
    """전체 상품을 검색하고 상태와 함께 페이지를 나눠 조회한다"""
    query = Product.query
    search = _search_term()
    if search:
        query = query.filter(Product.title.contains(search, autoescape=True))
    pagination = _paginate(query.order_by(Product.created_at.desc()))
    return render_template(
        "admin/products.html",
        products=pagination.items,
        pagination=pagination,
        search=search,
    )


@bp.post("/products/<product_id>/status")
@admin_required
def update_product_status(product_id: str):
    """관리자 사유와 함께 상품을 공개, 숨김 또는 삭제 상태로 변경한다"""
    product = db.session.get(Product, validate_uuid(product_id, "상품 ID"))
    if not product:
        abort(404)
    status = request.form.get("status")
    if status not in {"active", "hidden", "deleted"}:
        abort(400)
    try:
        reason = validate_text(request.form.get("reason", ""), "조치 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.products"))
    # 이미 거래가 끝난 상품을 다시 판매 중으로 바꾸면 이중 판매가 가능하므로 막는다
    if product.status == "sold" and status == "active":
        flash("판매 완료 상품은 판매 중으로 되돌릴 수 없습니다.", "error")
        return redirect(url_for("admin.products"))
    product.status = status
    add_audit_log(
        "admin.product_status",
        "product",
        product.id,
        f"{status}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("상품 상태를 변경했습니다.", "success")
    return redirect(url_for("admin.products"))


@bp.get("/reports")
@admin_required
def reports():
    """접수된 신고를 최신 순서로 보여준다"""
    query = Report.query
    search = _search_term()
    if search:
        query = query.filter(
            or_(
                Report.reason.contains(search, autoescape=True),
                Report.target_id.contains(search, autoescape=True),
            )
        )
    pagination = _paginate(query.order_by(Report.created_at.desc()))
    return render_template(
        "admin/reports.html",
        reports=pagination.items,
        pagination=pagination,
        search=search,
    )


@bp.post("/reports/<report_id>/resolve")
@admin_required
def resolve_report(report_id: str):
    """신고를 조치 완료 또는 기각으로 처리하고 처리자와 시각을 기록한다"""
    report = db.session.get(Report, validate_uuid(report_id, "신고 ID"))
    if not report:
        abort(404)
    status = request.form.get("status")
    if status not in {"resolved", "dismissed"}:
        abort(400)
    try:
        reason = validate_text(request.form.get("reason", ""), "처리 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.reports"))
    # 신고 본문은 유지하고 처리 결과, 관리자, 시각만 덧붙여 추적 가능하게 한다
    report.status = status
    report.resolved_at = utc_now()
    report.resolved_by_id = current_user.id
    add_audit_log(
        "admin.report_resolved",
        "report",
        report.id,
        f"{status}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("신고를 처리했습니다.", "success")
    return redirect(url_for("admin.reports"))


@bp.get("/transactions")
@admin_required
def transactions():
    """거래 목록과 각 거래 정정에 사용할 일회성 UUID를 함께 준비한다"""
    query = MoneyTransaction.query
    search = _search_term()
    if search:
        query = query.filter(
            or_(
                MoneyTransaction.note.contains(search, autoescape=True),
                MoneyTransaction.id.contains(search, autoescape=True),
            )
        )
    pagination = _paginate(query.order_by(MoneyTransaction.created_at.desc()))
    items = pagination.items
    return render_template(
        "admin/transactions.html",
        transactions=items,
        correction_keys={item.id: str(uuid.uuid4()) for item in items},
        pagination=pagination,
        search=search,
    )


@bp.post("/transactions/<transaction_id>/reverse")
@admin_required
@limiter.limit("10 per hour")
def reverse(transaction_id: str):
    """원본을 수정하지 않고 반대 방향의 새 거래로 잘못된 거래를 정정한다"""
    transaction = db.session.get(
        MoneyTransaction, validate_uuid(transaction_id, "거래 ID")
    )
    if not transaction:
        abort(404)
    try:
        reason = validate_text(request.form.get("reason", ""), "정정 사유", 10, 500)
        idempotency_key = validate_uuid(
            request.form.get("idempotency_key", ""), "요청 식별자"
        )
        # 실제 잔액 이동과 중복 정정 방지는 서비스 계층이 하나의 트랜잭션으로 처리한다
        reverse_transaction(transaction, current_user.id, reason, idempotency_key)
    except (ValidationError, TransactionError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.transactions"))
    flash("반대 방향의 정정 거래를 기록했습니다.", "success")
    return redirect(url_for("admin.transactions"))


@bp.get("/conversations")
@admin_required
def conversations():
    """분쟁 확인을 위해 생성된 1:1 대화방 목록을 관리자에게 보여준다"""
    query = Conversation.query
    search = _search_term()
    if search:
        query = query.join(Conversation.product).filter(
            Product.title.contains(search, autoescape=True)
        )
    pagination = _paginate(query.order_by(Conversation.created_at.desc()))
    return render_template(
        "admin/conversations.html",
        conversations=pagination.items,
        pagination=pagination,
        search=search,
    )


@bp.get("/comments")
@admin_required
def comments():
    """상품 전체의 공개·삭제 댓글을 페이지 단위로 관리자에게 보여준다"""
    query = ProductComment.query
    search = _search_term()
    if search:
        query = query.join(ProductComment.product).filter(
            or_(
                ProductComment.content.contains(search, autoescape=True),
                Product.title.contains(search, autoescape=True),
            )
        )
    pagination = _paginate(query.order_by(ProductComment.created_at.desc()))
    return render_template(
        "admin/comments.html",
        comments=pagination.items,
        pagination=pagination,
        search=search,
    )


@bp.post("/comments/<comment_id>/status")
@admin_required
@limiter.limit("60 per minute")
def update_comment_status(comment_id: str):
    """관리자 사유와 함께 댓글을 숨기거나 복구하고 감사 기록을 남긴다"""
    comment = db.session.get(ProductComment, validate_uuid(comment_id, "댓글 ID"))
    if not comment:
        abort(404)
    status = request.form.get("status")
    if status not in {"active", "deleted"}:
        abort(400)
    try:
        reason = validate_text(request.form.get("reason", ""), "조치 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.comments"))
    comment.status = status
    add_audit_log(
        "admin.comment_status",
        "product_comment",
        comment.id,
        f"{status}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("댓글 상태를 변경했습니다.", "success")
    return redirect(url_for("admin.comments"))


@bp.get("/messages")
@admin_required
def messages():
    """모든 대화방의 공개·삭제 메시지를 페이지 단위로 관리자에게 보여준다"""
    query = Message.query
    search = _search_term()
    conversation_id = request.args.get("conversation_id", "").strip()
    if conversation_id:
        query = query.filter_by(
            conversation_id=validate_uuid(conversation_id, "대화방 ID")
        )
    if search:
        query = query.filter(Message.content.contains(search, autoescape=True))
    pagination = _paginate(query.order_by(Message.created_at.desc()))
    return render_template(
        "admin/messages.html",
        messages=pagination.items,
        pagination=pagination,
        conversation_id=conversation_id,
        search=search,
    )


@bp.post("/messages/<message_id>/status")
@admin_required
@limiter.limit("60 per minute")
def update_message_status(message_id: str):
    """관리자 사유와 함께 채팅 메시지를 숨기거나 복구하고 감사 기록을 남긴다"""
    message = db.session.get(Message, validate_uuid(message_id, "메시지 ID"))
    if not message:
        abort(404)
    status = request.form.get("status")
    if status not in {"active", "deleted"}:
        abort(400)
    try:
        reason = validate_text(request.form.get("reason", ""), "조치 사유", 5, 500)
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.messages"))
    message.status = status
    add_audit_log(
        "admin.message_status",
        "message",
        message.id,
        f"{status}: {reason}",
        actor_id=current_user.id,
    )
    db.session.commit()
    flash("채팅 메시지 상태를 변경했습니다.", "success")
    return redirect(url_for("admin.messages"))


@bp.get("/purchases")
@admin_required
def purchases():
    """상품, 구매자, 판매자와 거래를 연결한 구매 기록 전체를 보여준다"""
    query = Purchase.query
    search = _search_term()
    if search:
        query = query.join(Purchase.product).filter(
            Product.title.contains(search, autoescape=True)
        )
    pagination = _paginate(query.order_by(Purchase.created_at.desc()))
    return render_template(
        "admin/purchases.html",
        purchases=pagination.items,
        pagination=pagination,
        search=search,
    )


@bp.get("/audit-logs")
@admin_required
def audit_logs():
    """주요 보안 작업의 수행자, 대상, 사유, 시각, IP를 최신 순으로 보여준다"""
    query = AuditLog.query
    search = _search_term()
    if search:
        query = query.filter(
            or_(
                AuditLog.action.contains(search, autoescape=True),
                AuditLog.reason.contains(search, autoescape=True),
                AuditLog.target_type.contains(search, autoescape=True),
            )
        )
    pagination = _paginate(query.order_by(AuditLog.created_at.desc()))
    return render_template(
        "admin/audit_logs.html",
        logs=pagination.items,
        pagination=pagination,
        search=search,
    )
