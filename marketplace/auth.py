"""회원가입, 로그인, 로그아웃, 프로필과 비밀번호 변경 요청을 처리한다"""

from datetime import timedelta
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, limiter
from .models import User, utc_now
from .security import (
    ValidationError,
    delete_uploaded_image,
    hash_password,
    needs_password_rehash,
    nickname_key,
    normalize_login_id,
    save_profile_image,
    validate_login_id,
    validate_nickname,
    validate_password,
    validate_text,
    verify_password,
)
from .services import add_audit_log


# 인증 관련 URL을 하나의 Blueprint로 묶어 앱 팩토리에서 등록한다
bp = Blueprint("auth", __name__)


def _safe_next_url(value: str | None) -> str | None:
    """로그인 후 이동할 경로가 현재 서버 내부 주소인지 확인한다"""
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


@bp.get("/")
def index():
    """비로그인 사용자에게는 소개 화면을, 로그인 사용자에게는 상품 목록을 보여준다"""
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    return render_template("index.html")


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    """가입 화면을 보여 주거나 검증된 새 사용자 계정을 생성한다"""
    # 이미 로그인한 사용자가 중복 계정을 만들지 않도록 상품 목록으로 보낸다
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    if request.method == "GET":
        return render_template("auth/register.html")

    # 브라우저의 required 속성은 우회할 수 있으므로 모든 값을 서버에서 다시 검사한다
    try:
        nickname = validate_nickname(request.form.get("nickname", ""))
        login_id = validate_login_id(request.form.get("login_id", ""))
        password = validate_password(
            request.form.get("password", ""), login_id, nickname
        )
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("auth/register.html"), 400

    # 정규화 열을 조회해 대소문자나 유니코드 표현을 바꾼 중복도 막는다
    if User.query.filter_by(login_id_normalized=normalize_login_id(login_id)).first():
        flash("이미 사용 중인 아이디입니다.", "error")
        return render_template("auth/register.html"), 409
    if User.query.filter_by(nickname_normalized=nickname_key(nickname)).first():
        flash("이미 사용 중인 닉네임입니다.", "error")
        return render_template("auth/register.html"), 409

    # 비밀번호 원문 대신 Argon2id 해시를 넣은 User 객체를 만든다
    user = User(
        login_id=login_id,
        login_id_normalized=normalize_login_id(login_id),
        nickname=nickname,
        nickname_normalized=nickname_key(nickname),
        password_hash=hash_password(password),
    )
    db.session.add(user)
    # 감사 로그에 넣을 사용자 UUID를 먼저 발급받되 아직 거래를 확정하지는 않는다
    db.session.flush()
    add_audit_log("auth.register", "user", user.id, "회원가입", actor_id=user.id)
    db.session.commit()
    flash("회원가입이 완료되었습니다. 로그인해 주세요.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    """아이디와 비밀번호를 확인하고 안전한 로그인 세션을 새로 만든다"""
    if current_user.is_authenticated:
        return redirect(url_for("products.list_products"))
    if request.method == "GET":
        remembered_login_id = request.cookies.get(
            current_app.config["REMEMBER_LOGIN_ID_COOKIE_NAME"], ""
        )
        try:
            remembered_login_id = validate_login_id(remembered_login_id)
        except ValidationError:
            remembered_login_id = ""
        return render_template(
            "auth/login.html",
            login_id=remembered_login_id,
            remember_login_id=bool(remembered_login_id),
            keep_signed_in=False,
        )

    # 존재 여부와 관계없이 같은 흐름으로 처리해 공격자가 가입 아이디를 구분하기 어렵게 한다
    login_id = normalize_login_id(request.form.get("login_id") or "")
    password = request.form.get("password") or ""
    remember_login_id = request.form.get("remember_login_id") == "1"
    keep_signed_in = request.form.get("keep_signed_in") == "1"
    user = User.query.filter_by(login_id_normalized=login_id).first()
    now = utc_now()
    # 잠긴 계정은 비밀번호가 맞더라도 잠금 시간이 끝나기 전까지 로그인시키지 않는다
    locked = bool(user and user.locked_until and user.locked_until > now)
    valid = bool(user and not locked and verify_password(user.password_hash, password))

    if not valid:
        if user and not locked:
            # 다섯 번 연속 실패하면 5분 동안 계정을 잠그고 실패 횟수를 다시 센다
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=5)
                user.failed_login_count = 0
            add_audit_log("auth.login_failed", "user", user.id, "로그인 실패")
            db.session.commit()
        flash("아이디 또는 비밀번호를 확인하거나 잠시 후 다시 시도해 주세요.", "error")
        return (
            render_template(
                "auth/login.html",
                login_id=login_id[:20],
                remember_login_id=remember_login_id,
                keep_signed_in=keep_signed_in,
            ),
            401,
        )

    if user.status != "active":
        flash("정지되었거나 사용할 수 없는 계정입니다.", "error")
        return (
            render_template(
                "auth/login.html",
                login_id=login_id[:20],
                remember_login_id=remember_login_id,
                keep_signed_in=keep_signed_in,
            ),
            403,
        )

    # 성공 시 실패 기록을 초기화하고 필요하면 최신 Argon2 설정으로 해시를 갱신한다
    user.failed_login_count = 0
    user.locked_until = None
    if needs_password_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    # 기존 세션 데이터를 지운 뒤 새 로그인 상태를 만들어 세션 고정 공격을 줄인다
    session.clear()
    login_user(
        user,
        remember=keep_signed_in,
        duration=current_app.config["REMEMBER_COOKIE_DURATION"],
        fresh=True,
    )
    session.permanent = True
    session["auth_time"] = now.isoformat()
    add_audit_log("auth.login", "user", user.id, "로그인", actor_id=user.id)
    db.session.commit()
    flash("로그인에 성공했습니다.", "success")
    destination = _safe_next_url(request.args.get("next")) or url_for(
        "products.list_products"
    )
    response = redirect(destination)
    login_id_cookie = current_app.config["REMEMBER_LOGIN_ID_COOKIE_NAME"]
    if remember_login_id:
        response.set_cookie(
            login_id_cookie,
            login_id,
            max_age=int(timedelta(days=30).total_seconds()),
            secure=current_app.config["SESSION_COOKIE_SECURE"],
            httponly=True,
            samesite="Lax",
            path="/login",
        )
    else:
        response.delete_cookie(login_id_cookie, path="/login")
    return response


@bp.post("/logout")
@login_required
def logout():
    """로그인 상태와 세션 데이터를 지우고 로그아웃 감사 기록을 남긴다"""
    # 세션을 비운 뒤 logout_user를 호출해 로그인 유지 쿠키 삭제 표시를 보존한다
    user_id = current_user.id
    session.clear()
    logout_user()
    add_audit_log("auth.logout", "user", user_id, "로그아웃", actor_id=user_id)
    db.session.commit()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("auth.index"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def profile():
    """본인 프로필을 보여 주고 프로필 사진과 소개글을 수정한다"""
    if request.method == "POST":
        try:
            bio = validate_text(request.form.get("bio", ""), "소개글", 0, 500)
            remove_image = request.form.get("remove_profile_image") == "1"
            uploaded_file = request.files.get("profile_image")
            has_new_image = bool(uploaded_file and uploaded_file.filename)
            if remove_image and has_new_image:
                raise ValidationError(
                    "새 사진 등록과 기존 사진 삭제를 동시에 선택할 수 없습니다."
                )
            new_image_filename = save_profile_image(uploaded_file)
        except ValidationError as exc:
            flash(str(exc), "error")
            return render_template("auth/profile.html"), 400

        # DB 변경을 먼저 확정한 뒤 이전 파일을 지워 화면과 DB가 엇갈리지 않게 한다
        previous_image = current_user.profile_image_filename
        current_user.bio = bio
        if remove_image:
            current_user.profile_image_filename = None
        elif new_image_filename:
            current_user.profile_image_filename = new_image_filename
        add_audit_log(
            "profile.updated", "user", current_user.id, "프로필 수정", actor_id=current_user.id
        )
        db.session.commit()
        if previous_image and previous_image != current_user.profile_image_filename:
            delete_uploaded_image(previous_image)
        flash("프로필을 수정했습니다.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html")


@bp.post("/profile/password")
@login_required
@limiter.limit("5 per hour")
def change_password():
    """현재 비밀번호 재확인 후 새 비밀번호로 교체하고 모든 세션 정보를 지운다"""
    # 로그인 세션을 탈취한 사람만으로는 비밀번호를 바꾸지 못하도록 현재 비밀번호를 확인한다
    current_password = request.form.get("current_password") or ""
    if not verify_password(current_user.password_hash, current_password):
        flash("현재 비밀번호가 올바르지 않습니다.", "error")
        return redirect(url_for("auth.profile"))
    try:
        new_password = validate_password(
            request.form.get("new_password", ""),
            current_user.login_id,
            current_user.nickname,
        )
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.profile"))
    # 같은 비밀번호로 다시 저장하는 무의미한 변경은 허용하지 않는다
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
    # 비밀번호 변경 뒤 현재 브라우저도 로그아웃시켜 새 비밀번호로 다시 인증하게 한다
    session.clear()
    logout_user()
    flash("비밀번호를 변경했습니다. 다시 로그인해 주세요.", "success")
    return redirect(url_for("auth.login"))
