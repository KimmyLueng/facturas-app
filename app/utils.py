"""通用工具函数：金额/日期解析等。"""
import re
import datetime

from app import config

# ---------------------------------------------------------------- 金额解析
def parse_amount(text: str) -> float:
    """解析西班牙语格式金额："$ 1.234,56" / "1.234,56 €" / "1234,56" / "1,234.56"。

    规则：若同时存在逗号和点，以最后出现者作为小数分隔符。
    """
    if not text:
        return 0.0
    t = str(text)
    # 去掉货币符号和字母、空格
    t = t.replace("€", "").replace("$", "").replace("EUR", "").replace(" ", "")
    t = t.replace("\u00a0", "").replace("\t", "")
    # 保留数字、点、逗号、负号
    t = re.sub(r"[^\d.,\-]", "", t)
    if not t or t in (".", ",", "-"):
        return 0.0
    neg = t.startswith("-")
    t = t.lstrip("-")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return 0.0
    return -v if neg else v


def format_amount(value: float, decimals: int = 2, currency: str = None) -> str:
    """格式化为西班牙语金额："1.234,56 $"。

    currency 指定币种时显示对应符号（CNY→¥、EUR→€、VES→Bs.），默认 $。
    """
    if value is None:
        value = 0.0
    s = f"{value:,.{decimals}f}"
    # 转西班牙语：千分位 . 小数 ,
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    symbol = config.CURRENCY_SYMBOLS.get(str(currency or "").upper(), "$")
    return f"{s} {symbol}"


# ---------------------------------------------------------------- 日期解析
def parse_date(text: str):
    """解析日期，优先支持 yyyy-mm-dd / yyyy/mm/dd，也支持 dd/mm/yyyy 等西班牙语格式。"""
    if not text:
        return None
    t = str(text).strip()
    # 1) ISO 格式：yyyy-mm-dd / yyyy/mm/dd（手工录入常见）
    iso = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", t)
    if iso:
        y, mo, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        try:
            return datetime.date(y, mo, d)
        except ValueError:
            return None
    # 2) 西班牙语格式：dd/mm/yyyy、dd-mm-yyyy、dd.mm.yyyy
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", t)
    if not m:
        # 形如 25 de agosto de 2026
        m2 = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-záéíóúñ]+)\s+(?:de\s+)?(\d{2,4})", t, re.I)
        if m2:
            months = {
                "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
                "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
                "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
            }
            mon = months.get(m2.group(2).lower())
            if mon:
                try:
                    return datetime.date(int(m2.group(3)), mon, int(m2.group(1)))
                except ValueError:
                    return None
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def date_iso(d) -> str:
    """date -> 'YYYY-MM-DD'"""
    return d.strftime("%Y-%m-%d") if d else ""


# ---------------------------------------------------------------- 单据号
_DATE_LIKE = re.compile(r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}$")


def parse_document_number(text: str) -> str:
    """从文本中提取单据号：Factura Nº 2026-001 / F-0001 等。"""
    if not text:
        return ""
    patterns = [
        # Nº 2026-001 / N. FACTURA 2026-001 / FACTURA Nº 2026-001
        r"(?:N[ºo°]?\.?\s*(?:FACTURA|FACT|DOC(?:UMENTO)?)?"
        r"|FACTURA\s*(?:N[ºo°]?\.?\s*)?|FACT\s*)\s*[:\-]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9\-/._]*\d[A-Za-z0-9\-/._]*)",
        # "Factura 2026-045"
        r"\b(?:FACTURA|FACT|ALBAR[ÁA]N|TICKET)\b\s*[:\-]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9\-/._]*\d[A-Za-z0-9\-/._]*)",
        # F-2026-001 等带字母前缀编号
        r"\b([A-Za-z]{1,4}[-/]\d{3,}[A-Za-z0-9\-/._]*)\b",
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.I):
            v = m.group(1).strip(" :.-")
            if not v:
                continue
            if _DATE_LIKE.match(v):   # 排除日期被误当单据号
                continue
            return v
    return ""
