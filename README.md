# sleep-circle-bot

睡眠サークル用の Discord Bot。メンバーがボタンで入眠・起床を記録し、週1回スタッツを共有します。
入眠・起床時刻は本人のパスフレーズでしか復号できない形で保存します。詳しくは [PRIVACY.md](PRIVACY.md)。

**このコードは誰でも読めるように公開しています。** 動いている Bot のバージョンは `/about` で確認できます。

## 進捗

- [x] Phase 1: `/join`、パスフレーズと鍵、プライバシー設定、記録パネル、DB
- [x] Phase 2: `/edit` `/delete` `/privacy` `/leave` `/mystats`（テキスト）
- [x] Phase 3: 週次スタッツの自動投稿とプライバシーテスト
- [x] Phase 4: カレンダーヒートマップ・睡眠帯グラフ
- [x] Phase 5: デプロイ手順（Google Cloud 無料枠）

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

1. 個人チャンネルを入れるカテゴリを作る（例: `sleep-logs`）
   - カテゴリの「権限」で **Bot のロール（Bot と同じ名前）を追加し、次を ✅ にする**: チャンネルを見る／チャンネルの管理／権限の管理／メッセージを送信／メッセージ履歴を読む／メッセージのピン留め（なければ「メッセージの管理」）／ファイルを添付／埋め込みリンク
   - そのうえで @everyone の「チャンネルを見る」を ❌ にしておくと安心（Bot を許可せずに閉じると `/join` が「権限がない」で失敗します）
2. 週次スタッツを投稿するチャンネルを作る
3. Discord の設定 → 詳細設定 → 開発者モード を ON にし、サーバー・カテゴリ・チャンネルを右クリック →「ID をコピー」

### 4. `.env`

```
DISCORD_TOKEN=（Bot のトークン）
GUILD_ID=（サーバー ID）
STATS_CHANNEL_ID=（週次スタッツを投稿するチャンネル ID）
CATEGORY_ID=（個人チャンネルを入れるカテゴリ ID）
REPORT_CHANNEL_ID=（任意。リアルタイム共有の投稿先チャンネル ID。未設定ならリアルタイム共有は選べない）
GROUPS=（任意。「ロールID:チャンネルID」をカンマ区切り。そのロールを持つ人は、そのチャンネルで時刻まで自動共有）
PENDING_KEY=（おやすみ中の入眠時刻を暗号化して一時保存する鍵。下のコマンドで作る。未設定だと再起動で消える）
PREVIEW_EMPTY_STATS=true（実験フェーズ用。記録がなくても /mystats で空の枠を出す。本番では false）
DATABASE_PATH=data/sleep.db
INCLUDE_NAPS_IN_TOTAL=false
```

`.env` は git に入れないでください（`.gitignore` 済み）。

`PENDING_KEY` の作り方（サーバーごとに別の鍵を作る。DB のバックアップと一緒に置かない）:

```bash
python3 -c "import base64,os;print('PENDING_KEY='+base64.b64encode(os.urandom(32)).decode())"
```

### 5. 起動

