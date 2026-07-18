import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db, limiter
from .models import MoneyTransaction, User
from .security import ValidationError, parse_positive_krw, validate_uuid, verify_password
from .services import TransactionError, transfer_funds


bp = Blueprint("users", __name__, url_prefix="/users")


@bp.get("")
@login_required
def search_users():
    keyword = (request.args.get("q") or "").strip()[:20]
    users = []
    if keyword:
        users = (
            User.query.filter(
                User.status != "banned",
                User.id != current_user.id,
                or_(User.username.ilike(f"%{keyword}%"), User.bio.ilike(f"%{keyword}%")),
            )
            .order_by(User.username.asc())
            .limit(50)
            .all()
        )
    transfer_keys = {user.id: str(uuid.uuid4()) for user in users}
    return render_template(
        "users/search.html", users=users, keyword=keyword, transfer_keys=transfer_keys
    )


@bp.get("/<user_id>")
@login_required
def view_user(user_id: str):
    user = db.session.get(User, validate_uuid(user_id, "사용자 ID"))
    if not user or user.status == "banned":
        abort(404)
    return render_template(
        "users/detail.html", user=user, transfer_key=str(uuid.uuid4())
    )


@bp.post("/<user_id>/transfer")
@login_required
@limiter.limit("10 per minute")
def transfer(user_id: str):
    receiver_id = validate_uuid(user_id, "사용자 ID")
    try:
        amount = parse_positive_krw(request.form.get("amount", ""))
        idempotency_key = validate_uuid(
            request.form.get("idempotency_key", ""), "요청 식별자"
        )
        if not verify_password(
            current_user.password_hash, request.form.get("current_password") or ""
        ):
            raise TransactionError("현재 비밀번호가 올바르지 않습니다.")
        note = (request.form.get("note") or "회원 간 송금").strip()
        if len(note) > 200:
            raise ValidationError("송금 메모는 200자 이하여야 합니다.")
        _transaction, created = transfer_funds(
            current_user.id, receiver_id, amount, idempotency_key, note or "회원 간 송금"
        )
    except (ValidationError, TransactionError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("users.view_user", user_id=receiver_id))

    flash("송금이 완료되었습니다." if created else "이미 처리된 송금 요청입니다.", "success")
    return redirect(url_for("users.transactions"))


@bp.get("/transactions/history")
@login_required
def transactions():
    items = (
        MoneyTransaction.query.filter(
            or_(
                MoneyTransaction.sender_id == current_user.id,
                MoneyTransaction.receiver_id == current_user.id,
            )
        )
        .order_by(MoneyTransaction.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("users/transactions.html", transactions=items)
