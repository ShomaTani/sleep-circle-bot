#!/bin/sh
# グラフ用の日本語フォント Noto Sans JP（SIL Open Font License）を fonts/ に取得する。
# Mac ではヒラギノがあれば不要。Linux サーバー（Railway など）では起動前に1回実行する。
set -eu
cd "$(dirname "$0")/.."
mkdir -p fonts
[ -f fonts/NotoSansJP.ttf ] && { echo "fonts/NotoSansJP.ttf は取得済み"; exit 0; }
curl -fsSL -o fonts/NotoSansJP.ttf "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
echo "fonts/NotoSansJP.ttf を取得しました"
