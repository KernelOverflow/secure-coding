"""파일마켓 Flask 앱을 만들고 공통 설정, 확장 기능, 오류 처리를 연결한다"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from sqlalchemy import event, inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    get_environment_settings,
    load_project_environment,
    validate_host,
    validate_port,
)
from .extensions import csrf, db, limiter, login_manager, socketio
from .models import User
from .security import (
    ValidationError,
    hash_password,
    load_or_create_secret,
    nickname_key,
    normalize_login_id,
    validate_login_id,
    validate_nickname,
    validate_password,
)


def _configure_sqlite(engine) -> None:
    """SQLite 연결마다 무결성과 동시 처리에 필요한 기본 옵션을 적용한다"""
    # PostgreSQL 같은 다른 DB를 사용할 때는 SQLite 전용 명령을 실행하지 않는다
    if engine.url.get_backend_name() != "sqlite":
        return

    def set_pragmas(dbapi_connection, _connection_record) -> None:
        """새 SQLite 연결이 만들어질 때 외래키, WAL, 동기화 수준을 설정한다"""
        cursor = dbapi_connection.cursor()
        # 외래키 관계를 실제로 검사해 존재하지 않는 사용자나 상품 참조를 막는다
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL 모드는 읽기와 쓰기가 겹칠 때 잠금 충돌을 줄여 준다
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    # SQLAlchemy가 새 DB 연결을 열 때마다 위 설정 함수를 자동으로 호출한다
    event.listen(engine, "connect", set_pragmas)


def _migrate_legacy_user_identity(engine) -> None:
    """예제 DB의 username 구조를 아이디와 닉네임이 분리된 구조로 안전하게 옮긴다"""
    if engine.url.get_backend_name() != "sqlite":
        return
    inspector = inspect(engine)
    # 처음 실행한 빈 DB라면 마이그레이션할 사용자 테이블이 아직 없으므로 종료한다
    if "user" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("user")}
    # begin 블록 안에서 처리해 중간 실패 시 일부 열만 바뀐 상태로 남는 일을 줄인다
    with engine.begin() as connection:
        # 강의 예제의 username은 로그인 전용 아이디인 login_id로 이름을 바꾼다
        if "username" in columns and "login_id" not in columns:
            connection.execute(text('ALTER TABLE "user" RENAME COLUMN username TO login_id'))
            columns.remove("username")
            columns.add("login_id")
        # 새 버전에 필요한 정규화 아이디와 공개 닉네임 열이 없을 때만 추가한다
        if "login_id_normalized" not in columns:
            connection.execute(
                text('ALTER TABLE "user" ADD COLUMN login_id_normalized VARCHAR(20)')
            )
        if "nickname" not in columns:
            connection.execute(text('ALTER TABLE "user" ADD COLUMN nickname VARCHAR(20)'))
        if "nickname_normalized" not in columns:
            connection.execute(
                text('ALTER TABLE "user" ADD COLUMN nickname_normalized VARCHAR(20)')
            )
        # 기존 DB에도 프로필 이미지 파일명을 보관할 선택 열을 추가한다
        if "profile_image_filename" not in columns:
            connection.execute(
                text('ALTER TABLE "user" ADD COLUMN profile_image_filename VARCHAR(80)')
            )

        # 기존 계정을 가입 순서대로 읽어 각 행에 새 식별값을 채운다
        rows = connection.execute(
            text('SELECT id, login_id, nickname FROM "user" ORDER BY created_at, id')
        ).mappings()
        login_ids: set[str] = set()
        nicknames: set[str] = set()
        for row in rows:
            # 대소문자와 유니코드 표현이 달라도 같은 아이디로 판단하도록 정규화한다
            login_id = str(row["login_id"] or "").strip()
            login_normalized = normalize_login_id(login_id)
            if not login_normalized or login_normalized in login_ids:
                raise RuntimeError("기존 계정의 아이디를 고유하게 마이그레이션할 수 없습니다.")
            login_ids.add(login_normalized)

            # 예전에는 별도 닉네임이 없었으므로 우선 기존 아이디를 표시 이름으로 사용한다
            legacy_nickname = str(row["nickname"] or login_id)
            try:
                nickname = validate_nickname(legacy_nickname, allow_reserved=True)
            except ValidationError:
                # 현재 닉네임 규칙에 맞지 않으면 내부 UUID 일부를 이용한 안전한 이름으로 바꾼다
                nickname = f"회원_{str(row['id'])[:8]}"
            normalized_nickname = nickname_key(nickname)
            if normalized_nickname in nicknames:
                # 기존 사용자끼리 닉네임이 겹치면 UUID 접미사를 붙여 데이터 손실 없이 구분한다
                suffix = f"_{str(row['id'])[:6]}"
                nickname = f"{nickname[: 20 - len(suffix)]}{suffix}"
                normalized_nickname = nickname_key(nickname)
            nicknames.add(normalized_nickname)
            connection.execute(
                text(
                    'UPDATE "user" SET login_id = :login_id, '
                    "login_id_normalized = :login_id_normalized, nickname = :nickname, "
                    "nickname_normalized = :nickname_normalized WHERE id = :user_id"
                ),
                {
                    "login_id": login_id,
                    "login_id_normalized": login_normalized,
                    "nickname": nickname,
                    "nickname_normalized": normalized_nickname,
                    "user_id": row["id"],
                },
            )
        # 정규화 값에 고유 인덱스를 만들어 DB 수준에서도 중복 가입을 차단한다
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_login_id_normalized "
                'ON "user" (login_id_normalized)'
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_nickname_normalized "
                'ON "user" (nickname_normalized)'
            )
        )
        connection.execute(text("DROP INDEX IF EXISTS ix_user_username"))
        connection.execute(
            text('CREATE INDEX IF NOT EXISTS ix_user_login_id ON "user" (login_id)')
        )
        connection.execute(
            text('CREATE INDEX IF NOT EXISTS ix_user_nickname ON "user" (nickname)')
        )


def _migrate_legacy_message_status(engine) -> None:
    """기존 채팅 메시지에 관리자 숨김 처리를 위한 상태 열과 인덱스를 추가한다"""
    if engine.url.get_backend_name() != "sqlite":
        return
    inspector = inspect(engine)
    if "message" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("message")}
    with engine.begin() as connection:
        # 기존 메시지는 계속 보이도록 active 기본값으로 상태 열을 추가한다
        if "status" not in columns:
            connection.execute(
                text(
                    'ALTER TABLE "message" ADD COLUMN status VARCHAR(20) '
                    "NOT NULL DEFAULT 'active'"
                )
            )
        connection.execute(
            text('CREATE INDEX IF NOT EXISTS ix_message_status ON "message" (status)')
        )


def create_app(test_config: dict | None = None) -> Flask:
    """환경설정과 기능별 Blueprint를 연결한 완성된 Flask 앱을 반환한다"""
    # 운영체제 환경변수가 우선이며, 없는 값만 프로젝트 .env에서 읽는다
    load_project_environment()
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="../static",
    )
    # DB, 업로드, 비밀키처럼 Git에 올리지 않을 실행 데이터를 instance 폴더에 보관한다
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    upload_folder = Path(app.instance_path) / "uploads"
    upload_folder.mkdir(parents=True, exist_ok=True)

    # 개발 환경에서만 핫 리로딩과 정적 파일 캐시 해제를 사용하도록 실행 설정을 나눈다
    environment_settings = get_environment_settings(os.environ.get("FLASK_ENV"))
    production = environment_settings["ENVIRONMENT"] == "production"
    secure_cookies = os.environ.get(
        "COOKIE_SECURE", "1" if production else "0"
    ) == "1"
    # 보안, DB, 업로드, 세션, 요청 제한에 사용할 공통 설정을 한 번에 등록한다
    app.config.from_mapping(
        SECRET_KEY=load_or_create_secret(app.instance_path),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", f"sqlite:///{Path(app.instance_path) / 'market.db'}"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"timeout": 30}},
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=6 * 1024 * 1024,
        UPLOAD_FOLDER=str(upload_folder),
        SESSION_COOKIE_NAME="secure_market_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=secure_cookies,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        REMEMBER_COOKIE_NAME="filemarket_remember",
        REMEMBER_COOKIE_DURATION=timedelta(days=30),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=secure_cookies,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_LOGIN_ID_COOKIE_NAME="filemarket_login_id",
        WTF_CSRF_TIME_LIMIT=2 * 60 * 60,
        TRUST_PROXY=os.environ.get("TRUST_PROXY", "0") == "1",
        SERVER_HOST=validate_host(os.environ.get("HOST", DEFAULT_HOST)),
        SERVER_PORT=validate_port(os.environ.get("PORT", DEFAULT_PORT)),
        RATELIMIT_HEADERS_ENABLED=True,
        **environment_settings,
    )
    if test_config:
        # 자동 테스트에서는 임시 DB나 CSRF 설정만 선택적으로 덮어쓸 수 있다
        app.config.update(test_config)

    if app.config["TRUST_PROXY"]:
        # 신뢰하는 프록시 한 단계의 전달 헤더만 실제 접속 정보로 인정한다
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # 위에서 준비한 Flask 확장 객체를 현재 앱에 연결한다
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    socketio.init_app(app, cors_allowed_origins=None)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요합니다."
    login_manager.session_protection = "strong"

    # 앱 컨텍스트 안에서 DB 연결 옵션, 이전 스키마 변환, 테이블 생성을 순서대로 처리한다
    with app.app_context():
        _configure_sqlite(db.engine)
        _migrate_legacy_user_identity(db.engine)
        _migrate_legacy_message_status(db.engine)
        db.create_all()

    # 기능별 라우트는 여기에서 늦게 불러와 순환 import를 피한다
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .chat import bp as chat_bp
    from .products import bp as products_bp
    from .reports import bp as reports_bp
    from .users import bp as users_bp

    # 각 Blueprint를 등록하면 해당 모듈의 URL들이 실제 웹앱에 연결된다
    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp)

    register_commands(app)
    register_handlers(app)

    @app.template_filter("krw")
    def format_krw(value) -> str:
        """정수 금액을 화면에서 읽기 쉬운 원화 문자열로 바꾼다"""
        return f"{int(value or 0):,}원"

    @app.template_filter("product_status")
    def format_product_status(value) -> str:
        """DB의 영문 상품 상태를 모든 화면에서 같은 한국어 문구로 바꾼다"""
        labels = {
            "active": "판매 중",
            "sold": "판매 완료",
            "hidden": "숨김",
            "deleted": "삭제됨",
        }
        return labels.get(str(value), "알 수 없음")

    @app.template_filter("user_status")
    def format_user_status(value) -> str:
        """DB의 영문 회원 상태를 관리자 화면에서 같은 한국어 문구로 바꾼다"""
        labels = {
            "active": "활성",
            "suspended": "임시 정지",
            "banned": "차단",
        }
        return labels.get(str(value), "알 수 없음")

    @app.before_request
    def enforce_active_account():
        """정지 또는 차단된 계정의 기존 로그인 세션을 요청 처리 전에 종료한다"""
        if current_user.is_authenticated and current_user.status != "active":
            logout_user()
            flash("정지되었거나 사용할 수 없는 계정입니다.", "error")
            return redirect(url_for("auth.login"))
        return None

    @app.after_request
    def add_security_headers(response):
        """모든 응답에 브라우저 보안 정책과 민감 화면 캐시 방지 헤더를 추가한다"""
        # CSP는 허용한 출처 외의 스크립트, 객체, 프레임 실행을 차단한다
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.socket.io; "
            "style-src 'self'; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.is_secure:
            # HTTPS로 접속한 경우 이후에도 브라우저가 HTTPS를 사용하도록 알린다
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if response.content_type and response.content_type.startswith("text/html"):
            # 로그인 정보나 잔액이 담긴 HTML을 브라우저와 프록시가 저장하지 않게 한다
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


@login_manager.user_loader
def load_user(user_id: str):
    """세션에 저장된 사용자 ID로 매 요청의 로그인 사용자를 다시 조회한다"""
    return db.session.get(User, user_id)


def register_handlers(app: Flask) -> None:
    """예외별 상태 코드와 사용자 친화적인 공통 오류 화면을 등록한다"""
    @app.errorhandler(400)
    def bad_request(_error):
        """형식이 잘못된 요청에는 내부 예외 대신 400 안내 화면을 보여준다"""
        return render_template("error.html", code=400, message="잘못된 요청입니다."), 400

    @app.errorhandler(ValidationError)
    def validation_error(_error):
        """검증 함수에서 놓친 입력 오류도 안전한 400 응답으로 바꾼다"""
        return render_template("error.html", code=400, message="입력값이 올바르지 않습니다."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        """권한이 없는 접근은 상세 권한 구조를 공개하지 않고 거부한다"""
        return render_template("error.html", code=403, message="접근 권한이 없습니다."), 403

    @app.errorhandler(404)
    def not_found(_error):
        """존재하지 않거나 숨겨야 하는 자원은 같은 404 화면으로 처리한다"""
        return render_template("error.html", code=404, message="페이지를 찾을 수 없습니다."), 404

    @app.errorhandler(413)
    def too_large(_error):
        """설정한 업로드 크기를 넘으면 파일 처리 전에 요청을 거부한다"""
        return render_template("error.html", code=413, message="업로드 파일이 너무 큽니다."), 413

    @app.errorhandler(429)
    def too_many_requests(_error):
        """요청 횟수 제한을 넘긴 사용자에게 재시도 안내를 보여준다"""
        return render_template("error.html", code=429, message="잠시 후 다시 시도해 주세요."), 429

    @app.errorhandler(500)
    def internal_error(_error):
        """예상하지 못한 오류 시 미완료 DB 작업을 취소하고 일반 메시지만 반환한다"""
        db.session.rollback()
        return render_template("error.html", code=500, message="요청을 처리하지 못했습니다."), 500


def register_commands(app: Flask) -> None:
    """DB 초기화와 관리자 생성을 위한 Flask CLI 명령을 등록한다"""
    @app.cli.command("init-db")
    def init_db_command():
        """아직 없는 데이터베이스 테이블을 생성한다"""
        db.create_all()
        click.echo("데이터베이스를 초기화했습니다.")

    @app.cli.command("create-admin")
    @click.option("--login-id", prompt="관리자 아이디")
    @click.option("--nickname", prompt="관리자 닉네임")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_command(login_id: str, nickname: str, password: str):
        """하드코딩 계정 없이 검증된 관리자 계정을 대화형으로 생성한다"""
        try:
            login_id = validate_login_id(login_id)
            nickname = validate_nickname(nickname, allow_reserved=True)
            password = validate_password(password, login_id, nickname)
        except ValidationError as exc:
            # 웹 폼 오류가 아니라 터미널 명령 오류 형식으로 이유를 출력한다
            raise click.ClickException(str(exc)) from exc
        if User.query.filter_by(login_id_normalized=normalize_login_id(login_id)).first():
            raise click.ClickException("이미 존재하는 아이디입니다.")
        if User.query.filter_by(nickname_normalized=nickname_key(nickname)).first():
            raise click.ClickException("이미 존재하는 닉네임입니다.")
        # 비밀번호 원문은 저장하지 않고 Argon2id 해시만 User 모델에 담는다
        admin = User(
            login_id=login_id,
            login_id_normalized=normalize_login_id(login_id),
            nickname=nickname,
            nickname_normalized=nickname_key(nickname),
            password_hash=hash_password(password),
            role="admin",
            balance_krw=1_000_000,
        )
        db.session.add(admin)
        db.session.flush()
        # flush로 관리자 UUID를 받은 뒤 누가 언제 생성됐는지 감사 기록을 남긴다
        from .services import add_audit_log

        add_audit_log("admin.created", "user", admin.id, "CLI 관리자 생성", actor_id=admin.id)
        db.session.commit()
        click.echo(f"관리자 계정 '{nickname}'을(를) 생성했습니다.")
