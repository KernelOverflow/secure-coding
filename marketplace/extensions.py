"""여러 기능 모듈에서 함께 사용할 Flask 확장 객체를 한곳에 모아 둔다"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


# 객체만 먼저 만들고 실제 Flask 앱 연결은 create_app에서 수행한다
# 이렇게 하면 순환 import를 피하고 테스트마다 별도의 앱을 연결할 수 있다
db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
# API와 로그인 시도를 과도하게 반복하지 못하도록 요청 횟수 제한기를 준비한다
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
# HTTP 세션과 로그인 정보를 그대로 이용하도록 Socket.IO의 별도 세션 관리를 끈다
socketio = SocketIO(async_mode="threading", manage_session=False)
