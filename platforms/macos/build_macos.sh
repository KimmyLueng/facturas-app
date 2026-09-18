#!/usr/bin/env bash
# ============================================================
#  macOS 平台构建：.app 应用包 + .dmg 磁盘镜像
#  必须在 macOS 上运行（PyInstaller 不支持交叉编译）
#    ./platforms/macos/build_macos.sh             # 含 OCR
#    ./platforms/macos/build_macos.sh --no-ocr    # 不含 OCR（体积从 ~1GB 降到 ~80MB）
#  产物: dist/GestionFacturas.app
#        dist/GestionFacturas.dmg
# ============================================================
set -e
cd "$(dirname "$0")/../.."
NO_OCR=0
[ "$1" = "--no-ocr" ] && NO_OCR=1

APP_NAME="GestionFacturas"
echo "==> [1/3] 清理旧产物 ..."
rm -rf "dist/$APP_NAME.app" "dist/$APP_NAME" "build/$APP_NAME" "dist/$APP_NAME.dmg"

echo "==> [2/3] PyInstaller 打包 .app ..."
if [ "$NO_OCR" -eq 1 ]; then
    EXCLUDES="--exclude-module paddle --exclude-module paddleocr --exclude-module paddlex \
              --exclude-module paddlepaddle --exclude-module cv2 --exclude-module PyMuPDF"
else
    EXCLUDES="--collect-all paddleocr --collect-all paddlex --collect-all paddle \
              --copy-metadata paddlepaddle --copy-metadata paddlex --copy-metadata paddleocr \
              --copy-metadata opencv-contrib-python --copy-metadata pyclipper \
              --copy-metadata shapely --copy-metadata pypdfium2 --copy-metadata python-bidi \
              --copy-metadata imagesize --copy-metadata safetensors --copy-metadata beautifulsoup4"
fi

# shellcheck disable=SC2086
python3 -m PyInstaller -w -n "$APP_NAME" \
    $EXCLUDES \
    --additional-hooks-dir pyinstaller_hooks \
    --add-data "data/chart_of_accounts.json:data" \
    --osx-bundle-identifier com.example.gestionfacturas \
    --distpath dist --clean main.py

echo "==> [3/3] 生成 dmg ..."
if command -v create-dmg >/dev/null 2>&1; then
    create-dmg --volname "$APP_NAME" --window-size 640 400 \
        --app-drop-link 460 200 "dist/$APP_NAME.dmg" "dist/$APP_NAME.app"
else
    # 没有 create-dmg 时用系统自带 hdiutil（无快捷方式布局，但可直接双击安装）
    hdiutil create -volname "$APP_NAME" -srcfolder "dist/$APP_NAME.app" \
        -ov -format UDZO "dist/$APP_NAME.dmg"
fi

echo "==> 完成："
echo "    app: dist/$APP_NAME.app"
echo "    dmg: dist/$APP_NAME.dmg"
echo "提示：首次打开若被 Gatekeeper 拦截，请「系统设置 → 隐私与安全性 → 仍要打开」。"
