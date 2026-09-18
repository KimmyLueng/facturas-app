# Gestion de Facturas · 西班牙语单据财务管理系统（Windows / macOS / Android）

一个 Windows 桌面应用：**扫描导入西班牙语的进货单（Factura de compra）和出货单（Factura de venta）**，
自动识别关键字段并生成**资产负债表（Balance de Situación）**和**利润表（Cuenta de Resultados）**，可导出 PDF。

## 功能

- 📥 **扫描导入**：支持图片（JPG/PNG/BMP）和 PDF 文件，自动 OCR 识别西班牙语文档；
  可自动判断进货/出货方向，或手动指定；识别结果可编辑核对后再入库。
- 💱 **币种识别**：自动识别单据币种（EUR 欧元 / USD 美元 / VES 玻利瓦尔等）
  与单据上标注的汇率（如 `Tasa: 36,50`、`1 USD = 785,07 Bs`）。
- 📄 **单据管理**：列表查看（含币种列）、筛选（方向/日期）、删除、查看 OCR 原文与汇率详情。
- 📊 **财务报表**：按日期范围生成资产负债表与利润表，实时汇总，可导出 PDF；
  金额按**本位币**统一换算（外币单据自动折算后入账）。
- ⚙️ **设置**：期初资本、本位币、**委内瑞拉官方汇率**（在线获取 BCV 汇率或手动填写）、OCR 引擎自检。
- 💰 **店铺收支日报表**：按日期记录 A/B 店营业额（刷卡/委币/美元）、费用开支与营业结余。
- 💸 **店铺支出日报表**：录入工资、加班费、膳食、税金、水电、铺租、市政管理等支出；选择付款方式（银行卡/现金）和币种（VES/USD）后自动归集到合计列。
- 🏭 **供应商往来结算**：记录供应商供货金额（委币）与支付金额，按方式/币种自动拆分为银行转账、现金（委币）、现金（美元）。
- 📒 **财务期初余额**：内置中国小企业会计准则科目表（167 个科目，来自《财务初始余额.xlsx》），
  首次启动自动载入；支持 Excel 式行内编辑录入各科目年初/期初余额，可一键导入《财务初始余额.xlsx》，
  实时校验「借方合计 = 贷方合计」借贷平衡。

## 币种与汇率（委内瑞拉）

- 扫描单据时自动识别币种与单据汇率；可在扫描页手动修正后再入库。
- 报表按**本位币**（默认 USD，可在设置中改为 EUR/VES）统一换算：
  - USD → 本位币：按「1 USD = X 本位币」
  - VES → 本位币：按「单据自带汇率」或「官方汇率（1 USD = X VES）」折成 USD，再折成本位币
- **委内瑞拉官方汇率**：设置页点击「在线获取官方汇率」从委内瑞拉央行（BCV，经 dolarapi 接口）拉取，也可手动填写兜底。汇率缺失的单据会在报表中提示「未换算」。

## 会计模型（简化西班牙 PGC）

- 进货（Compra）：
  借 `Existencias(300)` 存货 + 借 `HP IVA Soportado(472)` 进项税
  贷 `Caja(570)` 现金
- 出货（Venta）：
  借 `Caja(570)` 现金
  贷 `Ventas(700)` 收入 + 贷 `HP IVA Repercutido(477)` 销项税
  并按**加权平均法**结转销售成本：借 `Coste de ventas(610)` 贷 `Existencias(300)`
- 资产负债表：Caja/Bancos、Existencias、HP IVA、Capital、Resultado 等科目自动平衡。
- 利润表：收入 − 销售成本 = 净利润，另附 IVA 净额（负=应交，正=可抵/退）。

## 安装与运行

```powershell
# 1. 安装依赖（Python 3.9+，推荐 3.12）
pip install -r requirements.txt

# 2. 运行
python main.py
```

> 首次执行 OCR 时，PaddleOCR 会自动下载西班牙语模型（约几十 MB），请保持网络畅通。

## 打包为独立 exe

```powershell
# 1. 安装打包工具（仅一次）
pip install pyinstaller

# 2. 运行一键打包脚本（自动收集 PaddleOCR 全部资源，产物在 dist\GestionFacturas\GestionFacturas.exe）
.\build.ps1

# 或手动执行等价命令：
# pyinstaller -w -n GestionFacturas --collect-all paddleocr --collect-all paddle main.py
```

> 打包为 onedir 模式（exe + 同目录 `_internal` 依赖）。Paddle 库较大，首次打包约需 5-10 分钟。
> 数据目录 `data\`（数据库与设置）在 exe 同级自动生成；启动失败会写 `error.log` 到 exe 同级。

## 各平台安装包（Windows / macOS / Android）

| 平台 | 安装包 | 构建命令 | 说明 |
|---|---|---|---|
| Windows | `GestionFacturas-Setup.exe` 或 `GestionFacturas.msi` | `.\build_all.ps1` / `.\build_all.ps1 -Msi` | EXE 包需 Inno Setup 6；MSI 包需 WiX Toolset v3，支持静默部署 |
| macOS | `GestionFacturas.dmg`（内含 .app） | `./build_all.sh macos` | 必须在 Mac 上构建 |
| Android | `app-debug.apk` | `./build_all.sh android` | 需 Android Studio/Gradle，不含 OCR |
| 浏览器 | 免安装 | `python -m app.web.server` | 手机浏览器可用，依赖 `requirements-web.txt` |

详见 [docs/PLATFORMS.md](docs/PLATFORMS.md)。

## 项目结构

```
facturas_app/
├── main.py                # 入口（图形界面）
├── cli.py                 # 无头工具入口（导入/报表/期初余额等，可选）
├── selftest.py            # 自检脚本（无 OCR 依赖）
├── build.ps1              # 一键打包脚本（PyInstaller onedir）
├── requirements.txt
├── app/
│   ├── config.py          # 配置与会计科目（打包后数据目录自动定位到 exe 同级）
│   ├── utils.py           # 金额/日期解析
│   ├── rates.py           # 币种换算 + 委内瑞拉官方汇率在线获取
│   ├── settings.py        # 设置持久化
│   ├── ocr/               # OCR 引擎（PaddleOCR 西语）+ 单据解析器（含币种识别）
│   ├── db/                # SQLite 数据模型（含科目表 chart_of_accounts / 期初余额 opening_balances）
│   ├── accounting/        # 报表引擎 + PDF 导出
│   ├── sync/              # WebDAV 数据同步（webdav 客户端 + 同步管理器）
│   ├── web/               # Flask Web 界面（浏览器 / Android 内嵌）
│   └── ui/                # tkinter 界面（扫描/单据/报表/收支/支出/供应商结算/期初余额/设置/同步）
├── platforms/             # 各平台打包工程（windows / macos / android）
├── data/                  # SQLite 数据库与设置（自动生成）；chart_of_accounts.json 首次启动自动载入
└── dist/                  # 打包产物（exe / dmg / 安装包）
```

## 提示

- 扫描件请尽量清晰、端正、光线均匀，识别率更高。
- OCR 识别字段可能含误差，入库前请核对表单（金额、日期、NIF 等）。
- 报表基于已入库单据实时计算；删除单据后报表自动更新。
