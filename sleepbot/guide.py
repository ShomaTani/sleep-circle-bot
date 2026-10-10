"""新しく参加した人への使い方の案内（/join 直後に個人チャンネルへ送ってピン留め。/guide でも出せる）。"""

from __future__ import annotations

from sleepbot.config import Config

PRIVACY_URL = "https://github.com/ShomaTani/sleep-circle-bot/blob/main/PRIVACY.md"


def guide_text(cfg: Config) -> str:
    stats = f"<#{cfg.stats_channel_id}>"
    extras = [
        f"・毎日 12:00: 今日の睡眠時間ランキング（{stats}）",
        f"・毎週月曜 8:00: 先週のスタッツ（{stats}）",
    ]
    if cfg.groups:
        chans = "／".join(f"<#{g.channel_id}>" for g in cfg.groups)
        extras.append(f"・ロールを持つ人: そのロールのチャンネル（{chans}）で、寝た・起きた時刻と週次の時刻スタッツを自動で共有")
    if cfg.report_channel_id:
        extras.append(f"・`/privacy` でリアルタイム共有を選んだ人: 寝た・起きたを <#{cfg.report_channel_id}> に投稿")

    return "\n".join(
        [
            "**😴 使い方はこれだけ**",
            "このチャンネルのピン留めパネルで、**寝るとき 😴、起きたら ☀️** を押すだけ。",
            "・スタッツが気になったら `/mystats`（今月。`month:2026-09` で過去の月）",
            "・押し忘れ・押しミスは `/edit` で直せる（`date` は起きた日）",
            "・わからなくなったら `/` だけ入力すると、コマンドの一覧が出る",
            "返事はぜんぶ自分にしか見えません。",
            "",
            "**ほかに届くもの**",
            *extras,
            "",
            "**プライバシー**",
            "・全体に出るのは睡眠時間（長さ）だけ。時刻も全体に出すかは `/privacy` で自分で選べる（初期値は出さない）",
            "・共有しない時刻は、あなたのパスフレーズで暗号化して保存。管理者もデータベースからは読めない",
            "・パスフレーズを忘れると、過去の時刻は戻せない（睡眠時間は残る）",
            "・このチャンネルに自分で書いたことは管理者にも見える。ボタンの返事は残らない",
            f"・詳しくは {PRIVACY_URL}",
        ]
    )
