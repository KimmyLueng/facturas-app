#!/usr/bin/env bash
# ============================================================
#  Android 构建：把业务代码同步进 Chaquopy 工程并打包 APK
#    ./platforms/android/build_android.sh                 # 同步 + debug APK
#    ./platforms/android/build_android.sh --release       # 同步 + release APK
#    ./platforms/android/build_android.sh --sync-only     # 仅同步源码（CI 用）
#  产物: platforms/android/app/build/outputs/apk/{debug,release}/app-*.apk
# ============================================================
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DEST="$HERE/app/src/main/python"

TASK="assembleDebug"
SYNC_ONLY=0
for a in "$@"; do
    case "$a" in
        --sync-only) SYNC_ONLY=1 ;;
        --release)   TASK="assembleRelease" ;;
    esac
done

echo "==> [1/2] 同步 Python 业务代码 ..."
mkdir -p "$DEST"
rm -rf "$DEST/app"
cp -R "$ROOT/app" "$DEST/app"
find "$DEST/app" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST/app" -name "*.pyc" -delete 2>/dev/null || true
echo "    -> $DEST/app"

if [ "$SYNC_ONLY" = "1" ]; then
    echo "==> --sync-only：仅同步源码，跳过构建"
    exit 0
fi

echo "==> [2/2] 打包 APK ($TASK) ..."
if ! command -v java >/dev/null 2>&1; then
    echo "    未检测到 JDK 17，无法构建： https://adoptium.net/temurin/releases/?version=17"
    echo "    （或用 Android Studio 打开本目录，或改用 GitHub Actions 云端构建）"
    exit 1
fi

if [ "$TASK" = "assembleRelease" ]; then APK_DIR="release"; else APK_DIR="debug"; fi

if [ -x "$HERE/gradlew" ]; then
    (cd "$HERE" && ./gradlew "$TASK")
    echo "    APK: $HERE/app/build/outputs/apk/$APK_DIR/app-$APK_DIR.apk"
elif command -v gradle >/dev/null 2>&1; then
    (cd "$HERE" && gradle "$TASK")
    echo "    APK: $HERE/app/build/outputs/apk/$APK_DIR/app-$APK_DIR.apk"
else
    echo "    未检测到 gradle。请用 Android Studio 打开 platforms/android："
    echo "      Build → Build Bundle(s) / APK(s) → Build APK"
    echo "    （首次打开会自动下载 Gradle 与 Chaquopy 依赖）"
fi