Python 3.11 または 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/fetch_font.sh   # グラフ用の日本語フォント（Mac でヒラギノがあれば省略可）
python -m sleepbot
```

フォントは `FONT_PATH` → `fonts/` → システムの Noto Sans JP / ヒラギノ の順に探します。

### テスト

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

### 週次スタッツの確認（投稿はしない）

```bash
python -m sleepbot.weekly            # 今週月曜に投稿される内容
python -m sleepbot.weekly 2026-10-12 # その日を含む週の月曜に投稿される内容（画像は data/preview/ に保存）
```

毎週月曜 8:00（JST）に前週（月〜日）分を `STATS_CHANNEL_ID` に投稿します（`GROUPS` があれば、各グループのチャンネルにグループ内の時刻も）。
毎日 12:00（JST）には、今日起きた分の睡眠時間ランキングを `STATS_CHANNEL_ID` に投稿します。
Bot が止まっていて 8:00 を逃した場合は、その週のうちに起動した時点で投稿します。投稿済みの週は DB に記録するので、再起動しても二重投稿しません。

## Google Cloud で常時動かす（無料枠）

Google Cloud の Always Free 枠の VM（e2-micro）1台で動かします。下の条件を守れば料金はかかりません。

| 項目 | 無料にするための設定 |
|---|---|
| リージョン | `us-west1`（オレゴン）／`us-central1`（アイオワ）／`us-east1`（サウスカロライナ）のどれか |
| マシンタイプ | `e2-micro`（1台だけ） |
| ブートディスク | **標準永続ディスク**（「バランス」は無料枠外）、30GB 以下 |
| その他 | 固定 IP（静的外部 IP）を予約しない。HTTP/HTTPS のファイアウォールは開けない（Bot は外向きの通信だけ） |

### 1. アカウントと VM

1. <https://console.cloud.google.com/> でアカウントを作る（本人確認でカード登録が必要。無料枠内なら請求なし）
2. 「お支払い → 予算とアラート」で予算 ¥100 などのアラートを作っておく（万一の課金にすぐ気づける）
3. 「Compute Engine → VM インスタンス → インスタンスを作成」
   - 名前: `sleepbot`、リージョン: `us-west1`、マシンタイプ: `e2-micro`
   - ブートディスク: 「変更」→ OS **Debian 12**、ディスクの種類 **標準永続ディスク**、サイズ 10GB
   - ファイアウォール: チェックはすべて外したまま
4. 作成後、一覧の「SSH」ボタンでブラウザからログインする

### 2. 初期設定（SSH の画面で実行）

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/ShomaTani/sleep-circle-bot.git
sudo bash sleep-circle-bot/deploy/gcp/setup.sh
```

### 3. `.env` を置いて起動

```bash
sudo -u sleepbot nano /opt/sleepbot/.env   # 手元の .env の中身を貼り付けて保存（Ctrl+O → Enter → Ctrl+X）
sudo chmod 600 /opt/sleepbot/.env
sudo systemctl enable --now sleepbot
sudo journalctl -u sleepbot -f             # 「ready as ...」と出れば成功（Ctrl+C で抜ける）
```

**手元の Mac などで同じトークンの Bot を動かしている場合は、先に止めてください。** 同じ Bot が2つ動くと、ボタンへの応答や週次投稿が重複します。

### 運用

- `main` に push すると、10分以内にサーバーが取り込んで再起動します（`deploy/gcp/update.sh`）。サーバー上でコードを書き換えても、次の確認で `main` に戻ります
- いま動いているコミットは Discord の `/about` で誰でも確認できます
- ログ: `sudo journalctl -u sleepbot -n 100`／再起動: `sudo systemctl restart sleepbot`
- 記録は `/opt/sleepbot/data/sleep.db` にあります

## 使い方（メンバー向け）

| 操作 | 内容 |
|---|---|
| `/join` | パスフレーズを決めて参加。自分だけが見えるチャンネル `sleep-<名前>` ができる |
| 😴 おやすみ / ☀️ おはよう | 個人チャンネルのピン留めパネルで押す。返事は自分にだけ見える |
| `/edit date bedtime waketime [add]` | 記録を手入力。`date` は**起きた日**。入眠が起床より遅い時刻なら前日の夜とみなす（例: `2026-10-08 23:30 07:00` → 10/7 23:30〜10/8 7:00）。その日の記録は置き換え、`add:True` なら追加（昼寝など） |
| `/delete date` | その日（起きた日）の記録を削除。確認あり |
| `/privacy` | 共有の範囲を3段階から選ぶ: 睡眠時間だけ／時刻も（週次スタッツ）／リアルタイムでも（😴 ☀️ を押すと `REPORT_CHANNEL_ID` に「おやすみ」「おきた」と時刻を投稿）。時刻の共有をやめると、共有用に保存していた時刻はすぐ削除。共有を始めるときは、パスフレーズを入れれば過去分も共有できる |
| `/mystats [month:YYYY-MM] [period:week]` | 何も付けなければ今月のスタッツとカレンダー画像。`month:2026-09` でその月、`period:week` で直近7日。パスフレーズを入れると時刻と睡眠帯グラフも。返事は消えるので、見たいときに出し直す |
| `/leave` | 退会。個人チャンネルと全記録を削除。確認あり |
| `/about` | ソースコードと、いま動いているコミット |

返事はすべて本人にだけ見えます（ephemeral）。

## 運用のルール

[PRIVACY.md の「運用のルール」](PRIVACY.md#運用のルール運用者が守る約束) を参照。デプロイはこのリポジトリの `main` からだけ行い、`main` への変更はレビュー必須にします。
