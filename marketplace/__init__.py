from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from sqlalchemy import event
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import csrf, db, limiter, login_manager, socketio
from .models import User
from .security import (
    ValidationError,
    hash_password,
    load_or_create_secret,
    validate_password,
    validate_username,
)


def _configure_sqlite(engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    def set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    event.listen(engine, "connect", set_pragmas)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="../static",
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    upload_folder = Path(app.instance_path) / "uploads"
    upload_folder.mkdir(parents=True, exist_ok=True)

    production = os.environ.get("FLASK_ENV", "development") == "production"
    secure_cookies = os.environ.get(
        "COOKIE_SECURE", "1" if production else "0"
    ) == "1"
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
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=secure_cookies,
        WTF_CSRF_TIME_LIMIT=timedelta(hours=2),
        TRUST_PROXY=os.environ.get("TRUST_PROXY", "0") == "1",
        RATELIMIT_HEADERS_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    socketio.init_app(app, cors_allowed_origins=None)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요합니다."
    login_manager.session_protection = "strong"

    with app.app_context():
        _configure_sqlite(db.engine)
        db.create_all()

    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .chat import bp as chat_bp
    from .products import bp as products_bp
    from .reports import bp as reports_bp
    from .users import bp as users_bp

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
        return f"{int(value or 0):,}원"

    @app.before_request
    def enforce_active_account():
        if current_user.is_authenticated and current_user.status != "active":
            logout_user()
            flash("정지되었거나 사용할 수 없는 계정입니다.", "error")
            return redirect(url_for("auth.login"))
        return None

    @app.after_request
    def add_security_headers(response):
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
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if response.content_type and response.content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, user_id)


def register_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", code=400, message="잘못된 요청입니다."), 400

    @app.errorhandler(ValidationError)
    def validation_error(_error):
        return render_template("error.html", code=400, message="입력값이 올바르지 않습니다."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="접근 권한이 없습니다."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="페이지를 찾을 수 없습니다."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code=413, message="업로드 파일이 너무 큽니다."), 413

    @app.errorhandler(429)
    def too_many_requests(_error):
        return render_template("error.html", code=429, message="잠시 후 다시 시도해 주세요."), 429

    @app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()
        return render_template("error.html", code=500, message="요청을 처리하지 못했습니다."), 500


def register_commands(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        click.echo("데이터베이스를 초기화했습니다.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt="관리자 사용자명")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_command(username: str, password: str):
        try:
            username = validate_username(username)
            password = validate_password(password, username)
        except ValidationError as exc:
            raise click.ClickException(str(exc)) from exc
        if User.query.filter_by(username=username).first():
            raise click.ClickException("이미 존재하는 사용자명입니다.")
        admin = User(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            balance_krw=1_000_000,
        )
        db.session.add(admin)
        db.session.flush()
        from .services import add_audit_log

        add_audit_log("admin.created", "user", admin.id, "CLI 관리자 생성", actor_id=admin.id)
        db.session.commit()
        click.echo(f"관리자 계정 '{username}'을(를) 생성했습니다.")
