# ============================================================
#  GestionFacturas 一键打包脚本 (Windows PowerShell)
#  前置条件: pip install pyinstaller
#  产物:     dist\GestionFacturas\GestionFacturas.exe
#  用法:     .\build.ps1                # 输出到 dist\GestionFacturas
#            .\build.ps1 -OutDir mydist # 输出到 mydist\GestionFacturas（不删旧产物）
# ============================================================
param(
    [string]$OutDir = "dist"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> 开始打包 GestionFacturas (onedir) ..." -ForegroundColor Cyan
Write-Host "    输出目录: $OutDir\GestionFacturas"

# 用 python 预清理旧产物（shutil 比 PyInstaller 内部删除更可靠，避免文件占用/残留冲突）
python -c "import shutil, sys; shutil.rmtree(r'$OutDir\GestionFacturas', ignore_errors=True); shutil.rmtree(r'build\GestionFacturas', ignore_errors=True)"
if ($LASTEXITCODE -ne 0) { Write-Host "==> 清理旧产物失败" -ForegroundColor Red; exit 1 }

# 用 python -m 调用，兼容 pyinstaller.exe 不在 PATH 的环境
# 必须收集 paddlex（pipeline yaml 配置）与 paddle（动态库），否则 OCR 无法加载
# --copy-metadata: paddlex 依赖检查 (is_extra_available/is_dep_available)
#   通过 importlib.metadata.version() 校验 ocr-core 依赖，缺少 dist-info 会报
#   "A dependency error occurred during pipeline creation"
python -m PyInstaller -w -n GestionFacturas `
    --collect-all paddleocr `
    --collect-all paddlex `
    --collect-all paddle `
    --copy-metadata paddlepaddle `
    --copy-metadata paddlex `
    --copy-metadata paddleocr `
    --copy-metadata opencv-contrib-python `
    --copy-metadata pyclipper `
    --copy-metadata shapely `
    --copy-metadata pypdfium2 `
    --copy-metadata python-bidi `
    --copy-metadata imagesize `
    --copy-metadata safetensors `
    --copy-metadata beautifulsoup4 `
    --additional-hooks-dir pyinstaller_hooks `
    --add-data "data/chart_of_accounts.json;data" `
    --distpath $OutDir `
    --clean `
    main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "==> 打包完成！" -ForegroundColor Green
    Write-Host "    exe : $OutDir\GestionFacturas\GestionFacturas.exe" -ForegroundColor Green
    Write-Host "    数据: 首次运行时在 exe 同级自动生成 data\ 目录（数据库与设置）"
    Write-Host "    提示 : 首次使用 OCR 时需联网下载西班牙语模型 (~/.paddleocr)"
} else {
    Write-Host "==> 打包失败，退出码: $LASTEXITCODE" -ForegroundColor Red
}
