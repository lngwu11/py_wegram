import os
import sqlite3
import threading
from typing import Optional

import config


class MessageStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        with self.lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY,
                    new_msg_id TEXT,
                    msg_type TEXT,
                    from_wxid TEXT,
                    to_wxid TEXT,
                    sender_wxid TEXT,
                    contact_name TEXT,
                    sender_name TEXT,
                    create_time INTEGER,
                    text TEXT,
                    cdn_file TEXT,
                    media_path TEXT,
                    raw_xml TEXT
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(create_time)"
            )
            self.conn.commit()

    def save(self, row: dict) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO messages (
                    msg_id, new_msg_id, msg_type, from_wxid, to_wxid, sender_wxid,
                    contact_name, sender_name, create_time, text, cdn_file, media_path, raw_xml
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(msg_id) DO NOTHING
                """,
                (
                    str(row.get("msg_id") or ""),
                    str(row.get("new_msg_id") or ""),
                    str(row.get("msg_type") or ""),
                    row.get("from_wxid") or "",
                    row.get("to_wxid") or "",
                    row.get("sender_wxid") or "",
                    row.get("contact_name") or "",
                    row.get("sender_name") or "",
                    int(row.get("create_time") or 0),
                    row.get("text") or "",
                    row.get("cdn_file") or "",
                    row.get("media_path") or "",
                    row.get("raw_xml") or "",
                ),
            )
            self.conn.commit()

    def update_names(self, msg_id: str, contact_name: str, sender_name: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE messages SET contact_name=?, sender_name=? WHERE msg_id=?",
                (contact_name or "", sender_name or "", str(msg_id)),
            )
            self.conn.commit()

    def update_media(self, msg_id: str, media_path: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE messages SET media_path=? WHERE msg_id=?",
                (media_path, str(msg_id)),
            )
            self.conn.commit()

    def list_peers(self, kind: str, self_wxid: str) -> list:
        group_sql = "peer LIKE '%@chatroom'" if kind == "group" else "peer NOT LIKE '%@chatroom'"
        sql = f"""
            WITH tagged AS (
                SELECT
                    CASE
                        WHEN from_wxid LIKE '%@chatroom' THEN from_wxid
                        WHEN from_wxid = ? THEN to_wxid
                        ELSE from_wxid
                    END AS peer,
                    text, contact_name, sender_name, create_time, msg_id
                FROM messages
            ),
            latest AS (
                SELECT peer, MAX(create_time) AS create_time, COUNT(*) AS total
                FROM tagged
                WHERE peer != '' AND {group_sql}
                GROUP BY peer
            )
            SELECT t.peer, t.text, t.contact_name, t.sender_name, t.create_time, l.total
            FROM tagged t
            JOIN latest l ON l.peer = t.peer AND l.create_time = t.create_time
            GROUP BY t.peer
            ORDER BY t.create_time DESC
        """
        with self.lock:
            rows = self.conn.execute(sql, (self_wxid,)).fetchall()
        return [dict(row) for row in rows]

    def list_for_peer(self, peer: str, limit: int = 80) -> list:
        limit = min(max(limit, 1), 200)
        if str(peer).endswith("@chatroom"):
            where = "from_wxid = ?"
            args = [peer]
        else:
            where = "(from_wxid = ? OR to_wxid = ?) AND from_wxid NOT LIKE '%@chatroom'"
            args = [peer, peer]
        sql = f"""
            SELECT * FROM (
                SELECT * FROM messages WHERE {where}
                ORDER BY create_time DESC, msg_id DESC
                LIMIT ?
            ) ORDER BY create_time ASC, msg_id ASC
        """
        with self.lock:
            rows = self.conn.execute(sql, args + [limit]).fetchall()
        return [self._public_row(row) for row in rows]

    def list_messages(self, page: int = 1, size: int = 30, keyword: str = "") -> dict:
        page = max(page, 1)
        size = min(max(size, 1), 100)
        offset = (page - 1) * size
        where = ""
        args: list = []
        if keyword:
            where = "WHERE text LIKE ? OR contact_name LIKE ? OR sender_name LIKE ? OR from_wxid LIKE ?"
            like = f"%{keyword}%"
            args = [like, like, like, like]
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM messages {where}", args).fetchone()[0]
            rows = self.conn.execute(
                f"SELECT * FROM messages {where} ORDER BY create_time DESC, msg_id DESC LIMIT ? OFFSET ?",
                args + [size, offset],
            ).fetchall()
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self._public_row(row) for row in rows],
        }

    def get(self, msg_id: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM messages WHERE msg_id=?", (str(msg_id),)
            ).fetchone()
        return self._public_row(row) if row else None

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict:
        item = dict(row)
        media = item.get("media_path") or ""
        item["mediaUrl"] = ("/admin/media/" + media.replace("\\", "/")) if media else ""
        item.pop("raw_xml", None)
        return item


message_store = MessageStore(os.path.join(config.DATA_DIR, "wegram.db"))
