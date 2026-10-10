"""「おやすみ」を押した時刻（起きるまでの一時データ）。

- PENDING_KEY があれば、サーバー鍵（SecretBox）で暗号化して DB の pending_sleeps に置く。
  Bot が再起動しても（push での更新も含む）寝ている人の記録は続く。「おはよう」で DB から消す
- PENDING_KEY がなければ、プロセスのメモリにだけ置く（再起動で消える。/edit で手入力してもらう）

どちらの場合もログには書かない。DB には作成時刻などのメタデータも持たせない。
DB とサーバー鍵（.env）の両方が漏れた場合だけ、その時点で寝ている人の入眠時刻が読める。
"""

from __future__ import annotations

import json
from datetime import datetime

from nacl import secret
from nacl.exceptions import CryptoError

from sleepbot.db import Database


class PendingSleeps:
    def __init__(self, db: Database | None = None, key: bytes | None = None) -> None:
        self._db = db
        self._box = secret.SecretBox(key) if (db is not None and key is not None) else None
        self._memory: dict[int, datetime] = {}

    @property
    def persistent(self) -> bool:
        return self._box is not None

    def __repr__(self) -> str:
        # 誤ってログに出しても中身が出ないように
        return f"<PendingSleeps persistent={self.persistent}>"

    def has(self, discord_id: int) -> bool:
        if self._box is None:
            return discord_id in self._memory
        return self._db.get_pending(discord_id) is not None

    def start(self, discord_id: int, bedtime_utc: datetime) -> None:
        if self._box is None:
            self._memory[discord_id] = bedtime_utc
            return
        payload = json.dumps({"id": discord_id, "bed": bedtime_utc.isoformat()}).encode()
        self._db.put_pending(discord_id, bytes(self._box.encrypt(payload)))

    def peek(self, discord_id: int) -> datetime | None:
        """消さずに見る（/group の「いま寝ている人」用）。"""
        if self._box is None:
            return self._memory.get(discord_id)
        sealed = self._db.get_pending(discord_id)
        if sealed is None:
            return None
        try:
            payload = json.loads(self._box.decrypt(sealed))
        except (CryptoError, ValueError):
            return None
        return datetime.fromisoformat(payload["bed"]) if payload.get("id") == discord_id else None

    def pop(self, discord_id: int) -> datetime | None:
        if self._box is None:
            return self._memory.pop(discord_id, None)
        sealed = self._db.get_pending(discord_id)
        if sealed is None:
            return None
        self._db.delete_pending(discord_id)
        try:
            payload = json.loads(self._box.decrypt(sealed))
        except (CryptoError, ValueError):
            return None  # 鍵が変わった・壊れている → 見つからない扱い（/edit で手入力）
        if payload.get("id") != discord_id:
            return None  # 別の人の行にすり替えられていたら使わない
        return datetime.fromisoformat(payload["bed"])

    def discard(self, discord_id: int) -> None:
        self._memory.pop(discord_id, None)
        if self._db is not None:
            self._db.delete_pending(discord_id)
