#!/usr/bin/env bash
# ============================================================
#  跨平台构建入口（macOS / Linux / Android / Web）
#    ./build_all.sh macos            # 打包 .app + .dmg（含 OCR）
#    ./build_all.sh macos --no-ocr   # 不含 OCR（体积小）
#    ./build_all.sh android          # 打包 APK（需 Android SDK）
#    ./build_all.sh web              # 直接启动 Web 界面
#  Windows 请用:  build_all.ps1
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

case "${1:-macos}" in
    macos|mac|darwin)
        exec "$ROOT/platforms/macos/build_macos.sh" "$2"
        ;;
    android)
        exec "$ROOT/platforms/android/build_android.sh"
        ;;
    web|server)
        cd "$ROOT"
        exec python3 -m app.web.server "${@:2}"
        ;;
    *)
        echo "用法: $0 [macos|android|web] [--no-ocr]"
        exit 1
        ;;
esac
