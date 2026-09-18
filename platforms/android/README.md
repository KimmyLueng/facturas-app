# Android 版（APK 安装包）

## 原理

Tk 桌面界面无法直接打包成 APK，因此 Android 版采用「内嵌 Web 界面」方案：

```
APK
 ├─ Java：MainActivity 启动 Python → WebView 打开 http://127.0.0.1:8080
 └─ Python（Chaquopy 17 内嵌 CPython 3.12）
     └─ app.web.server（Flask）→ 与桌面端共用 app/db、app/accounting、app/sync
```

业务代码与 Windows / macOS 桌面端**完全一致**（同一套数据库与同步逻辑），只是界面换成移动端网页。
Chaquopy 自 12.0.1 起**免费开源，无需 license key**。

## 三种构建方式

### A. 云端构建（推荐，本机无需装任何 Android 环境）

仓库已有 `.github/workflows/android-apk.yml`：

1. 推送代码到 GitHub
2. **Actions → Android APK → Run workflow**
3. 构建完成后在 Artifacts 下载 `GestionFacturas-debug-apk`
4. 打 tag（`git tag v1.0.0 && git push --tags`）会自动发布到 Release

### B. Android Studio（本机）

用 Android Studio 打开 `platforms/android` 目录 → Build → Build Bundle(s)/APK(s) → Build APK。
首次会自动下载 Gradle、AGP 与 Chaquopy 依赖。

### C. 命令行（本机需 JDK 17 + Android SDK + gradle）

```powershell
# Windows
.\platforms\android\build_android.ps1              # debug APK
.\platforms\android\build_android.ps1 -Release     # release APK
```

```bash
# macOS / Linux
./platforms/android/build_android.sh
```

脚本会自动同步 `app/` → `app/src/main/python/app`，再执行 gradle 构建。

## 环境要求

| 项 | 版本 |
|---|---|
| Chaquopy | 17.0.0（顶层 `build.gradle` 声明） |
| Android Gradle Plugin | 8.2.2（要求 7.3–9.2） |
| Gradle | 8.x |
| JDK | 17 |
| compileSdk / targetSdk / minSdk | 34 / 34 / 24（Chaquopy 要求 ≥24） |
| 本机 Python | **3.12**（须与 `chaquopy.defaultConfig.version` 一致） |

Python 版本不一致会直接构建失败。若本机是 3.11：把 `app/build.gradle` 的
`version = "3.12"` 改为 `"3.11"`，并把 `abiFilters` 改为 `'arm64-v8a','armeabi-v7a','x86_64'`
（3.11 及更早才支持 32 位 ABI）。

Windows 上若报找不到 Python，取消注释并改成自己的路径：

```groovy
buildPython("C:/Users/<你>/AppData/Local/Programs/Python/Python312/python.exe")
// 或
buildPython("py", "-3.12")
```

## 产物

`platforms/android/app/build/outputs/apk/debug/app-debug.apk`
（release：`app/build/outputs/apk/release/app-release.apk`）

正式发布前请在 `app/build.gradle` 的 `buildTypes.release` 中配置自己的 `signingConfig`。

## 功能差异

| 功能 | Windows / macOS | Android |
|---|---|---|
| 单据录入、库存、收入/支出日报、报表、设置 | ✔ | ✔（同一数据库结构） |
| WebDAV 数据同步 | ✔ | ✔ |
| OCR 扫描识别（paddleocr） | ✔ | ✘（Android 不支持，改手工录入） |
| PDF / Excel 导出 | ✔ | 报表页查看；导出请用桌面端 |

## 数据存放

数据库与设置在应用私有目录（`getFilesDir()`，约 `/data/user/0/com.example.gestionfacturas/files`）。
**卸载 App 会删除数据**，请在「同步」页用 WebDAV 上传备份。
