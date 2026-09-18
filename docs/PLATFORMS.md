# 跨平台支持与安装包

| 平台 | 界面 | 安装包形态 | 构建环境要求 |
|---|---|---|---|
| Windows | Tk 桌面客户端 | `GestionFacturas.msi`（WiX）或 `-Setup.exe`（Inno Setup） | 本机：Python 3.12 + PyInstaller + WiX；**或云端 Actions** |
| macOS | Tk 桌面客户端 | `GestionFacturas.dmg`（内含 `.app`） | 本机：Mac + Python 3.12；**或云端 Actions**（macOS runner） |
| Android | 内嵌 Web 界面（Flask + WebView） | `app-debug.apk` | 本机：Android Studio + Gradle；**或云端 Actions** |
| 任意浏览器 | Web 界面 | 免安装，直接运行 | Python + Flask（`requirements-web.txt`） |

三端**共用同一套业务代码与数据库结构**（`app/db`、`app/accounting`、`app/sync`），
通过 WebDAV 同步可在三端之间共享同一个账套。

---

## 0. 云端构建（推荐：本机无需安装任何构建工具）

推到 GitHub 后，在 **Actions** 页面手动触发；打 tag 则三端同时构建并发布到 Release。

| 工作流 | 触发方式 | 产物（Artifact） |
|---|---|---|
| Windows MSI | Actions → Windows MSI → Run workflow | `GestionFacturas-windows-msi` → `GestionFacturas.msi` |
| macOS DMG | Actions → macOS DMG → Run workflow | `GestionFacturas-macos-dmg` → `GestionFacturas.dmg` |
| Android APK | Actions → Android APK → Run workflow | `GestionFacturas-debug-apk` → `app-debug.apk` |

```bash
git add . && git commit -m "init"
git remote add origin https://github.com/<用户名>/<仓库>.git
git push -u origin main

git tag v1.0.0 && git push --tags     # 打 tag：三端同时构建 + 发布 Release
```

说明：

- Windows / macOS 默认构建**不含 OCR**（约 80MB）；触发时可勾选 `with_ocr` 打完整版。
- macOS 用 `macos-latest`（Apple Silicon / arm64）。要出 Intel 版，把 `macos-dmg.yml` 的 `runs-on` 改成 `macos-13`。
- Android 版本身不含 OCR；dmg / apk 未签名，首次打开按系统提示允许即可。
- 仓库根目录已加 `.gitattributes`（`*.sh` 强制 LF）与 `.gitignore`，避免脚本换行符和构建产物入仓。

---

## 1. Windows

```powershell
pip install -r requirements.txt
pip install pyinstaller

.\build_all.ps1                 # 打 exe + 安装包
.\build_all.ps1 -NoInstaller    # 只打 exe（绿色版）
```

产物：

- `dist\GestionFacturas\GestionFacturas.exe`（绿色版，可整目录拷贝）
- `dist\installer\GestionFacturas-Setup.exe`（EXE 安装包，需先安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)）

### MSI 安装包（企业部署 / 静默安装）

```powershell
# 前置：安装 WiX Toolset v3.11 或 v3.14
#   https://github.com/wixtoolset/wix3/releases  （WiX314.exe）

.\build_all.ps1 -Msi                 # 完整版 MSI（含 OCR，体积大）
.\build_all.ps1 -Msi -NoOcr          # 轻量版 MSI（不含 OCR，约 80MB，推荐）
```

产物 `dist\installer\GestionFacturas.msi`：

