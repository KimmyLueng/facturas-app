"""全局配置：路径、会计科目、默认参数。"""
import os
import sys


def _app_dir() -> str:
    """应用根目录。打包后位于程序包旁；源码运行时位于项目根。

    - Windows exe：数据保存在 exe 所在目录，避免写入临时解压目录而丢失
    - macOS .app：程序在 *.app/Contents/MacOS/ 内，数据写到 .app 同级目录，
      避免写入应用包内部（签名校验 / 只读 / 隔离属性导致失败）
    - Android：由 MainActivity 设置环境变量 FACTURAS_DATA_DIR（应用私有目录）
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        contents_macos = os.path.join("Contents", "MacOS")
        if exe_dir.endswith(contents_macos):
            bundle_dir = os.path.dirname(os.path.dirname(exe_dir))  # .../xxx.app
            return os.path.dirname(bundle_dir)
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    """用户级数据目录：安装到只读位置时用于回退。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or \
            os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or \
            os.path.expanduser("~/.local/share")
    return os.path.join(base, "GestionFacturas")


def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".writetest")
        with open(probe, "w") as fh:
            fh.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def _base_dir() -> str:
    """数据根目录：优先程序所在目录（绿色版），
    装进 Program Files 等只读位置时自动切到用户目录，否则数据库无法创建。"""
    portable = _app_dir()
    if sys.platform == "win32" and "program files" in portable.lower():
        return _user_data_dir()
    if _is_writable(portable):
        return portable
    return _user_data_dir()


# 数据目录（数据库文件所在目录）
# 支持环境变量 FACTURAS_DATA_DIR 覆盖（Docker 挂载数据卷时使用）
APP_DIR = _app_dir()
BASE_DIR = _base_dir()

DATA_DIR = os.environ.get("FACTURAS_DATA_DIR") or os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "facturas.db")

# 无头模式目录：inbox 放待识别单据，out 放报表输出（Docker 挂载卷）
INBOX_DIR = os.environ.get("FACTURAS_INBOX") or os.path.join(BASE_DIR, "inbox")
OUT_DIR = os.environ.get("FACTURAS_OUT") or os.path.join(BASE_DIR, "out")

# OCR 语言：es = 西班牙语
OCR_LANG = "es"

# 默认期初资本（可放入设置）
DEFAULT_CAPITAL = 0.0

# 币种
CURRENCY_EUR = "EUR"
CURRENCY_USD = "USD"
CURRENCY_BS = "Bs"              # 委内瑞拉玻利瓦尔：VES 是 ISO 代码、Bs 是货币符号，同一种货币
CURRENCY_VES = CURRENCY_BS      # 兼容旧代码（历史库里存的 VES）
CURRENCY_CNY = "CNY"            # 人民币
CURRENCY_USDT = "USDT"          # 泰达币稳定币（与美元 1:1 锚定）
DEFAULT_BASE_CURRENCY = "USD"   # 本位币（记账币种），可在设置中修改
CURRENCY_CODES = [CURRENCY_EUR, CURRENCY_USD, CURRENCY_BS, CURRENCY_CNY,
                  CURRENCY_USDT, "MXN", "ARS", "COP"]

# 币种中文名称（各模块下拉统一显示「中文名称（简称）」，库中存代码）
CURRENCY_ZH = {
    CURRENCY_EUR: "欧元",
    CURRENCY_USD: "美元",
    CURRENCY_BS: "玻利瓦尔",
    CURRENCY_CNY: "人民币",
    CURRENCY_USDT: "泰达币",
    "MXN": "墨西哥比索",
    "ARS": "阿根廷比索",
    "COP": "哥伦比亚比索",
    "PEN": "秘鲁索尔",
    "CLP": "智利比索",
    "BRL": "巴西雷亚尔",
}

