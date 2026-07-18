from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, limiter
from .models import User, utc_now
from .security import (
    ValidationError,
    hash_password,
    needs_password_rehash,
    validate_password,
    validate_text,
    validate_username,
    verify_password,
)
from .services import add_audit_log


bp = Blueprint("auth", __name__)


@bp.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    return render_template("index.html")


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    if request.method == "GET":
        return render_template("auth/register.html")

    try:
        username = validate_username(request.form.get("username", ""))
        password = validate_password(request.form.get("password", ""), username)
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("auth/register.html"), 400

    if User.query.filter_by(username=username).first():
        flash("이미 사용 중인 사용자명입니다.", "error")
        return render_template("auth/register.html"), 409

    user = User(username=username, password_hash=hash_password(password))
    db.session.add(user)
    db.session.flush()
    add_audit_log("auth.register", "user", user.id, "회원가입", actor_id=user.id)
    db.session.commit()
    flash("회원가입이 완료되었습니다. 로그인해 주세요.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    if request.method == "GET":
        return render_template("auth/login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = User.query.filter_by(username=username).first()
    now = utc_now()
    locked = bool(user and user.locked_until and user.locked_until > now)
    valid = bool(user and not locked and verify_password(user.password_hash, password))

    if not valid:
        if user and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=5)
                user.failed_login_count = 0
            add_audit_log("auth.login_failed", "user", user.id, "로그인 실패")
            db.session.commit()
        flash("사용자명 또는 비밀번호를 확인하거나 잠시 후 다시 시도해 주세요.", "error")
        return render_template("auth/login.html"), 401

    if user.status != "active":
        flash("정지되었거나 사용할 수 없는 계정입니다.", "error")
        return render_template("auth/login.html"), 403

    user.failed_login_count = 0
    user.locked_until = None
    if needs_password_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    session.clear()
    login_user(user, remember=False, fresh=True)
    session.permanent = True
    session["auth_time"] = now.isoformat()
    add_audit_log("auth.login", "user", user.id, "로그인", actor_id=user.id)
    db.session.commit()
    flash("로그인되었습니다.", "success")
    return redirect(url_for("products.list_products"))


@bp.post("/logout")
@login_required
def logout():
    user_id = current_user.id
    logout_user()
    session.clear()
    add_audit_log("auth.logout", "user", user_id, "로그아웃", actor_id=user_id)
    db.session.commit()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("auth.index"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        try:
            current_user.bio = validate_text(
                request.form.get("bio", ""), "소개글", 0, 500
            )
        except ValidationError as exc:
            flash(str(exc), "error")
            return render_template("auth/profile.html"), 400
        add_audit_log(
            "profile.updated", "user", current_user.id, "소개글 수정", actor_id=current_user.id
        )
        db.session.commit()
        flash("프로필을 수정했습니다.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html")


@bp.post("/profile/password")
@login_required
@limiter.limit("5 per hour")
def change_password():
    current_password = request.form.get("current_password") or ""
    if not verify_password(current_user.password_hash, current_password):
        flash("현재 비밀번호가 올바르지 않습니다.", "error")
        return redirect(url_for("auth.profile"))
    try:
        new_password = validate_password(
            request.form.get("new_password", ""), current_user.username
        )
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.profile"))
    if verify_password(current_user.password_hash, new_password):
        flash("기존 비밀번호와 다른 비밀번호를 사용해 주세요.", "error")
        return redirect(url_for("auth.profile"))

    current_user.password_hash = hash_password(new_password)
    add_audit_log(
        "profile.password_changed",
        "user",
        current_user.id,
        "비밀번호 변경",
        actor_id=current_user.id,
    )
    db.session.commit()
    session.clear()
    logout_user()
    flash("비밀번호를 변경했습니다. 다시 로그인해 주세요.", "success")
    return redirect(url_for("auth.login"))
