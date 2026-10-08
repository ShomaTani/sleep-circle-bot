# sleep-circle-bot

睡眠サークル用の Discord Bot。メンバーがボタンで入眠・起床を記録し、週1回スタッツを共有します。
入眠・起床時刻は本人のパスフレーズでしか復号できない形で保存します。詳しくは [PRIVACY.md](PRIVACY.md)。

**このコードは誰でも読めるように公開しています。** 動いている Bot のバージョンは `/about` で確認できます。

## 進捗

- [x] Phase 1: `/join`、パスフレーズと鍵、プライバシー設定、記録パネル、DB
- [x] Phase 2: `/edit` `/delete` `/privacy` `/leave` `/mystats`（テキスト）
- [x] Phase 3: 週次スタッツの自動投稿とプライバシーテスト
- [ ] Phase 4: カレンダーヒートマップ・睡眠帯グラフ
- [ ] Phase 5: デプロイ手順

## セットアップ

### 1. Bot を作る

1. <https://discord.com/developers/applications> → New Application
2. 左メニュー **Bot** → Reset Token でトークンを控える（`.env` の `DISCORD_TOKEN`）
3. Privileged Gateway Intents は**すべて OFF のまま**でよい（Message Content / Server Members / Presence は使わない）

### 2. サーバーに招待する

左メニュー **OAuth2 → URL Generator** で

- Scopes: `bot`, `applications.commands`
- Bot Permissions:
  - Manage Channels（個人チャンネルの作成・削除）
  - Manage Roles（個人チャンネルの閲覧権限を本人だけにする）
  - View Channels / Send Messages / Read Message History
  - Embed Links / Attach Files（スタッツ画像）
  - Manage Messages、または Pin Messages がある場合はそちら（記録パネルのピン留め）

を選び、生成された URL を開いてサーバーに追加します。

### 3. サーバー側の準備

1. 個人チャンネルを入れるカテゴリを作る（例: `sleep-logs`）。@everyone の「チャンネルを見る」を OFF にしておくと安心
2. 週次スタッツを投稿するチャンネルを作る
3. Discord の設定 → 詳細設定 → 開発者モード を ON にし、サーバー・カテゴリ・チャンネルを右クリック →「ID をコピー」

### 4. `.env`

```
DISCORD_TOKEN=（Bot のトークン）
GUILD_ID=（サーバー ID）
STATS_CHANNEL_ID=（週次スタッツを投稿するチャンネル ID）
CATEGORY_ID=（個人チャンネルを入れるカテゴリ ID）
DATABASE_PATH=data/sleep.db
INCLUDE_NAPS_IN_TOTAL=false
```

`.env` は git に入れないでください（`.gitignore` 済み）。

### 5. 起動

Python 3.11 または 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sleepbot
```

### テスト

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

### 週次スタッツの確認（投稿はしない）

```bash
python -m sleepbot.weekly            # 今週月曜に投稿される内容
python -m sleepbot.weekly 2026-10-12 # その日を含む週の月曜に投稿される内容
```

毎週月曜 8:00（JST）に前週（月〜日）分を `STATS_CHANNEL_ID` に投稿します。
Bot が止まっていて 8:00 を逃した場合は、その週のうちに起動した時点で投稿します。投稿済みの週は DB に記録するので、再起動しても二重投稿しません。

## 使い方（メンバー向け）

| 操作 | 内容 |
|---|---|
| `/join` | パスフレーズを決めて参加。自分だけが見えるチャンネル `sleep-<名前>` ができる |
| 😴 おやすみ / ☀️ おはよう | 個人チャンネルのピン留めパネルで押す。返事は自分にだけ見える |
| `/edit date bedtime waketime [add]` | 記録を手入力。`date` は**起きた日**。入眠が起床より遅い時刻なら前日の夜とみなす（例: `2026-10-08 23:30 07:00` → 10/7 23:30〜10/8 7:00）。その日の記録は置き換え、`add:True` なら追加（昼寝など） |
| `/delete date` | その日（起きた日）の記録を削除。確認あり |
| `/privacy` | 時刻を共有するかを変更。共有をやめると、共有用に保存していた時刻はすぐ削除。共有を始めるときは、パスフレーズを入れれば過去分も共有できる |
| `/mystats [week\|month]` | 直近7日／30日の自分のスタッツ。時刻も見るときはパスフレーズを入力 |
| `/leave` | 退会。個人チャンネルと全記録を削除。確認あり |
| `/about` | ソースコードと、いま動いているコミット |

返事はすべて本人にだけ見えます（ephemeral）。

## 運用のルール

[PRIVACY.md の「運用のルール」](PRIVACY.md#運用のルール運用者が守る約束) を参照。デプロイはこのリポジトリの `main` からだけ行い、`main` への変更はレビュー必須にします。
