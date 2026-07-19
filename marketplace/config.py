"""서버 실행에 필요한 환경변수를 불러오고 안전한 형식인지 확인한다"""

from pathlib import Path

from dotenv import load_dotenv


# 별도 설정이 없을 때는 외부에 공개되지 않는 로컬 주소와 일반 개발 포트를 사용한다
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
VALID_ENVIRONMENTS = {"development", "production"}


def load_project_environment() -> None:
    """프로젝트 루트의 .env를 읽되 이미 설정된 환경변수는 덮어쓰지 않는다"""
    # 현재 파일의 상위 폴더를 기준으로 찾아 어느 경로에서 실행해도 같은 .env를 읽는다
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)


def get_environment_settings(value: str | None) -> dict[str, object]:
    """개발과 운영 환경에 맞는 디버그, 리로더, 캐시 설정을 반환한다"""
    environment = str(value or "development").strip().lower()
    if environment not in VALID_ENVIRONMENTS:
        raise ValueError("FLASK_ENV는 development 또는 production이어야 합니다.")

    # 내부 정보 노출과 예기치 않은 재시작을 막기 위해 개발 환경에서만 편의 기능을 켠다
    development = environment == "development"
    return {
        "ENVIRONMENT": environment,
        "DEBUG": development,
        "USE_RELOADER": development,
        "TEMPLATES_AUTO_RELOAD": development,
        "SEND_FILE_MAX_AGE_DEFAULT": 0 if development else 3600,
    }


def validate_host(value: str) -> str:
    """host를 정리하고 서버 주소로 쓰기 위험한 빈 값과 제어 문자를 거부한다"""
    host = str(value or "").strip()
    # 지나치게 긴 값은 도메인 이름의 일반적인 최대 길이를 넘으므로 받지 않는다
    if not host or len(host) > 253:
        raise ValueError("HOST는 비어 있지 않은 253자 이하의 값이어야 합니다.")
    # 공백과 줄바꿈이 섞이면 로그나 실행 옵션을 혼동시킬 수 있어 차단한다
    if any(character.isspace() or ord(character) < 32 for character in host):
        raise ValueError("HOST에는 공백이나 제어 문자를 사용할 수 없습니다.")
    return host


def validate_port(value: str | int) -> int:
    """문자열 또는 정수로 받은 port를 실제 사용할 수 있는 범위로 검사한다"""
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PORT는 1~65535 사이의 정수여야 합니다.") from exc
    # TCP와 UDP 포트 번호가 가질 수 있는 전체 범위 안에서만 허용한다
    if not 1 <= port <= 65535:
        raise ValueError("PORT는 1~65535 사이의 정수여야 합니다.")
    return port
