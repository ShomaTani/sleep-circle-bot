"""SQLite への保存。

時刻の漏洩を防ぐため次の点に注意している。
- 入眠中の未完了セッションは、サーバー鍵で暗号化して pending_sleeps に一時保存し、起床で消す（pending.py）
- created_at / updated_at は「日付」だけを持つ。ボタン記録の作成時刻＝起床時刻になってしまうため
- secure_delete を有効にし、削除した平文の時刻がファイルの空き領域に残らないようにする
- ジャーナルは WAL を使わない（削除前のページが -wal ファイルに残るのを避ける）
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sleepbot.config import JST

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id            INTEGER PRIMARY KEY,
    display_name          TEXT    NOT NULL,
    channel_id            INTEGER,
    panel_message_id      INTEGER,
    share_times           INTEGER NOT NULL DEFAULT 0,
    share_realtime        INTEGER NOT NULL DEFAULT 0,
    public_key            BLOB    NOT NULL,
    encrypted_private_key BLOB    NOT NULL,
    kdf_salt              BLOB    NOT NULL,
    kdf_params            TEXT    NOT NULL,
    joined_at             TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sleep_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id          INTEGER NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    sleep_date          TEXT    NOT NULL,
    duration_minutes    INTEGER NOT NULL,
    is_nap              INTEGER NOT NULL,
    encrypted_times     BLOB    NOT NULL,
    public_bedtime_utc  TEXT,
    public_waketime_utc TEXT,
    source              TEXT    NOT NULL CHECK (source IN ('button', 'manual')),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_user_date ON sleep_records(discord_id, sleep_date);

-- 「おやすみ」中の入眠時刻。サーバー鍵（PENDING_KEY）で暗号化し、作成時刻などは持たない。
-- 「おはよう」（または上書き・退会）で削除する。再起動しても寝ている人の記録が消えないようにするため
CREATE TABLE IF NOT EXISTS pending_sleeps (
    discord_id INTEGER PRIMARY KEY REFERENCES users(discord_id) ON DELETE CASCADE,
    sealed     BLOB    NOT NULL
);

-- 週次スタッツの二重投稿防止。投稿前に週を「確保」し、失敗したら解放する
CREATE TABLE IF NOT EXISTS weekly_posts (
    week_start TEXT PRIMARY KEY,
    message_id INTEGER
);
"""


@dataclass(frozen=True)
class User:
    discord_id: int
    display_name: str
    channel_id: int | None
    panel_message_id: int | None
    share_times: bool
    public_key: bytes
    encrypted_private_key: bytes
    kdf_salt: bytes
    kdf_params: str
    joined_at: str
    share_realtime: bool = False  # True なら share_times も必ず True


@dataclass(frozen=True)
class SleepRecord:
    id: int
    discord_id: int
    sleep_date: date
    duration_minutes: int
    is_nap: bool
    encrypted_times: bytes
    public_bedtime_utc: datetime | None
    public_waketime_utc: datetime | None
    source: str


@dataclass(frozen=True)
class NewRecord:
    discord_id: int
    sleep_date: date
    duration_minutes: int
    is_nap: bool
    encrypted_times: bytes
    public_bedtime_utc: datetime | None
    public_waketime_utc: datetime | None
    source: str


def _today_jst() -> str:
    return datetime.now(JST).date().isoformat()


