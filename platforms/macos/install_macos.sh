#!/usr/bin/env bash
# ============================================================
#  macOS 依赖安装（在 Mac 上执行一次）
#    ./platforms/macos/install_macos.sh            # 完整（含 OCR）
#    ./platforms/macos/install_macos.sh --no-ocr   # 不装 OCR（体积小、装得快）
# ============================================================
set -e
cd "$(dirname "$0")/../.."
NO_OCR=0
[ "$1" = "--no-ocr" ] && NO_OCR=1

echo "==> 安装 Python 依赖 ..."
python3 -m pip install --upgrade pip

if [ "$NO_OCR" -eq 1 ]; then
    python3 -m pip install reportlab openpyxl pymupdf Pillow
else
    python3 -m pip install -r requirements.txt
fi

python3 -m pip install pyinstaller

echo "==> 完成。"
echo "下一步： ./platforms/macos/build_macos.sh $([ $NO_OCR -eq 1 ] && echo --no-ocr)"
