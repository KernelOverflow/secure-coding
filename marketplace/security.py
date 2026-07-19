"""입력값, 비밀번호, 이미지, 식별자처럼 여러 기능이 공유하는 보안 검증을 제공한다"""

import os
import re
import secrets
import unicodedata
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app, request
from PIL import Image, UnidentifiedImageError


# 허용 문자 목록을 정규식으로 고정해 예상하지 못한 HTML이나 제어 문자가 들어오지 않게 한다
LOGIN_ID_RE = re.compile(r"^[a-z0-9_]{4,20}$")
NICKNAME_RE = re.compile(r"^[A-Za-z0-9_가-힣 ]{2,20}$")
# 비밀번호는 최소 길이뿐 아니라 영문, 숫자, 특수문자를 각각 하나 이상 요구한다
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,128}$")
# 서비스 운영자처럼 보이는 닉네임을 일반 사용자가 선점하지 못하게 예약한다
RESERVED_NICKNAME_PREFIXES = (
    "admin",
    "administrator",
    "filemarket",
    "support",
    "system",
    "관리자",
    "운영자",
    "파일마켓",
)
# 파일 확장자가 아니라 Pillow가 확인한 실제 이미지 형식만 허용한다
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
Image.MAX_IMAGE_PIXELS = 25_000_000
# Argon2id의 시간, 메모리, 병렬 처리 비용을 명시해 빠른 대입 공격 비용을 높인다
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


class ValidationError(ValueError):
    """사용자가 고칠 수 있는 입력 오류를 일반 서버 오류와 구분한다"""

    pass