class Database:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
        if "share_realtime" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN share_realtime INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.conn.close()

    # ---- users ----

    def add_user(
        self,
        discord_id: int,
        display_name: str,
        public_key: bytes,
        encrypted_private_key: bytes,
        kdf_salt: bytes,
        kdf_params: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO users (discord_id, display_name, share_times, public_key,
                   encrypted_private_key, kdf_salt, kdf_params, joined_at)
               VALUES (?, ?, 0, ?, ?, ?, ?, ?)""",
            (discord_id, display_name, public_key, encrypted_private_key, kdf_salt, kdf_params, _today_jst()),
        )
        self.conn.commit()

    def get_user(self, discord_id: int) -> User | None:
        row = self.conn.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
        return _user(row) if row else None

    def list_users(self) -> list[User]:
        return [_user(r) for r in self.conn.execute("SELECT * FROM users ORDER BY discord_id")]

    def set_channel(self, discord_id: int, channel_id: int) -> None:
        self.conn.execute("UPDATE users SET channel_id = ? WHERE discord_id = ?", (channel_id, discord_id))
        self.conn.commit()

    def set_panel_message(self, discord_id: int, message_id: int) -> None:
        self.conn.execute("UPDATE users SET panel_message_id = ? WHERE discord_id = ?", (message_id, discord_id))
        self.conn.commit()

    def set_privacy(self, discord_id: int, share_times: bool, share_realtime: bool) -> None:
        """公開設定を変える。リアルタイム共有は時刻共有が前提。
        時刻共有をやめたら平文の時刻をすべて消す（暗号化済みの時刻は残る）。"""
        share_realtime = share_realtime and share_times
        with self.conn:
            self.conn.execute(
                "UPDATE users SET share_times = ?, share_realtime = ? WHERE discord_id = ?",
                (int(share_times), int(share_realtime), discord_id),
            )
            if not share_times:
                self.conn.execute(
                    """UPDATE sleep_records SET public_bedtime_utc = NULL, public_waketime_utc = NULL
                       WHERE discord_id = ?""",
                    (discord_id,),
                )
        if not share_times:
            # 空き領域に残った古いページも上書きして消す
            self.conn.execute("VACUUM")

    def set_share_times(self, discord_id: int, share: bool) -> None:
        self.set_privacy(discord_id, share, False)

    def delete_user(self, discord_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM pending_sleeps WHERE discord_id = ?", (discord_id,))
            self.conn.execute("DELETE FROM sleep_records WHERE discord_id = ?", (discord_id,))
            self.conn.execute("DELETE FROM users WHERE discord_id = ?", (discord_id,))
        self.conn.execute("VACUUM")

    # ---- pending_sleeps ----

    def put_pending(self, discord_id: int, sealed: bytes) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO pending_sleeps (discord_id, sealed) VALUES (?, ?)", (discord_id, sealed)
            )

    def get_pending(self, discord_id: int) -> bytes | None:
        row = self.conn.execute("SELECT sealed FROM pending_sleeps WHERE discord_id = ?", (discord_id,)).fetchone()
        return row["sealed"] if row else None

    def delete_pending(self, discord_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM pending_sleeps WHERE discord_id = ?", (discord_id,))

    # ---- weekly_posts ----

    def claim_week(self, week_start: date) -> bool:
        """その週の投稿権を取る。すでに誰か（前回の起動など）が取っていれば False。"""
        with self.conn:
            cur = self.conn.execute("INSERT OR IGNORE INTO weekly_posts (week_start) VALUES (?)", (week_start.isoformat(),))
        return cur.rowcount == 1

    def release_week(self, week_start: date) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM weekly_posts WHERE week_start = ?", (week_start.isoformat(),))

    def mark_week_posted(self, week_start: date, message_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE weekly_posts SET message_id = ? WHERE week_start = ?", (message_id, week_start.isoformat())
            )

    # ---- sleep_records ----

    def add_record(self, rec: NewRecord) -> int:
        with self.conn:
            return self._insert(rec)

    def replace_day(self, rec: NewRecord) -> int:
        """その日の記録をすべて消して rec に置き換える。消した件数を返す。"""
        with self.conn:
            removed = self.conn.execute(
                "DELETE FROM sleep_records WHERE discord_id = ? AND sleep_date = ?",
                (rec.discord_id, rec.sleep_date.isoformat()),
            ).rowcount
            self._insert(rec)
        return removed

    def delete_day(self, discord_id: int, sleep_date: date) -> int:
        with self.conn:
            return self.conn.execute(
                "DELETE FROM sleep_records WHERE discord_id = ? AND sleep_date = ?",
                (discord_id, sleep_date.isoformat()),
            ).rowcount

    def set_public_times(self, times: list[tuple[int, datetime, datetime]]) -> None:
        """(record_id, bedtime_utc, waketime_utc) の平文の時刻を書く。時刻共有ONの人の過去分公開用。"""
        today = _today_jst()
        with self.conn:
            self.conn.executemany(
                """UPDATE sleep_records SET public_bedtime_utc = ?, public_waketime_utc = ?, updated_at = ?
                   WHERE id = ?
                     AND discord_id IN (SELECT discord_id FROM users WHERE share_times = 1)""",
                [(bed.isoformat(), wake.isoformat(), today, rid) for rid, bed, wake in times],
            )

    def _insert(self, rec: NewRecord) -> int:
        today = _today_jst()
        cur = self.conn.execute(
            """INSERT INTO sleep_records (discord_id, sleep_date, duration_minutes, is_nap,
                   encrypted_times, public_bedtime_utc, public_waketime_utc, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.discord_id,
                rec.sleep_date.isoformat(),
                rec.duration_minutes,
                int(rec.is_nap),
                rec.encrypted_times,
                rec.public_bedtime_utc.isoformat() if rec.public_bedtime_utc else None,
                rec.public_waketime_utc.isoformat() if rec.public_waketime_utc else None,
                rec.source,
                today,
                today,
            ),
        )
        return int(cur.lastrowid)

    def list_records(self, discord_id: int, start: date | None = None, end: date | None = None) -> list[SleepRecord]:
        sql = "SELECT * FROM sleep_records WHERE discord_id = ?"
        args: list[object] = [discord_id]
        if start:
            sql += " AND sleep_date >= ?"
            args.append(start.isoformat())
        if end:
            sql += " AND sleep_date <= ?"
            args.append(end.isoformat())
        sql += " ORDER BY sleep_date, id"
        return [_record(r) for r in self.conn.execute(sql, args)]


def _user(row: sqlite3.Row) -> User:
    return User(
        discord_id=row["discord_id"],
        display_name=row["display_name"],
        channel_id=row["channel_id"],
        panel_message_id=row["panel_message_id"],
        share_times=bool(row["share_times"]),
        public_key=row["public_key"],
        encrypted_private_key=row["encrypted_private_key"],
        kdf_salt=row["kdf_salt"],
        kdf_params=row["kdf_params"],
        joined_at=row["joined_at"],
        share_realtime=bool(row["share_realtime"]),
    )


def _record(row: sqlite3.Row) -> SleepRecord:
    bed, wake = row["public_bedtime_utc"], row["public_waketime_utc"]
    return SleepRecord(
        id=row["id"],
        discord_id=row["discord_id"],
        sleep_date=date.fromisoformat(row["sleep_date"]),
        duration_minutes=row["duration_minutes"],
        is_nap=bool(row["is_nap"]),
        encrypted_times=row["encrypted_times"],
        public_bedtime_utc=datetime.fromisoformat(bed) if bed else None,
        public_waketime_utc=datetime.fromisoformat(wake) if wake else None,
        source=row["source"],
    )
