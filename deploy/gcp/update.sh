#!/bin/bash
# GitHub の main に更新があれば取り込んで再起動する（sleepbot-update.timer から10分ごとに実行）。
# main 以外のコードや、サーバー上で書き換えたコードは動かさない（reset --hard で main に戻す）。
set -euo pipefail
APP=/opt/sleepbot
as_bot() { runuser -u sleepbot -- "$@"; }

cd "$APP"
as_bot git fetch -q origin main
if [ "$(as_bot git rev-parse HEAD)" = "$(as_bot git rev-parse origin/main)" ] && [ -z "$(as_bot git status --porcelain --untracked-files=no)" ]; then
  exit 0
fi
as_bot git reset -q --hard origin/main
as_bot "$APP/.venv/bin/pip" install -q -r requirements.txt
install -m 644 deploy/gcp/sleepbot.service deploy/gcp/sleepbot-update.service deploy/gcp/sleepbot-update.timer /etc/systemd/system/
systemctl daemon-reload
if [ -f "$APP/.env" ]; then
  systemctl restart sleepbot
fi
echo "updated to $(as_bot git rev-parse --short HEAD)"