# 玻利瓦尔的历史写法 / 别名 → 统一为 Bs（VES、VED、VEF、Bs.、Bs.S、BOLIVAR…）
# 以及旧版本把中文名直接存库的历史数据（美元 / 人民币 / USDT 泰达币）
_CURRENCY_ALIASES = {
    "VES": CURRENCY_BS, "VED": CURRENCY_BS, "VEF": CURRENCY_BS,
    "BS": CURRENCY_BS, "BSS": CURRENCY_BS, "BSF": CURRENCY_BS,
    "BS.S": CURRENCY_BS, "BSS.S": CURRENCY_BS,
    "BOLIVAR": CURRENCY_BS, "BOLÍVAR": CURRENCY_BS, "BOLIVARES": CURRENCY_BS,
    "委内瑞拉玻利瓦尔": CURRENCY_BS, "玻利瓦尔": CURRENCY_BS,
    "美元": CURRENCY_USD, "美金": CURRENCY_USD,
    "人民币": CURRENCY_CNY, "元": CURRENCY_CNY,
    "USDT 泰达币": CURRENCY_USDT, "USDT泰达币": CURRENCY_USDT,
    "泰达币": CURRENCY_USDT, "数字加密稳定币": CURRENCY_USDT,
}


def normalize_currency(code) -> str:
    """把币种的各种写法归一到标准代码。

    主要用途：VES 与 Bs 是同一种货币，统一按 Bs 存储与显示。
    旧库里的 VES / VED / Bs. / 委内瑞拉玻利瓦尔 都会被读成 Bs；
    旧版本存成中文的「美元 / 人民币 / USDT 泰达币」也归一为 USD / CNY / USDT。
    """
    c = str(code or "").strip()
    if not c:
        return ""
    up = c.upper()
    if up in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[up]
    for std in CURRENCY_CODES:
        if up == std.upper():
            return std
    return c


def currency_label(code) -> str:
    """币种代码 → 统一显示名「中文名称（简称）」，如 美元（USD）、玻利瓦尔（Bs）。"""
    c = normalize_currency(code)
    if not c:
        return ""
    return f"{CURRENCY_ZH.get(c, c)}（{c}）"


def currency_code(text) -> str:
    """显示名 / 代码 → 标准代码：美元（USD）→ USD、人民币 → CNY、Bs → Bs。"""
    s = str(text or "").strip()
    if not s:
        return ""
    inner = ""
    if "（" in s and "）" in s:
        inner = s[s.index("（") + 1:s.rindex("）")].strip()
    elif "(" in s and ")" in s:
        inner = s[s.index("(") + 1:s.rindex(")")].strip()
    for cand in (inner, s):
        if not cand:
            continue
        code = normalize_currency(cand)
        if code in CURRENCY_CODES or code in _CURRENCY_ALIASES.values():
            return code
    return normalize_currency(s)

# 收/付款方式（下拉选取）
PAY_METHOD_CARD = "银行卡"
PAY_METHOD_EPAY = "电子支付"
PAY_METHOD_CASH = "现金"
PAY_METHODS = [PAY_METHOD_CARD, PAY_METHOD_EPAY, PAY_METHOD_CASH]

# 日常交易币种（库中一律存代码；界面按 currency_label() 显示「中文名称（简称）」）
PAY_CURRENCY_BS = "Bs"
PAY_CURRENCY_VES = PAY_CURRENCY_BS   # 兼容旧写法
PAY_CURRENCY_USD = "USD"
PAY_CURRENCY_CNY = "CNY"
PAY_CURRENCY_USDT = "USDT"
PAY_CURRENCIES = [PAY_CURRENCY_BS, PAY_CURRENCY_USD, PAY_CURRENCY_CNY,
                  PAY_CURRENCY_USDT]


def pay_currency_labels() -> list:
    """日常交易币种的显示名列表（与 PAY_CURRENCIES 一一对应）。"""
    return [currency_label(c) for c in PAY_CURRENCIES]

# ------------------------------------------------ 店铺收入日报：营业额来源
INCOME_SOURCE_CARD = "银行卡"        # → 银行存款
INCOME_SOURCE_EPAY = "电子支付"      # 扫码支付 → 其他货币资金
INCOME_SOURCE_CASH = "现钞"          # → 库存现金（稳定币除外，见 income_account_key）
INCOME_SOURCES = [INCOME_SOURCE_CARD, INCOME_SOURCE_EPAY, INCOME_SOURCE_CASH]