def load_or_create_secret(instance_path: str) -> str:
    """세션 서명용 비밀키를 환경변수에서 읽거나 안전한 임의 값으로 생성한다"""
    configured = os.environ.get("SECRET_KEY")
    if configured:
        # 짧은 비밀키는 추측 가능성이 커 운영자가 설정했더라도 거부한다
        if len(configured) < 32:
            raise RuntimeError("SECRET_KEY는 32자 이상이어야 합니다.")
        return configured

    secret_path = Path(instance_path) / ".secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        # 재시작할 때 같은 키를 사용해야 기존 로그인 세션을 정상적으로 확인할 수 있다
        return secret_path.read_text(encoding="utf-8").strip()

    # 처음 실행할 때만 예측하기 어려운 키를 만들고 소유자만 읽을 수 있는 권한으로 저장한다
    secret = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(secret_path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret


def normalize_login_id(login_id: str) -> str:
    """유니코드 표현과 대소문자 차이를 통일해 아이디 중복 검사가 우회되지 않게 한다"""
    return unicodedata.normalize("NFKC", login_id or "").strip().casefold()


def validate_login_id(login_id: str) -> str:
    """로그인 아이디가 영문 소문자, 숫자, 밑줄 4~20자 규칙을 따르는지 검사한다"""
    entered = unicodedata.normalize("NFKC", login_id or "").strip()
    value = normalize_login_id(login_id)
    if entered != value or not LOGIN_ID_RE.fullmatch(value):
        raise ValidationError("아이디는 영문 소문자, 숫자, 밑줄로 4~20자여야 합니다.")
    return value


def normalize_nickname(nickname: str) -> str:
    """닉네임의 유니코드와 연속 공백을 통일하고 줄바꿈을 차단한다"""
    value = unicodedata.normalize("NFKC", nickname or "").strip()
    if any(character.isspace() and character != " " for character in value):
        raise ValidationError("닉네임에는 줄바꿈이나 제어 문자를 사용할 수 없습니다.")
    return re.sub(r" {2,}", " ", value)


def nickname_key(nickname: str) -> str:
    """화면 표시값은 유지하면서 중복 비교에 사용할 닉네임 키를 만든다"""
    return normalize_nickname(nickname).casefold()


def validate_nickname(nickname: str, *, allow_reserved: bool = False) -> str:
    """닉네임의 문자와 길이를 검사하고 관리자 사칭 이름을 차단한다"""
    value = normalize_nickname(nickname)
    if not NICKNAME_RE.fullmatch(value):
        raise ValidationError(
            "닉네임은 한글, 영문, 숫자, 밑줄, 공백으로 2~20자여야 합니다."
        )
    # 밑줄이나 공백을 끼워 넣어 예약어 검사를 우회하지 못하도록 제거한 뒤 비교한다
    compact = re.sub(r"[_ ]", "", value.casefold())
    if not allow_reserved and compact.startswith(RESERVED_NICKNAME_PREFIXES):
        raise ValidationError("관리자나 서비스 운영자를 사칭하는 닉네임은 사용할 수 없습니다.")
    return value


def validate_password(password: str, login_id: str = "", nickname: str = "") -> str:
    """비밀번호 조합을 확인하고 아이디나 닉네임이 그대로 포함되는 것을 막는다"""
    value = password or ""
    if not PASSWORD_RE.fullmatch(value):
        raise ValidationError("비밀번호는 영문, 숫자, 특수문자를 포함해 8~128자여야 합니다.")
    if login_id and normalize_login_id(login_id) in value.casefold():
        raise ValidationError("비밀번호에 아이디를 포함할 수 없습니다.")
    if nickname and nickname_key(nickname) in value.casefold():
        raise ValidationError("비밀번호에 닉네임을 포함할 수 없습니다.")
    return value


def hash_password(password: str) -> str:
    """비밀번호 원문을 복구할 수 없는 Argon2id 해시 문자열로 바꾼다"""
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """입력 비밀번호가 저장된 해시와 같은지 확인하고 잘못된 해시는 False로 처리한다"""
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_password_rehash(password_hash: str) -> bool:
    """보안 비용 설정이 바뀌었을 때 다음 로그인에서 해시를 갱신할지 판단한다"""
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def parse_positive_krw(raw_value: str, maximum: int = 1_000_000_000) -> int:
    """사용자 입력 금액을 소수점 없는 양의 원화 정수로 변환하고 상한을 검사한다"""
    value = (raw_value or "").strip()
    if not value.isdecimal():
        raise ValidationError("금액은 1원 이상의 정수로 입력해 주세요.")
    amount = int(value)
    if amount < 1 or amount > maximum:
        raise ValidationError(f"금액은 1원 이상 {maximum:,}원 이하여야 합니다.")
    return amount


def validate_uuid(raw_value: str, field_name: str = "식별자") -> str:
    """URL과 폼에서 받은 식별자가 올바른 UUID인지 검사하고 표준 문자열로 반환한다"""
    try:
        return str(uuid.UUID(raw_value or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"올바르지 않은 {field_name}입니다.") from exc


def validate_text(raw_value: str, field_name: str, minimum: int, maximum: int) -> str:
    """필수 텍스트의 앞뒤 공백을 제거하고 지정한 길이 범위인지 확인한다"""
    value = (raw_value or "").strip()
    if len(value) < minimum or len(value) > maximum:
        raise ValidationError(f"{field_name}은(는) {minimum}~{maximum}자로 입력해 주세요.")
    return value


def validate_optional_text(
    raw_value: str, field_name: str, minimum: int, maximum: int
) -> str:
    """선택 텍스트는 빈 값을 허용하되 입력했다면 지정한 길이 범위를 적용한다"""
    value = (raw_value or "").strip()
    if not value:
        return ""
    if len(value) < minimum or len(value) > maximum:
        raise ValidationError(
            f"{field_name}은(는) 비워 두거나 {minimum}~{maximum}자로 입력해 주세요."
        )
    return value


def save_uploaded_image(file_storage) -> str | None:
    """상품과 프로필 업로드를 실제 이미지로 확인한 뒤 안전하게 저장한다"""
    if not file_storage or not file_storage.filename:
        return None

    # 사용자가 입력한 파일명은 경로 조작 위험이 있어 저장 파일명으로 사용하지 않는다
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        # verify로 구조를 먼저 확인한 뒤 스트림을 되감아 실제 픽셀을 다시 읽는다
        image = Image.open(file_storage.stream)
        image.verify()
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("정상적인 이미지 파일만 업로드할 수 있습니다.") from exc

    # 확장자를 위장해도 이미지 내부에서 확인한 format이 허용 목록에 없으면 거부한다
    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("JPEG, PNG, WebP 이미지만 업로드할 수 있습니다.")
    if image.width > 5000 or image.height > 5000:
        raise ValidationError("이미지 가로와 세로는 각각 5,000픽셀 이하여야 합니다.")

    # UUID 파일명으로 덮어쓰기와 원본 파일명 노출을 막는다
    extension = ALLOWED_IMAGE_FORMATS[image.format]
    filename = f"{uuid.uuid4()}{extension}"
    destination = upload_dir / filename
    # 서버가 이미지를 다시 인코딩해 EXIF 같은 불필요한 메타데이터와 숨은 내용을 제거한다
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


def save_product_image(file_storage) -> str | None:
    """상품 사진을 공통 이미지 검증 과정으로 저장한다"""
    return save_uploaded_image(file_storage)


def save_profile_image(file_storage) -> str | None:
    """프로필 사진을 공통 이미지 검증 과정으로 저장한다"""
    return save_uploaded_image(file_storage)


def delete_uploaded_image(filename: str | None) -> None:
    """DB에서 더 이상 사용하지 않는 UUID 이미지 파일만 안전하게 삭제한다"""
    if not filename or Path(filename).name != filename:
        return
    # 서버가 만든 UUID 파일명 형식만 허용해 경로 조작을 차단한다
    try:
        identifier = Path(filename).stem
        uuid.UUID(identifier)
    except (ValueError, AttributeError):
        return
    if Path(filename).suffix.lower() not in ALLOWED_IMAGE_FORMATS.values():
        return
    destination = Path(current_app.config["UPLOAD_FOLDER"]) / filename
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        # 파일 정리 실패가 프로필 DB 수정까지 되돌리지는 않게 한다
        current_app.logger.warning("사용하지 않는 이미지를 삭제하지 못했습니다: %s", filename)


def client_ip() -> str:
    """요청 제한과 감사 로그에 사용할 클라이언트 IP를 신뢰 설정에 맞게 가져온다"""
    if current_app.config.get("TRUST_PROXY"):
        # ProxyFix를 명시적으로 켠 환경에서만 첫 번째 전달 IP를 신뢰한다
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return (request.remote_addr or "unknown")[:64]
