"""「おやすみ」を押した時刻。DB にもログにも書かず、プロセスのメモリにだけ置く。

Bot が再起動すると消える（仕様）。その場合は /edit で手入力してもらう。
"""

from __future__ import annotations

from datetime import datetime


class PendingSleeps:
    def __init__(self) -> None:
        self._bedtimes: dict[int, datetime] = {}

    def __repr__(self) -> str:
        # 誤ってログに出しても中身が出ないように
        return f"<PendingSleeps n={len(self._bedtimes)}>"

    def has(self, discord_id: int) -> bool:
        return discord_id in self._bedtimes

    def start(self, discord_id: int, bedtime_utc: datetime) -> None:
        self._bedtimes[discord_id] = bedtime_utc

    def pop(self, discord_id: int) -> datetime | None:
        return self._bedtimes.pop(discord_id, None)

    def discard(self, discord_id: int) -> None:
        self._bedtimes.pop(discord_id, None)