- 安装向导可选安装目录（`WixUI_InstallDir`），默认 `C:\Program Files\GestionFacturas`
- 自动创建开始菜单与桌面快捷方式
- 已给安装目录授予 **Users 写权限**（数据库 `data\` 与设置才能保存）
- 支持覆盖升级（`MajorUpgrade`）
- 静默部署：`msiexec /i GestionFacturas.msi /qn`；卸载：`msiexec /x GestionFacturas.msi /qn`

> 轻量版（`-NoOcr`）不含 PaddleOCR：扫描识别不可用，其余功能完全相同。
> 完整版文件数上万，MSI 打包较慢且体积约 1GB，一般场景建议用轻量版 + 桌面端 OCR。

数据目录规则：绿色版写在 exe 同级 `data\`；用 MSI 装到 `C:\Program Files` 时，
程序会自动改写到 `%LOCALAPPDATA%\GestionFacturas\data`（Program Files 对普通用户只读），
避免在管理员权限下才能记账。

云端构建（本机不必装 WiX）：Actions → **Windows MSI** → Run workflow，见上文「0. 云端构建」。

## 2. macOS

> PyInstaller 不能交叉编译，**下面两步都在 Mac 上执行**。

```bash
# 先赋予脚本执行权限（从 zip / git 拷贝后）
chmod +x platforms/macos/*.sh platforms/android/build_android.sh build_all.sh

# 1) 安装依赖（Apple Silicon 若装不上 paddlepaddle，用 --no-ocr 跳过 OCR）
./platforms/macos/install_macos.sh            # 完整（含 OCR，体积 ~1GB）
./platforms/macos/install_macos.sh --no-ocr   # 不含 OCR，体积 ~80MB

# 2) 打包
./build_all.sh macos                          # 或 ./build_all.sh macos --no-ocr
```

产物：

- `dist/GestionFacturas.app`
- `dist/GestionFacturas.dmg`（有 `create-dmg` 时带拖拽安装布局，否则用 `hdiutil` 生成）

注意：

- 数据目录在 `.app` 包的**同级目录**（`config._app_dir()` 已针对 `Contents/MacOS` 做处理），避免写入应用包内部导致签名校验失败。
- 首次打开若被 Gatekeeper 拦截：系统设置 → 隐私与安全性 → 仍要打开。
- 正式分发建议对 `.app`/`.dmg` 做开发者签名（`codesign`）与公证（`notarytool`）。
- 云端构建（无需 Mac 电脑）：Actions → **macOS DMG** → Run workflow，见上文「0. 云端构建」。

## 3. Android

Tk 界面无法直接打成 APK，Android 版采用 **Chaquopy（内嵌 CPython）+ Flask Web 界面 + WebView** 方案，
业务代码与桌面端完全一致。

三种方式任选（Chaquopy 12.0.1 起免费开源，无需 license key）：

**A. 云端构建（本机无需 JDK / Android SDK）**

```bash
git push                       # 推到 GitHub
# Actions → Android APK → Run workflow → 下载 Artifact GestionFacturas-debug-apk
git tag v1.0.0 && git push --tags    # 打 tag 会自动发布到 Release
```

**B. Android Studio**：打开 `platforms/android` → Build → Build APK

**C. 命令行**（需 JDK 17 + Android SDK + Gradle 8.x + 本机 Python 3.12）

```bash
./build_all.sh android                 # macOS / Linux
.\platforms\android\build_android.ps1  # Windows
```

产物：`platforms/android/app/build/outputs/apk/debug/app-debug.apk`

要点：

- Chaquopy 17 的 DSL 是 `chaquopy { defaultConfig { version = "3.12"; pip { ... } } }`，插件版本在**顶层** `platforms/android/build.gradle` 声明。
- **本机 Python 必须与 `version` 主次版本一致**（当前 3.12），否则构建失败；若本机是 3.11，同时改 `version` 与 `abiFilters`。
- **不含 OCR**（paddlepaddle 在 Android 不可用）→ 单据改为手工录入。
- 数据在应用私有目录，卸载会丢失 → 用「同步」页 WebDAV 备份。
- 详见 `platforms/android/README.md`。

## 4. Web 界面（浏览器 / 局域网 / 手机）

```bash
pip install -r requirements-web.txt
python -m app.web.server                 # http://127.0.0.1:8080
python -m app.web.server --host 0.0.0.0  # 局域网访问（手机也能开）
```

页面：概览、收入日报、支出日报、单据、库存、报表、设置、同步（移动端自适应）。

## 5. 三端共享数据（WebDAV）

任意一端打开「同步」页，填写同一个 WebDAV 目录：

| 服务商 | 地址示例 |
|---|---|
| 坚果云 | `https://dav.jianguoyun.com/dav/`（密码用**应用密码**） |
| Nextcloud | `https://服务器/remote.php/dav/files/用户名/` |
| 群晖 | `https://NAS:5006/` |

- 上传：本机数据库（一致性快照）+ 设置 + 元信息
- 恢复：自动备份本机库到 `data/backups/`
- 冲突：两端都有改动时需手动选择方向（或勾选强制覆盖）

## 6. 构建产物一览

```
dist/
├── GestionFacturas/GestionFacturas.exe      # Windows 绿色版
├── installer/GestionFacturas-Setup.exe      # Windows 安装包
├── GestionFacturas.app                      # macOS 应用包
└── GestionFacturas.dmg                      # macOS 磁盘镜像
platforms/android/app/build/outputs/apk/debug/app-debug.apk
```