# 收入币种（库中存代码，界面显示中文）
INCOME_CUR_BS = "Bs"
INCOME_CUR_VES = INCOME_CUR_BS     # 兼容旧写法
INCOME_CUR_USD = "USD"
INCOME_CUR_CNY = "CNY"
INCOME_CUR_USDT = "USDT"
INCOME_CURRENCY_LABELS = {
    INCOME_CUR_BS: currency_label(INCOME_CUR_BS),
    INCOME_CUR_USD: currency_label(INCOME_CUR_USD),
    INCOME_CUR_CNY: currency_label(INCOME_CUR_CNY),
    INCOME_CUR_USDT: currency_label(INCOME_CUR_USDT),
}
# 各来源可选币种
INCOME_CARD_CURRENCIES = [INCOME_CUR_BS, INCOME_CUR_USD, INCOME_CUR_CNY]
INCOME_EPAY_CURRENCIES = [INCOME_CUR_USDT, INCOME_CUR_USD, INCOME_CUR_BS,
                          INCOME_CUR_CNY]
INCOME_CASH_CURRENCIES = [INCOME_CUR_BS, INCOME_CUR_USD, INCOME_CUR_CNY]

# 支付方式（下拉）→ 可选币种
INCOME_SOURCE_CURRENCIES = {
    INCOME_SOURCE_CARD: INCOME_CARD_CURRENCIES,
    INCOME_SOURCE_EPAY: INCOME_EPAY_CURRENCIES,
    INCOME_SOURCE_CASH: INCOME_CASH_CURRENCIES,
}


def income_currency_label(code) -> str:
    return INCOME_CURRENCY_LABELS.get(code, code or "")


# 稳定币（非法定货币）：不存在现钞形态，只能记银行存款 / 其他货币资金
STABLECOIN_CURRENCIES = {INCOME_CUR_USDT}


def is_stablecoin(currency) -> bool:
    """是否为稳定币（USDT 等）：不能记账为库存现金。"""
    return normalize_currency(currency) in STABLECOIN_CURRENCIES


def income_account_key(source: str, currency: str) -> str:
    """营业额「支付方式 + 币种」→ 报表科目 key。

    法定货币（USD / Bs / CNY）可记三种科目，由支付方式决定：
      现钞     → cash   = 库存现金
      银行卡   → bank   = 银行存款
      电子支付 → crypto = 其他货币资金（扫码支付）
    稳定币（USDT）不是法定货币、没有现钞形态，只能记银行存款 / 其他货币资金；
    若来源是现钞则改记银行存款。
    """
    stable = is_stablecoin(currency)
    if source == INCOME_SOURCE_CASH:
        return "bank" if stable else "cash"
    if source == INCOME_SOURCE_CARD:
        return "bank"
    return "crypto"


def income_account_options(currency) -> list:
    """该币种允许记账的科目 key 列表（用于校验）。"""
    return ["bank", "crypto"] if is_stablecoin(currency) else ["cash", "bank", "crypto"]

# 币种符号（用于金额显示）；VES/BS 等旧写法同样显示 Bs.
CURRENCY_SYMBOLS = {
    CURRENCY_EUR: "€",
    CURRENCY_USD: "$",
    "Bs": "Bs.",
    "BS": "Bs.",
    "VES": "Bs.",
    CURRENCY_CNY: "¥",
    CURRENCY_USDT: "₮",
}

# 分店列表（入库分店 / Sucursal），可在设置中修改
DEFAULT_STORES = ["A店", "B店"]

# 店铺支出科目
EXPENSE_CATEGORIES = [
    ("salary", "工资"),
    ("overtime", "加班费"),
    ("meal", "膳食费用"),
    ("tax", "税金"),
    ("utilities", "水电费"),
    ("rent", "铺租"),
    ("municipal", "市政管理费"),
]

# 会计科目表（西班牙 PGC 简化）
ACCOUNT_CASH = "570"          # Caja / Bancos 现金及银行
ACCOUNT_BANK = "572"          # Bancos 银行存款（银行卡收款）
ACCOUNT_CRYPTO = "579"        # 其他货币资金（加密稳定币等数字资产）
ACCOUNT_CAPITAL = "100"       # Capital social 资本
ACCOUNT_CUSTOMERS = "430"     # Clientes 客户（应收账款）
ACCOUNT_SUPPLIERS = "400"     # Proveedores 供应商（应付账款）
ACCOUNT_INVENTORY = "300"     # Existencias 存货
ACCOUNT_SALES = "700"         # Ventas de mercaderías 销售收入
ACCOUNT_PURCHASES = "600"     # Compras de mercaderías 进货成本（结转用）
ACCOUNT_COST_OF_SALES = "610" # Coste de ventas 销售成本
ACCOUNT_IVA_INPUT = "472"     # HP IVA Soportado 进项税（可抵扣）
ACCOUNT_IVA_OUTPUT = "477"    # HP IVA Repercutido 销项税（应交）

