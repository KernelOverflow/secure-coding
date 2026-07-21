"""회원 검색, 공개 프로필, 직접 송금과 개인 거래 내역을 제공한다"""

import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
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
    """차단되지 않은 다른 회원을 공개 닉네임과 소개글로 검색한다"""
    keyword = (request.args.get("q") or "").strip()[:20]
    users = []
    if keyword:
        users = (
            User.query.filter(
                User.status != "banned",
                User.id != current_user.id,
                or_(User.nickname.ilike(f"%{keyword}%"), User.bio.ilike(f"%{keyword}%")),
            )
            .order_by(User.nickname.asc())
            .limit(50)
            .all()
        )
    # 검색 결과마다 별도 송금 키를 만들어 같은 요청의 중복 처리를 막는다
    transfer_keys = {user.id: str(uuid.uuid4()) for user in users}
    return render_template(
        "users/search.html", users=users, keyword=keyword, transfer_keys=transfer_keys
    )


@bp.get("/<user_id>")
@login_required
def view_user(user_id: str):
    """차단되지 않은 회원의 공개 프로필과 송금 폼을 보여준다. 관리자는 이력 확인을 위해 차단된 회원도 볼 수 있다"""
    user = db.session.get(User, validate_uuid(user_id, "사용자 ID"))
    if not user or (user.status == "banned" and not current_user.is_admin):
        abort(404)
    return render_template(
        "users/detail.html", user=user, transfer_key=str(uuid.uuid4())
    )


@bp.get("/profile-images/<filename>")
@login_required
def profile_image(filename: str):
    """활성 회원과 연결된 재인코딩 프로필 이미지만 로그인 사용자에게 보여 준다"""
    # 업로드 폴더의 파일명을 추측해도 DB에 연결되지 않으면 받을 수 없다
    user = User.query.filter_by(profile_image_filename=filename).first()
    if not user or user.status == "banned":
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        filename,
        max_age=3600,
    )


@bp.post("/<user_id>/transfer")
@login_required
@limiter.limit("10 per minute")
def transfer(user_id: str):
    """현재 비밀번호와 요청 고유 키를 확인한 뒤 다른 회원에게 원화를 송금한다"""
    receiver_id = validate_uuid(user_id, "사용자 ID")
    try:
        amount = parse_positive_krw(request.form.get("amount", ""))
        idempotency_key = validate_uuid(
            request.form.get("idempotency_key", ""), "요청 식별자"
        )
        # 로그인 세션만 탈취한 사람의 송금을 막기 위해 현재 비밀번호를 다시 확인한다
        if not verify_password(
            current_user.password_hash, request.form.get("current_password") or ""
        ):
            raise TransactionError("현재 비밀번호가 올바르지 않습니다.")
        note = (request.form.get("note") or "회원 간 송금").strip()
        if len(note) > 200:
            raise ValidationError("송금 메모는 200자 이하여야 합니다.")
        # 잔액 이동과 거래 기록은 서비스 계층이 하나의 DB 트랜잭션으로 처리한다
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
    """현재 사용자가 보내거나 받은 거래를 최신 순으로 최대 200개 보여준다"""
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
