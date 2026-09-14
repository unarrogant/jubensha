import json
from datetime import datetime, timezone
from typing import Any


class MysqlRoomStore:
    """Store the latest room snapshot in MySQL.

    MySQL is the durable source for recovery and history. Redis remains the
    low-latency store used by the realtime application path.
    """

    def __init__(self, database_url: str):
        try:
            from sqlalchemy import create_engine, text
        except ImportError as error:
            raise RuntimeError(
                "启用 MySQL 前请安装 sqlalchemy 和 pymysql"
            ) from error

        self._text = text
        self._engine = create_engine(
            database_url,
            pool_pre_ping=True,
            future=True,
        )
        try:
            self._ensure_schema()
        except Exception as error:
            raise RuntimeError(
                "MySQL 连接或初始化失败，请检查 MYSQL_URL、数据库和账号权限"
            ) from error

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS room_snapshots (
                        room_id VARCHAR(64) PRIMARY KEY,
                        script_id VARCHAR(128) NOT NULL,
                        script_version VARCHAR(64) NOT NULL,
                        room_status VARCHAR(32) NOT NULL,
                        payload JSON NOT NULL,
                        updated_at DATETIME(6) NOT NULL
                    )
                    """
                )
            )

    def save(self, room: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        payload = json.dumps(room, ensure_ascii=False, default=str)

        with self._engine.begin() as connection:
            connection.execute(
                self._text(
                    """
                    INSERT INTO room_snapshots
                        (room_id, script_id, script_version, room_status,
                         payload, updated_at)
                    VALUES
                        (:room_id, :script_id, :script_version, :room_status,
                         :payload, :updated_at)
                    ON DUPLICATE KEY UPDATE
                        script_id = VALUES(script_id),
                        script_version = VALUES(script_version),
                        room_status = VALUES(room_status),
                        payload = VALUES(payload),
                        updated_at = VALUES(updated_at)
                    """
                ),
                {
                    "room_id": room["id"],
                    "script_id": room["script_id"],
                    "script_version": room["script_version"],
                    "room_status": room["status"],
                    "payload": payload,
                    "updated_at": now,
                },
            )

    def get(self, room_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                self._text(
                    "SELECT payload FROM room_snapshots WHERE room_id = :room_id"
                ),
                {"room_id": room_id},
            ).mappings().first()

        if row is None:
            return None

        payload = row["payload"]
        if isinstance(payload, str):
            return json.loads(payload)
        return payload

    def list_all(self) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                self._text("SELECT payload FROM room_snapshots")
            ).mappings().all()

        result = []
        for row in rows:
            payload = row["payload"]
            result.append(json.loads(payload) if isinstance(payload, str) else payload)
        return result

    def delete(self, room_id: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                self._text(
                    "DELETE FROM room_snapshots WHERE room_id = :room_id"
                ),
                {"room_id": room_id},
            )
