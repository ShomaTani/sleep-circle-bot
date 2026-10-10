"""睡眠記録の計算・保存・手入力の解釈・復号。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sleepbot import crypto
from sleepbot.config import JST, MAX_SESSION_HOURS, NAP_THRESHOLD_MINUTES
from sleepbot.db import Database, NewRecord, SleepRecord, User


class InvalidSession(Exception):
    """起床が入眠より前、または長すぎる。時刻は持たない。"""


class InvalidInput(Exception):
    """手入力の形式が違う。メッセージは本人にだけ見せる。"""


@dataclass(frozen=True)
class Computed:
    sleep_date: date
    duration_minutes: int
    is_nap: bool


def compute(bedtime_utc: datetime, waketime_utc: datetime) -> Computed:
    delta = waketime_utc - bedtime_utc
    if delta <= timedelta(0):
        raise InvalidSession("起床が入眠より前になっています")
    if delta >= timedelta(hours=MAX_SESSION_HOURS):
        raise InvalidSession(f"{MAX_SESSION_HOURS}時間以上の睡眠は記録できません")
    minutes = int(delta.total_seconds() // 60)
    return Computed(
        # 1回の睡眠は「起床した日」(JST) の記録
        sleep_date=waketime_utc.astimezone(JST).date(),
        duration_minutes=minutes,
        is_nap=minutes < NAP_THRESHOLD_MINUTES,
    )


def build_record(
    user: User, bedtime_utc: datetime, waketime_utc: datetime, source: str, in_group: bool = False
) -> tuple[NewRecord, Computed]:
    """長さは平文、時刻は本人の公開鍵で暗号化。
    時刻共有ON、またはグループのロールを持つ（グループ内で時刻が共有される）ときだけ平文の時刻も持たせる。"""
    c = compute(bedtime_utc, waketime_utc)
    plain = user.share_times or in_group
    rec = NewRecord(
        discord_id=user.discord_id,
        sleep_date=c.sleep_date,
        duration_minutes=c.duration_minutes,
        is_nap=c.is_nap,
        encrypted_times=crypto.seal_times(user.public_key, bedtime_utc, waketime_utc),
        public_bedtime_utc=bedtime_utc if plain else None,
        public_waketime_utc=waketime_utc if plain else None,
        source=source,
    )
    return rec, c


def save_sleep(
    db: Database, user: User, bedtime_utc: datetime, waketime_utc: datetime, source: str, in_group: bool = False
) -> Computed:
    rec, c = build_record(user, bedtime_utc, waketime_utc, source, in_group)
    db.add_record(rec)
    return c


# ---- 手入力（/edit）


_HHMM = re.compile(r"^\s*(\d{1,2})[:：](\d{2})\s*$")


def parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise InvalidInput("日付は YYYY-MM-DD の形で入れてね（例: 2026-10-08）") from None


def _parse_hhmm(raw: str, label: str) -> time:
    m = _HHMM.match(raw)
    if not m or not (0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59):
        raise InvalidInput(f"{label}は HH:MM の形で入れてね（例: 23:30）")
    return time(int(m[1]), int(m[2]))


def parse_manual(date_raw: str, bed_raw: str, wake_raw: str, now_utc: datetime) -> tuple[datetime, datetime]:
    """date は起床日（睡眠日）。入眠が起床より遅い時刻なら前日の入眠とみなす。返り値は UTC。"""
    d = parse_date(date_raw)
    bed_t = _parse_hhmm(bed_raw, "入眠時刻")
    wake_t = _parse_hhmm(wake_raw, "起床時刻")
    wake = datetime.combine(d, wake_t, JST)
    bed_day = d if bed_t < wake_t else d - timedelta(days=1)
    bed = datetime.combine(bed_day, bed_t, JST)
    if wake > now_utc + timedelta(minutes=5):
        raise InvalidInput("未来の起床時刻は登録できないよ")
    return bed.astimezone(timezone.utc), wake.astimezone(timezone.utc)


# ---- 復号（パスフレーズがあるときだけ）


@dataclass(frozen=True)
class TimedRecord:
    record: SleepRecord
    bedtime_utc: datetime
    waketime_utc: datetime


def decrypt_records(user: User, passphrase: str, records: list[SleepRecord]) -> list[TimedRecord]:
    """重いのでスレッドで呼ぶこと。パスフレーズが違えば crypto.WrongPassphrase。"""
    sk = crypto.unlock_private_key(passphrase, user.encrypted_private_key, user.kdf_salt, user.kdf_params)
    out = []
    for r in records:
        bed, wake = crypto.open_times(sk, r.encrypted_times)
        out.append(TimedRecord(r, bed, wake))
    return out


def format_duration(minutes: int) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h}時間{m}分" if h else f"{m}分"
