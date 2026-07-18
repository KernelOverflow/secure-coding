import uuid
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db, limiter
from .models import (
    AuditLog,
    Conversation,
    MoneyTransaction,
    Product,
    Report,
    User,
    utc_now,
)
from .security import ValidationError, validate_text, validate_uuid
from .services import TransactionError, add_audit_log, reverse_transaction


bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@bp.get("")
@admin_required
def dashboard():
    counts = {
        "users": User.query.count(),
        "products": Product.query.count(),
        "pending_reports": Report.query.filter_by(status="pending").count(),
        "transactions": MoneyTransaction.query.count(),
        "conversations": Conversation.query.count(),
    }
    return render_template("admin/dashboard.html", counts=counts)


@bp.get("/users")
@admin_required
def users():
    items = User.query.order_by(User.created_at.desc()).limit(500).all()
    return render_template("admin/users.html", users=items)


@bp.post("/users/<user_id>/status")
@admin_required
@limiter.limit("30 per minute")
def update_user_status(user_id: str):
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
    if user.id == current_user.id and status != "active":
        flash("현재 관리자 계정은 정지할 수 없습니다.", "error")
        return redirect(url_for("admin.users"))
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


@bp.get("/products")
@admin_required
def products():
    items = Product.query.order_by(Product.created_at.desc()).limit(500).all()
    return render_template("admin/products.html", products=items)


@bp.post("/products/<product_id>/status")
@admin_required
def update_product_status(product_id: str):
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
    items = Report.query.order_by(Report.created_at.desc()).limit(500).all()
    return render_template("admin/reports.html", reports=items)


@bp.post("/reports/<report_id>/resolve")
@admin_required
def resolve_report(report_id: str):
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
    items = MoneyTransaction.query.order_by(MoneyTransaction.created_at.desc()).limit(500).all()
    return render_template(
        "admin/transactions.html", transactions=items, correction_keys={item.id: str(uuid.uuid4()) for item in items}
    )


@bp.post("/transactions/<transaction_id>/reverse")
@admin_required
@limiter.limit("10 per hour")
def reverse(transaction_id: str):
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
        reverse_transaction(transaction, current_user.id, reason, idempotency_key)
    except (ValidationError, TransactionError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.transactions"))
    flash("반대 방향의 정정 거래를 기록했습니다.", "success")
    return redirect(url_for("admin.transactions"))


@bp.get("/conversations")
@admin_required
def conversations():
    items = Conversation.query.order_by(Conversation.created_at.desc()).limit(500).all()
    return render_template("admin/conversations.html", conversations=items)


@bp.get("/audit-logs")
@admin_required
def audit_logs():
    items = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/audit_logs.html", logs=items)
