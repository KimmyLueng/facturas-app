# ============================================================
#  Windows MSI 安装包构建（WiX Toolset v3）
#    .\platforms\windows\build_msi.ps1                 # 完整版（含 OCR，体积大）
#    .\platforms\windows\build_msi.ps1 -NoOcr          # 轻量版（不含 OCR，约 80MB）
#    .\platforms\windows\build_msi.ps1 -Rebuild        # 先重新打包 exe 再生成 MSI
#    .\platforms\windows\build_msi.ps1 -Version 1.2.0  # 指定版本
#  前置：WiX Toolset v3.11 / v3.14   https://github.com/wixtoolset/wix3/releases
#  产物：dist\installer\GestionFacturas.msi
# ============================================================
param(
    [switch]$NoOcr,
    [switch]$Rebuild,
    [string]$Version = "1.0.0"
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Find-WixBin {
    $cmd = Get-Command candle.exe -ErrorAction SilentlyContinue
    if ($cmd) { return Split-Path -Parent $cmd.Source }
    $paths = @(
        "C:\Program Files (x86)\WiX Toolset v3.14\bin",
        "C:\Program Files (x86)\WiX Toolset v3.11\bin",
        "C:\Program Files (x86)\WiX Toolset v3.10\bin",
        "C:\Program Files\WiX Toolset v3.14\bin"
    )
    foreach ($p in $paths) {
        if (Test-Path (Join-Path $p "candle.exe")) { return $p }
    }
    return $null
}

$wix = Find-WixBin
if (-not $wix) {
    Write-Host "==> 未检测到 WiX Toolset v3。" -ForegroundColor Yellow
    Write-Host "    安装后重跑本脚本： https://github.com/wixtoolset/wix3/releases （WiX314.exe）" -ForegroundColor Yellow
    exit 1
}
$heat   = Join-Path $wix "heat.exe"
$candle = Join-Path $wix "candle.exe"
$light  = Join-Path $wix "light.exe"
Write-Host "WiX 目录: $wix" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1) exe 产物
$srcDir = Join-Path $Root "dist\GestionFacturas"
$exe = Join-Path $srcDir "GestionFacturas.exe"
$fileCount = if (Test-Path $srcDir) { (Get-ChildItem $srcDir -Recurse -File).Count } else { 0 }
$needBuild = $Rebuild -or -not (Test-Path $exe) -or $fileCount -lt 100
if ($needBuild) {
    Write-Host "==> [1/4] PyInstaller 打包桌面端 ..." -ForegroundColor Cyan
    if ($NoOcr) {
        python -m PyInstaller -w -n GestionFacturas --clean --noconfirm `
            --additional-hooks-dir pyinstaller_hooks `
            --add-data "data/chart_of_accounts.json;data" `
            --exclude-module paddle --exclude-module paddleocr `
            --exclude-module paddlex --exclude-module paddlepaddle `
            --exclude-module cv2 `
            --distpath dist main.py
    } else {
        python -m PyInstaller --noconfirm GestionFacturas.spec
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "==> PyInstaller 打包失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
        exit $LASTEXITCODE
    }
} else {
    Write-Host "==> [1/4] 复用现有 dist\GestionFacturas（加 -Rebuild 可重新打包）"
}

$msiDir = Join-Path $Root "dist\msi"
$outDir = Join-Path $Root "dist\installer"
New-Item -ItemType Directory -Force -Path $msiDir | Out-Null
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# ---------------------------------------------------------------- 2) 收割文件
Write-Host "==> [2/4] heat 收集文件清单 ..." -ForegroundColor Cyan
$appFiles = Join-Path $msiDir "AppFiles.wxs"
& $heat dir $srcDir -cg AppFiles -dr INSTALLFOLDER -srd -ag -sfrag `
    -var var.SourceDir -out $appFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> heat 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- 3) 编译
Write-Host "==> [3/4] candle 编译 ..." -ForegroundColor Cyan
$product = Join-Path $PSScriptRoot "msi\Product.wxs"
& $candle -nologo -dVersion=$Version "-dSourceDir=$srcDir" `
    -out "$msiDir\" $product $appFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> candle 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- 4) 链接
Write-Host "==> [4/4] light 生成 MSI ..." -ForegroundColor Cyan
$msi = Join-Path $outDir "GestionFacturas.msi"
& $light -nologo -ext WixUIExtension -ext WixUtilExtension `
    -sice:ICE57 -sice:ICE60 -sice:ICE64 -sice:ICE83 `
    -out $msi (Join-Path $msiDir "Product.wixobj") (Join-Path $msiDir "AppFiles.wixobj")
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> light 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

$size = [math]::Round((Get-Item $msi).Length / 1MB, 1)
Write-Host ""
Write-Host "==> 完成：$msi （$size MB）" -ForegroundColor Green
Write-Host "    安装：双击运行；静默部署： msiexec /i GestionFacturas.msi /qn"
