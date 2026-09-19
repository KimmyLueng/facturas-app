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

# 版本号必须是 x.x.x（x.x.x.x 也接受），否则 candle 会报 CNDL0108
if ($Version -notmatch '^\d+\.\d+(\.\d+)?(\.\d+)?$') {
    Write-Host "==> 版本号 '$Version' 非法，回退为 1.0.0" -ForegroundColor Yellow
    $Version = "1.0.0"
}
Write-Host "版本号: $Version" -ForegroundColor Cyan

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
# -sreg：不收割 SelfReg 信息（PyInstaller 产物不是 COM 自注册 DLL，可消掉成百条 HEAT5150 警告）
& $heat dir $srcDir -cg AppFiles -dr INSTALLFOLDER -srd -ag -sfrag -sreg `
    -var var.SourceDir -out $appFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> heat 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

# heat 默认按 32 位（Win64 缺省 = no）收割组件，而 Product.wxs 的安装目录是
# ProgramFiles64Folder（64 位目录），二者不匹配会让 light 抛出成百上千条 ICE80。
# 这里统一给收割出的 Component 打上 Win64="yes"，与 Package Platform="x64" 保持一致。
$wxsText = [System.IO.File]::ReadAllText($appFiles, [System.Text.Encoding]::UTF8)
$wxsText = [System.Text.RegularExpressions.Regex]::Replace(
    $wxsText,
    '<Component(?![^>]*\bWin64\s*=)',
    '<Component Win64="yes"')
[System.IO.File]::WriteAllText($appFiles, $wxsText, (New-Object System.Text.UTF8Encoding($false)))
$marked = ([System.Text.RegularExpressions.Regex]::Matches($wxsText, '<Component\b')).Count
Write-Host "    已将 $marked 个组件标记为 Win64（消除 ICE80）" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 3) 编译
Write-Host "==> [3/4] candle 编译 ..." -ForegroundColor Cyan
$product = Join-Path $PSScriptRoot "msi\Product.wxs"
# -ext 必须同时传给 candle：WixUIExtension(WixUI_InstallDir) + WixUtilExtension(util:PermissionEx)
& $candle -nologo "-dVersion=$Version" "-dSourceDir=$srcDir" `
    -ext WixUIExtension -ext WixUtilExtension `
    -out "$msiDir\" $product $appFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> candle 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- 4) 链接
Write-Host "==> [4/4] light 生成 MSI ..." -ForegroundColor Cyan
$msi = Join-Path $outDir "GestionFacturas.msi"
# -sice:ICE80 仅作兜底（组件已全部标为 Win64，正常不会再触发）
& $light -nologo -ext WixUIExtension -ext WixUtilExtension `
    -sice:ICE57 -sice:ICE60 -sice:ICE64 -sice:ICE83 -sice:ICE80 `
    -out $msi (Join-Path $msiDir "Product.wixobj") (Join-Path $msiDir "AppFiles.wixobj")
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> light 失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

$size = [math]::Round((Get-Item $msi).Length / 1MB, 1)
Write-Host ""
Write-Host "==> 完成：$msi （$size MB）" -ForegroundColor Green
Write-Host "    安装：双击运行；静默部署： msiexec /i GestionFacturas.msi /qn"
