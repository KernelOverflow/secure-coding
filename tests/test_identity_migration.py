"""강의 예제의 username DB가 아이디와 닉네임 구조로 자동 변환되는지 확인한다"""

from sqlalchemy import create_engine, inspect, text

from marketplace import _migrate_legacy_message_status, _migrate_legacy_user_identity


def test_legacy_username_schema_migrates_to_login_id_and_nickname(tmp_path):
    """기존 값 보존, 새 열, 고유 인덱스와 DB 무결성을 함께 확인한다"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "user" ('
                "id VARCHAR(36) PRIMARY KEY, username VARCHAR(20) UNIQUE NOT NULL, "
                "created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                'INSERT INTO "user" (id, username, created_at) '
                "VALUES ('legacy-id', 'legacy_user', '2026-07-19')"
            )
        )

    _migrate_legacy_user_identity(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("user")}
    assert "username" not in columns
    assert {
        "login_id",
        "login_id_normalized",
        "nickname",
        "nickname_normalized",
        "profile_image_filename",
    } <= columns
    with engine.connect() as connection:
        identity = connection.execute(
            text(
                'SELECT login_id, login_id_normalized, nickname, nickname_normalized '
                'FROM "user" WHERE id = :user_id'
            ),
            {"user_id": "legacy-id"},
        ).one()
    assert identity == ("legacy_user", "legacy_user", "legacy_user", "legacy_user")
    engine.dispose()


def test_legacy_message_schema_adds_active_status(tmp_path):
    """기존 채팅 원문을 보존하면서 관리자 관리용 active 상태 열을 추가하는지 확인한다"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-message.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "message" ('
                "id VARCHAR(36) PRIMARY KEY, content VARCHAR(1000) NOT NULL)"
            )
        )
        connection.execute(
            text(
                'INSERT INTO "message" (id, content) '
                "VALUES ('legacy-message', '기존 채팅 원문')"
            )
        )

    _migrate_legacy_message_status(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("message")}
    assert "status" in columns
    with engine.connect() as connection:
        migrated = connection.execute(
            text('SELECT content, status FROM "message" WHERE id = :message_id'),
            {"message_id": "legacy-message"},
        ).one()
    assert migrated == ("기존 채팅 원문", "active")
    engine.dispose()
