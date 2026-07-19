import argparse

# 다른 모듈에 나누어 둔 앱 생성 함수, 실행값 검증 함수, 웹소켓 객체를 불러오기
from marketplace import create_app
from marketplace.config import validate_host, validate_port
from marketplace.extensions import socketio

# 서버 프로그램 시작점 (Entry Point)
# Flask 웹 애플리케이션을 생성한다. Gunicorn이 app:app 형태로 불러올 때도 이 객체를 사용한다
app = create_app()


def host_argument(value: str) -> str:
    """터미널에서 입력받은 host가 서버 주소로 사용 가능한지 검사한다"""
    try:
        # 검사를 통과하면 앞뒤 공백이 제거된 host를 반환한다
        return validate_host(value)
    except ValueError as exc:
        # 일반 검증 오류를 argparse 전용 오류로 바꾸면 터미널에 사용법과 함께 표시된다
        raise argparse.ArgumentTypeError(str(exc)) from exc


def port_argument(value: str) -> int:
    """터미널에서 입력받은 port가 올바른 포트 번호인지 검사한다"""
    try:
        # 문자열로 입력된 포트를 검증한 뒤 실제 서버가 사용할 정수로 반환한다
        return validate_port(value)
    except ValueError as exc:
        # 숫자가 아니거나 범위를 벗어난 경우 서버를 실행하지 않고 이유를 알려준다
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_arguments() -> argparse.Namespace:
    """실행할 때 사용할 --host와 --port 옵션을 정의하고 입력값을 읽는다"""
    # --help를 실행했을 때 파일마켓 개발 서버라는 설명을 보여준다
    parser = argparse.ArgumentParser(description="파일마켓 개발 서버")

    # 명령행 값이 없으면 .env 또는 앱의 안전한 기본 host를 사용한다
    parser.add_argument(
        "--host",
        type=host_argument,
        default=app.config["SERVER_HOST"],
        help="바인딩할 host (기본값: HOST 환경변수 또는 127.0.0.1)",
    )

    # port도 명령행 값이 가장 우선하며, 없을 때 앱 설정값을 사용한다
    parser.add_argument(
        "--port",
        type=port_argument,
        default=app.config["SERVER_PORT"],
        help="바인딩할 port (기본값: PORT 환경변수 또는 5000)",
    )

    # 검증까지 끝난 host와 port를 하나의 Namespace 객체로 묶어 반환한다
    return parser.parse_args()


# 다른 모듈이 이 파일을 불러올 때는 서버를 자동 실행하지 않고, 직접 실행했을 때만 시작한다
if __name__ == "__main__":
    # 사용자가 터미널에 입력한 실행 옵션을 가져온다
    arguments = parse_arguments()

    # 개발 환경에서만 Werkzeug 서버와 파일 변경 감지 기능을 사용한다
    development = app.config["ENVIRONMENT"] == "development"

    # HTTP 요청과 실시간 Socket.IO 채팅을 함께 처리하는 개발 서버를 실행한다
    socketio.run(
        app,  # 위에서 생성한 Flask 애플리케이션
        host=arguments.host,  # 검증을 마친 접속 주소
        port=arguments.port,  # 검증을 마친 포트 번호
        debug=app.debug,  # 개발 환경에서만 상세 오류 확인 기능을 켠다
        use_reloader=app.config["USE_RELOADER"],  # Python 변경 시 개발 서버를 자동 재시작한다
        allow_unsafe_werkzeug=development,
    )
