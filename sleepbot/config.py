"""設定は .env（または環境変数）から読む。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

JST = ZoneInfo("Asia/Tokyo")

# 3時間未満の睡眠は昼寝として扱う
NAP_THRESHOLD_MINUTES = 180
# 入眠からこれ以上経って「おはよう」がない記録は無効
MAX_SESSION_HOURS = 20


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    stats_channel_id: int
    category_id: int
    database_path: str
    include_naps_in_total: bool
    report_channel_id: int | None = None  # リアルタイム共有の投稿先（未設定なら無効）
    # 実験フェーズ用: 記録がなくても /mystats で空の枠（画像）を出して見た目を確認できるようにする。
    # 本番では false にして、記録がなければ画像を作らずにメッセージだけ返す
    preview_empty_stats: bool = True


def load_config() -> Config:
    load_dotenv()

    def required(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise SystemExit(f"環境変数 {name} が未設定です（.env.example を参照）")
        return value

    return Config(
        token=required("DISCORD_TOKEN"),
        guild_id=int(required("GUILD_ID")),
        stats_channel_id=int(required("STATS_CHANNEL_ID")),
        category_id=int(required("CATEGORY_ID")),
        database_path=os.environ.get("DATABASE_PATH", "data/sleep.db"),
        include_naps_in_total=os.environ.get("INCLUDE_NAPS_IN_TOTAL", "false").lower() == "true",
        report_channel_id=int(os.environ["REPORT_CHANNEL_ID"]) if os.environ.get("REPORT_CHANNEL_ID", "").strip() else None,
        preview_empty_stats=os.environ.get("PREVIEW_EMPTY_STATS", "true").lower() == "true",
    )
