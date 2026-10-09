#!/bin/bash
# Google Cloud の VM（Debian 12）で1回だけ実行する初期設定。
#   sudo bash deploy/gcp/setup.sh
# - /opt/sleepbot に GitHub の main を置き、専用ユーザー sleepbot で常時起動する
# - 10分ごとに main を確認し、更新があれば取り込んで再起動する（手元のコードは動かさない）
set -euo pipefail

REPO=https://github.com/ShomaTani/sleep-circle-bot.git
APP=/opt/sleepbot

apt-get update -q
apt-get install -y -q python3-venv git curl

id sleepbot >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin sleepbot
if [ ! -d "$APP/.git" ]; then
  git clone -q "$REPO" "$APP"
fi
mkdir -p "$APP/data"
chown -R sleepbot:sleepbot "$APP"
chmod 700 "$APP/data"

runuser -u sleepbot -- python3 -m venv "$APP/.venv"
runuser -u sleepbot -- "$APP/.venv/bin/pip" install -q --no-cache-dir -r "$APP/requirements.txt"
runuser -u sleepbot -- "$APP/scripts/fetch_font.sh"

# e2-micro はメモリ 1GB なので、念のためスワップを 1GB 足す
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap -q /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

install -m 644 "$APP/deploy/gcp/sleepbot.service" /etc/systemd/system/
install -m 644 "$APP/deploy/gcp/sleepbot-update.service" /etc/systemd/system/
install -m 644 "$APP/deploy/gcp/sleepbot-update.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sleepbot-update.timer

if [ -f "$APP/.env" ]; then
  systemctl enable --now sleepbot
  echo "起動しました: sudo journalctl -u sleepbot -f でログを確認できます"
else
  echo ""
  echo "次に .env を置いてください:"
  echo "  sudo -u sleepbot nano $APP/.env      # 中身を貼って保存"
  echo "  sudo chmod 600 $APP/.env"
  echo "  sudo systemctl enable --now sleepbot"
fi
