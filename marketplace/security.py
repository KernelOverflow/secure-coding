import os
import re
import secrets
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app, request
from PIL import Image, UnidentifiedImageError


USERNAME_RE = re.compile(r"^[A-Za-z0-9_가-힣]{3,20}$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{10,128}$")
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
Image.MAX_IMAGE_PIXELS = 25_000_000
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


class ValidationError(ValueError):
    pass


def load_or_create_secret(instance_path: str) -> str:
    configured = os.environ.get("SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("SECRET_KEY는 32자 이상이어야 합니다.")
        return configured

    secret_path = Path(instance_path) / ".secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()

    secret = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(secret_path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValidationError("사용자명은 한글, 영문, 숫자, 밑줄로 3~20자여야 합니다.")
    return value


def validate_password(password: str, username: str = "") -> str:
    value = password or ""
    if not PASSWORD_RE.fullmatch(value):
        raise ValidationError("비밀번호는 영문, 숫자, 특수문자를 포함해 10~128자여야 합니다.")
    if username and username.casefold() in value.casefold():
        raise ValidationError("비밀번호에 사용자명을 포함할 수 없습니다.")
    return value


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_password_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def parse_positive_krw(raw_value: str, maximum: int = 1_000_000_000) -> int:
    value = (raw_value or "").strip()
    if not value.isdecimal():
        raise ValidationError("금액은 1원 이상의 정수로 입력해 주세요.")
    amount = int(value)
    if amount < 1 or amount > maximum:
        raise ValidationError(f"금액은 1원 이상 {maximum:,}원 이하여야 합니다.")
    return amount


def validate_uuid(raw_value: str, field_name: str = "식별자") -> str:
    try:
        return str(uuid.UUID(raw_value or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"올바르지 않은 {field_name}입니다.") from exc


def validate_text(raw_value: str, field_name: str, minimum: int, maximum: int) -> str:
    value = (raw_value or "").strip()
    if len(value) < minimum or len(value) > maximum:
        raise ValidationError(f"{field_name}은(는) {minimum}~{maximum}자로 입력해 주세요.")
    return value


def save_product_image(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None

    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        image = Image.open(file_storage.stream)
        image.verify()
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("정상적인 이미지 파일만 업로드할 수 있습니다.") from exc

    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("JPEG, PNG, WebP 이미지만 업로드할 수 있습니다.")
    if image.width > 5000 or image.height > 5000:
        raise ValidationError("이미지 가로와 세로는 각각 5,000픽셀 이하여야 합니다.")

    extension = ALLOWED_IMAGE_FORMATS[image.format]
    filename = f"{uuid.uuid4()}{extension}"
    destination = upload_dir / filename
    if image.format == "JPEG":
        image.convert("RGB").save(destination, "JPEG", quality=88, optimize=True)
    elif image.format == "PNG":
        clean = image.copy()
        clean.info.clear()
        clean.save(destination, "PNG", optimize=True)
    else:
        image.save(destination, "WEBP", quality=88, method=6)
    destination.chmod(0o600)
    return filename


def client_ip() -> str:
    if current_app.config.get("TRUST_PROXY"):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return (request.remote_addr or "unknown")[:64]
