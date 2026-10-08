# sleep-circle-bot

睡眠サークル用の Discord Bot。メンバーがボタンで入眠・起床を記録し、週1回スタッツを共有します。
入眠・起床時刻は本人のパスフレーズでしか復号できない形で保存します。詳しくは [PRIVACY.md](PRIVACY.md)。

**このコードは誰でも読めるように公開しています。** 動いている Bot のバージョンは `/about` で確認できます。

## 進捗

- [x] Phase 1: `/join`、パスフレーズと鍵、プライバシー設定、記録パネル、DB
- [ ] Phase 2: `/edit` `/delete` `/privacy` `/leave` `/mystats`（テキスト）
- [ ] Phase 3: 週次スタッツの自動投稿とプライバシーテスト
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

Python 3.11 以上。

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

## 使い方（メンバー向け）

| 操作 | 内容 |
|---|---|
| `/join` | パスフレーズを決めて参加。自分だけが見えるチャンネル `sleep-<名前>` ができる |
| 😴 おやすみ / ☀️ おはよう | 個人チャンネルのピン留めパネルで押す。返事は自分にだけ見える |
| `/about` | ソースコードと、いま動いているコミット |

## 運用のルール

[PRIVACY.md の「運用のルール」](PRIVACY.md#運用のルール運用者が守る約束) を参照。デプロイはこのリポジトリの `main` からだけ行い、`main` への変更はレビュー必須にします。
