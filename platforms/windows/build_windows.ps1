# ============================================================
#  Windows 平台构建：PyInstaller exe  +  Inno Setup 安装包
#  用法: .\platforms\windows\build_windows.ps1 [-NoInstaller]
#  产物: dist\GestionFacturas\GestionFacturas.exe
#        dist\installer\GestionFacturas-Setup.exe   （需安装 Inno Setup 6）
# ============================================================
param(
    [switch]$NoInstaller
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "==> [1/2] PyInstaller 打包桌面客户端 ..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm GestionFacturas.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> 打包失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "    exe: dist\GestionFacturas\GestionFacturas.exe" -ForegroundColor Green

if ($NoInstaller) { exit 0 }

Write-Host "==> [2/2] 编译安装包 ..." -ForegroundColor Cyan
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    # Inno Setup 默认安装路径
    $candidate = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) { $iscc = $candidate }
}
if (-not $iscc) {
    Write-Host "    未检测到 Inno Setup 6，跳过安装包。" -ForegroundColor Yellow
    Write-Host "    安装后重跑本脚本即可： https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "    也可直接分发 dist\GestionFacturas 整个目录（绿色版）。" -ForegroundColor Yellow
    exit 0
}
$exe = if ($iscc -is [string]) { $iscc } else { $iscc.Source }
& $exe (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> 安装包编译失败" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "    安装包: dist\installer\GestionFacturas-Setup.exe" -ForegroundColor Green
