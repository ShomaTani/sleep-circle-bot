"""画像生成（matplotlib）。

pyplot は使わず Figure を直接作る（スレッドから呼んでも状態を共有しないため）。
画像はメモリ上で PNG にして返し、ファイルには書かない。PNG のメタデータも付けない。
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from sleepbot.config import JST  # noqa: E402

WEEKDAYS = "月火水木金土日"

# 色（明るい背景のカードとして描く。Discord のライト／ダーク両方で読める）
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
EMPTY = "#f0efec"
BAR = "#2a78d6"
BAR_NAP = "#86b6ef"
# 睡眠時間の濃淡（青の一色、薄い→濃い）
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
CMAP = LinearSegmentedColormap.from_list("sleep", RAMP)
VMIN_H, VMAX_H = 4.0, 9.0  # 4時間以下は一番薄く、9時間以上は一番濃く

# 睡眠帯グラフの横軸: 18:00 から翌 12:00 まで（18時間）
BAND_START_HOUR = 18
BAND_HOURS = 18

FONT_CANDIDATES = ["Noto Sans JP", "Noto Sans CJK JP", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "IPAexGothic"]


def setup_font() -> str | None:
    """日本語フォントを探して設定する。FONT_PATH → fonts/ → システムの順。"""
    paths = []
    if os.environ.get("FONT_PATH"):
        paths.append(Path(os.environ["FONT_PATH"]))
    paths += sorted((Path(__file__).resolve().parent.parent / "fonts").glob("*.[ot]t[fc]"))
    for p in paths:
        if p.exists():
            font_manager.fontManager.addfont(str(p))
            name = font_manager.FontProperties(fname=str(p)).get_name()
            matplotlib.rcParams["font.family"] = name
            return name
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_CANDIDATES:
        if name in installed:
            matplotlib.rcParams["font.family"] = name
            return name
    return None


FONT = setup_font()


def _text_on(hours: float) -> str:
    """セルの濃さに合わせて文字色を選ぶ。"""
    return "#ffffff" if hours >= 6.5 else TEXT


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=TEXT_2, length=0, labelsize=9)


def to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, facecolor=SURFACE, bbox_inches="tight", metadata={"Software": None})
    return buf.getvalue()


def _color(hours: float):
    return CMAP(min(max((hours - VMIN_H) / (VMAX_H - VMIN_H), 0.0), 1.0))


def _scale_legend(fig: Figure, ax) -> None:
    handles = [Patch(color=_color(h), label=f"{h:g}h") for h in (4, 5, 6, 7, 8, 9)]
    handles.append(Patch(color=EMPTY, label="記録なし"))
    ax.legend(
        handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=len(handles),
        frameon=False, fontsize=8, labelcolor=TEXT_2, handlelength=1.2, columnspacing=1.0,
    )


# ---------------------------------------------------------------- 週次: メンバー×曜日ヒートマップ


def weekly_heatmap(rows: list[tuple[str, dict[date, int]]], start: date) -> Figure:
    """rows: (表示名, 睡眠日→分)。長さだけを描く。"""
    days = [start + timedelta(days=i) for i in range(7)]
    n = max(len(rows), 1)
    fig = Figure(figsize=(7.2, 1.2 + 0.48 * n), facecolor=SURFACE)
    ax = fig.add_subplot()
    _style(ax)
    gap = 0.04
    for r, (_, daily) in enumerate(rows):
        for c, d in enumerate(days):
            m = daily.get(d)
            face = EMPTY if m is None else _color(m / 60)
            ax.add_patch(Rectangle((c + gap, r + gap), 1 - 2 * gap, 1 - 2 * gap, facecolor=face, edgecolor="none"))
            if m is not None:
                ax.text(c + 0.5, r + 0.5, f"{m / 60:.1f}", ha="center", va="center", fontsize=10, color=_text_on(m / 60))
    ax.set_xlim(0, 7)
    ax.set_ylim(n, 0)
    ax.set_xticks([i + 0.5 for i in range(7)], [f"{WEEKDAYS[d.weekday()]}\n{d.month}/{d.day}" for d in days])
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(rows))], [name for name, _ in rows])
    ax.set_title("睡眠時間（時間）", loc="left", color=TEXT, fontsize=12, pad=34)
    _scale_legend(fig, ax)
    return fig


# ---------------------------------------------------------------- 睡眠帯


@dataclass(frozen=True)
class Sleep:
    sleep_date: date  # 起床日
    bedtime_utc: datetime
    waketime_utc: datetime
    is_nap: bool


def _band_span(s: Sleep) -> tuple[float, float] | None:
    """起床日の前日 18:00 を 0 とした時間位置。窓の外なら None。"""
    origin = datetime.combine(s.sleep_date - timedelta(days=1), time(BAND_START_HOUR), JST)
    x0 = (s.bedtime_utc - origin).total_seconds() / 3600
    x1 = (s.waketime_utc - origin).total_seconds() / 3600
    x0, x1 = max(x0, 0.0), min(x1, float(BAND_HOURS))
    return (x0, x1) if x1 > x0 else None


def _draw_bands(ax, sleeps: list[Sleep], days: list[date], show_xlabels: bool) -> bool:
    _style(ax)
    row = {d: i for i, d in enumerate(days)}
    has_nap = False
    for s in sleeps:
        if s.sleep_date not in row:
            continue
        span = _band_span(s)
        if span is None:
            continue
        x0, x1 = span
        has_nap |= s.is_nap
        ax.barh(row[s.sleep_date], x1 - x0, left=x0, height=0.62, color=BAR_NAP if s.is_nap else BAR, linewidth=0)
    ax.set_xlim(0, BAND_HOURS)
    ax.set_ylim(len(days) - 0.5, -0.5)
    ticks = list(range(0, BAND_HOURS + 1, 3))
    ax.set_xticks(ticks, [f"{(BAND_START_HOUR + t) % 24}:00" for t in ticks] if show_xlabels else [])
    ax.set_yticks(range(len(days)), [f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})" for d in days])
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return has_nap


def sleep_bands(panels: list[tuple[str, list[Sleep]]], start: date, end: date, title: str) -> Figure:
    """panels: (見出し, 睡眠のリスト)。縦軸が日付（起床日）、横軸が 18:00〜翌12:00。"""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    per_panel = 0.6 + 0.26 * len(days)
    fig = Figure(figsize=(7.2, 0.6 + per_panel * len(panels)), facecolor=SURFACE)
    axes = fig.subplots(len(panels), 1, squeeze=False, sharex=True)[:, 0]
    any_nap = False
    for i, (ax, (heading, sleeps)) in enumerate(zip(axes, panels)):
        any_nap |= _draw_bands(ax, sleeps, days, show_xlabels=(i == len(panels) - 1))
        if heading:
            ax.set_title(heading, loc="left", color=TEXT, fontsize=10)
    fig.suptitle(title, x=0.02, ha="left", color=TEXT, fontsize=12)
    if any_nap:
        axes[-1].legend(
            handles=[Patch(color=BAR, label="睡眠"), Patch(color=BAR_NAP, label="昼寝")],
            loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=False, fontsize=8, labelcolor=TEXT_2,
        )
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- 個人: カレンダー型ヒートマップ


def month_calendar(daily: dict[date, int], start: date, end: date, title: str) -> Figure:
    """start〜end をカレンダー（月曜始まり）に並べ、各マスに日付と睡眠時間を描く。"""
    first = start - timedelta(days=start.weekday())
    weeks = ((end - first).days // 7) + 1
    fig = Figure(figsize=(7.2, 1.3 + 0.82 * weeks), facecolor=SURFACE)
    ax = fig.add_subplot()
    _style(ax)
    gap = 0.04
    for i in range((end - first).days + 1):
        d = first + timedelta(days=i)
        if d < start:
            continue
        c, r = d.weekday(), (d - first).days // 7
        m = daily.get(d)
        face = EMPTY if m is None else _color(m / 60)
        ax.add_patch(Rectangle((c + gap, r + gap), 1 - 2 * gap, 1 - 2 * gap, facecolor=face, edgecolor="none"))
        ink = TEXT_2 if m is None else _text_on(m / 60)
        label = f"{d.month}/{d.day}" if d.day == 1 or d == start else str(d.day)
        ax.text(c + 0.1, r + 0.12, label, ha="left", va="top", fontsize=8, color=ink)
        if m is not None:
            h, mm = divmod(m, 60)
            ax.text(c + 0.5, r + 0.6, f"{h}:{mm:02d}", ha="center", va="center", fontsize=11, color=ink, weight="bold")
    ax.set_xlim(0, 7)
    ax.set_ylim(weeks, 0)
    ax.set_xticks([i + 0.5 for i in range(7)], list(WEEKDAYS))
    ax.xaxis.tick_top()
    ax.set_yticks([])
    ax.set_title(title, loc="left", color=TEXT, fontsize=12, pad=22)
    _scale_legend(fig, ax)
    return fig
