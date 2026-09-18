# ============================================================
#  Windows 构建 Android APK
#    .\platforms\android\build_android.ps1              # debug APK
#    .\platforms\android\build_android.ps1 -Release     # release APK（debug 签名）
#    .\platforms\android\build_android.ps1 -Gradle "C:\gradle-8.5\bin\gradle.bat"
#  前置：JDK 17 + Android SDK（platform 34 / build-tools 34）
#  产物：platforms\android\app\build\outputs\apk\debug\app-debug.apk
# ============================================================
param(
    [switch]$Release,
    [string]$Gradle = ""
)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = Resolve-Path (Join-Path $Here "..\..")

# ---------------------------------------------------------------- 1) 同步源码
Write-Host "==> [1/4] 同步 Python 业务代码 ..." -ForegroundColor Cyan
$dest = Join-Path $Here "app\src\main\python"
$target = Join-Path $dest "app"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
Copy-Item (Join-Path $Root "app") $target -Recurse -Force
Get-ChildItem $target -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $target -Recurse -File -Filter "*.pyc" |
    Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "    -> $target" -ForegroundColor Green

# ---------------------------------------------------------------- 2) 环境检测
Write-Host "==> [2/4] 检测构建环境 ..." -ForegroundColor Cyan
$javaHome = $env:JAVA_HOME
$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java -and -not $javaHome) {
    Write-Host "    未检测到 JDK 17。请安装： https://adoptium.net/temurin/releases/?version=17" -ForegroundColor Yellow
    Write-Host "    （或安装 Android Studio，它自带 JDK）" -ForegroundColor Yellow
    exit 1
}
if ($javaHome) { $env:JAVA_HOME = $javaHome; Write-Host "    JAVA_HOME: $javaHome" }
else { Write-Host "    java: $($java.Source)" }

$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) {
    $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $candidate) { $sdk = $candidate }
}
if (-not $sdk -or -not (Test-Path $sdk)) {
    Write-Host "    未检测到 Android SDK。" -ForegroundColor Yellow
    Write-Host "    安装 Android Studio 后把 SDK 路径写入环境变量 ANDROID_HOME，" -ForegroundColor Yellow
    Write-Host "    或创建 platforms\android\local.properties： sdk.dir=C:\\Users\\<你>\\AppData\\Local\\Android\\Sdk" -ForegroundColor Yellow
    exit 1
}
$env:ANDROID_HOME = $sdk
Write-Host "    ANDROID_HOME: $sdk" -ForegroundColor Green

# ---------------------------------------------------------------- 3) 定位 gradle
Write-Host "==> [3/4] 定位 Gradle ..." -ForegroundColor Cyan
$gradlew = Join-Path $Here "gradlew.bat"
if (Test-Path $gradlew) {
    $gradleCmd = $gradlew
} elseif ($Gradle) {
    $gradleCmd = $Gradle
} else {
    $g = Get-Command gradle -ErrorAction SilentlyContinue
    $gradleCmd = if ($g) { $g.Source } else { $null }
}
if (-not $gradleCmd) {
    Write-Host "    未找到 gradle。任选其一：" -ForegroundColor Yellow
    Write-Host "      a) 用 Android Studio 打开 platforms\android（会自动生成 gradlew）" -ForegroundColor Yellow
    Write-Host "      b) 安装 gradle 后加 -Gradle 参数指向 gradle.bat" -ForegroundColor Yellow
    Write-Host "      c) 用 GitHub Actions 云端构建： .github\workflows\android-apk.yml" -ForegroundColor Yellow
    exit 1
}
Write-Host "    gradle: $gradleCmd" -ForegroundColor Green

# ---------------------------------------------------------------- 4) 构建
$task = if ($Release) { "assembleRelease" } else { "assembleDebug" }
Write-Host "==> [4/4] 执行 $task ..." -ForegroundColor Cyan
Set-Location $Here
& $gradleCmd $task
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> 构建失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
    exit $LASTEXITCODE
}

$apkDir = if ($Release) { "app\build\outputs\apk\release" } else { "app\build\outputs\apk\debug" }
$apk = Join-Path $Here (Join-Path $apkDir "app-$(if($Release){'release'}else{'debug'}).apk")
if (Test-Path $apk) {
    $size = [math]::Round((Get-Item $apk).Length / 1MB, 1)
    Write-Host ""
    Write-Host "==> 完成：$apk （$size MB）" -ForegroundColor Green
} else {
    Write-Host "==> 构建结束，但未见 APK（可能未签名）：$apkDir" -ForegroundColor Yellow
}
