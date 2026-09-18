# ============================================================
#  Windows 一键构建
#    .\build_all.ps1                 # 打 exe + Inno Setup 安装包
#    .\build_all.ps1 -NoInstaller    # 只打 exe（绿色版）
#    .\build_all.ps1 -Msi            # 打 exe + MSI 安装包（WiX Toolset v3）
#    .\build_all.ps1 -Msi -NoOcr     # 轻量版 MSI（不含 OCR，约 80MB）
#  其它平台见:  build_all.sh （macOS / Android / Web）
# ============================================================
param(
    [switch]$NoInstaller,
    [switch]$Msi,
    [switch]$NoOcr
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

if ($Msi) {
    & (Join-Path $Root "platforms\windows\build_msi.ps1") -NoOcr:$NoOcr -Rebuild
} else {
    & (Join-Path $Root "platforms\windows\build_windows.ps1") -NoInstaller:$NoInstaller
}
