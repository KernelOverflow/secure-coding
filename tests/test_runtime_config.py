"""개발 서버의 host와 port 설정 검증이 잘못된 실행값을 거부하는지 확인한다"""

import pytest

from marketplace.config import get_environment_settings, validate_host, validate_port


def test_server_host_and_port_validation():
    """일반 로컬 주소와 문자열 포트가 정리된 값으로 반환되는지 확인한다"""
    assert validate_host(" 127.0.0.1 ") == "127.0.0.1"
    assert validate_host("0.0.0.0") == "0.0.0.0"
    assert validate_port("8000") == 8000


@pytest.mark.parametrize("value", ["", "local host", "host\nname"])
def test_invalid_host_is_rejected(value):
    """빈 host, 공백, 줄바꿈이 포함된 주소를 거부하는지 확인한다"""
    with pytest.raises(ValueError):
        validate_host(value)


@pytest.mark.parametrize("value", ["not-a-number", "0", "65536", "-1"])
def test_invalid_port_is_rejected(value):
    """숫자가 아니거나 허용 범위를 벗어난 포트를 거부하는지 확인한다"""
    with pytest.raises(ValueError):
        validate_port(value)


def test_development_environment_enables_reload_features():
    """개발 환경에서 디버그, 리로더, 템플릿 갱신과 정적 파일 캐시 해제가 켜지는지 확인한다"""
    settings = get_environment_settings("development")
    assert settings["DEBUG"] is True
    assert settings["USE_RELOADER"] is True
    assert settings["TEMPLATES_AUTO_RELOAD"] is True
    assert settings["SEND_FILE_MAX_AGE_DEFAULT"] == 0


def test_production_environment_disables_reload_features():
    """운영 환경에서 디버그와 모든 자동 갱신 기능을 끄고 정적 파일을 캐시하는지 확인한다"""
    settings = get_environment_settings("production")
    assert settings["DEBUG"] is False
    assert settings["USE_RELOADER"] is False
    assert settings["TEMPLATES_AUTO_RELOAD"] is False
    assert settings["SEND_FILE_MAX_AGE_DEFAULT"] == 3600


def test_unknown_environment_is_rejected():
    """오타 난 환경 이름이 개발용 디버그 기능을 실수로 켜지 못하게 거부하는지 확인한다"""
    with pytest.raises(ValueError, match="development 또는 production"):
        get_environment_settings("develop")