# 科目显示名称（西班牙语 + 中文）
ACCOUNT_NAMES = {
    ACCOUNT_CASH: "Caja/Bancos 现金及银行",
    ACCOUNT_BANK: "Bancos 银行存款",
    ACCOUNT_CRYPTO: "Otras formas de dinero 其他货币资金",
    ACCOUNT_CAPITAL: "Capital social 实收资本",
    ACCOUNT_CUSTOMERS: "Clientes 应收账款",
    ACCOUNT_SUPPLIERS: "Proveedores 应付账款",
    ACCOUNT_INVENTORY: "Existencias 存货",
    ACCOUNT_SALES: "Ventas 销售收入",
    ACCOUNT_PURCHASES: "Compras 进货",
    ACCOUNT_COST_OF_SALES: "Coste de ventas 销售成本",
    ACCOUNT_IVA_INPUT: "HP IVA Soportado 进项税",
    ACCOUNT_IVA_OUTPUT: "HP IVA Repercutido 销项税",
}

# ---------------------------------------------------------------- 报表科目映射
# 业务 → 科目的解析规则：优先用候选编码（在科目表中存在者），否则按名称关键字查找。
# 科目表为空（旧库）时，报表回退到上面的西班牙 PGC 常量科目。
ACCOUNTING_MAP = {
    # 币种 → 货币资金科目（USD/Bs/CNY → 库存现金；USDT → 银行存款）
    "cash": (["1001"], ["库存现金"]),
    "bank": (["1002"], ["银行存款"]),
    "crypto": (["1012", "1090"], ["其他货币资金", "数字货币"]),
    "inventory": (["1405", "1403"], ["库存商品"]),
    "sales": (["5001"], ["主营业务收入"]),
    "cost_of_sales": (["5401"], ["主营业务成本"]),
    "iva_input": (["22210101"], ["进项税额"]),
    "iva_output": (["22210106"], ["销项税额"]),
    "capital": (["3001"], ["实收资本"]),
    "receivable": (["1122"], ["应收账款"]),
    "payable": (["2202"], ["应付账款"]),
}

# 科目类别（按《小企业会计准则》编码首位）
CATEGORY_BY_PREFIX = {
    "1": "asset",       # 资产
    "2": "liability",   # 负债
    "3": "equity",      # 所有者权益
    "4": "asset",       # 成本类（生产成本/制造费用）→ 存货，列资产
    "5": "pnl",         # 损益
    "6": "equity",      # 6000 以前年度损益调整 → 权益
}


# 旧库/回退用的西班牙 PGC 科目：编码首位规则不适用，单独指定类别
CATEGORY_OVERRIDES = {
    ACCOUNT_CASH: "asset",            # 570 Caja/Bancos
    ACCOUNT_BANK: "asset",            # 572 Bancos 银行存款
    ACCOUNT_CRYPTO: "asset",          # 579 其他货币资金
    ACCOUNT_CUSTOMERS: "asset",       # 430 Clientes
    ACCOUNT_INVENTORY: "asset",       # 300 Existencias
    ACCOUNT_SUPPLIERS: "liability",   # 400 Proveedores
    ACCOUNT_IVA_INPUT: "liability",   # 472 HP IVA Soportado
    ACCOUNT_IVA_OUTPUT: "liability",  # 477 HP IVA Repercutido
    ACCOUNT_CAPITAL: "equity",        # 100 Capital social
    ACCOUNT_SALES: "pnl",             # 700 Ventas
    ACCOUNT_PURCHASES: "pnl",         # 600 Compras
    ACCOUNT_COST_OF_SALES: "pnl",     # 610 Coste de ventas
}


def account_category(code) -> str:
    """判定科目类别：asset / liability / equity / pnl / other。

    先查西班牙 PGC 特例（旧库），再按编码首位（小企业会计准则）。
    """
    c = str(code or "").strip()
    if c in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[c]
    return CATEGORY_BY_PREFIX.get(c[:1], "other")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
