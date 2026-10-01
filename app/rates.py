"""币种与汇率：委内瑞拉官方汇率在线获取、美元/本位币汇率、金额换算。

委内瑞拉官方汇率源（优先使用 dolarapi / BCV）：
    GET https://ve.dolarapi.com/v1/dolares/oficial
    -> {"moneda":"USD","fuente":"oficial","promedio":785.07,
        "fechaActualizacion":"2026-08-25T00:00:00-04:00"}

通用汇率备用源（open.er-api / exchangerate-api）：
    GET https://open.er-api.com/v6/latest/USD
    GET https://api.exchangerate-api.com/v4/latest/USD
    -> {"rates":{"EUR":0.85,"CNY":6.45,"VES":36.5,...},
        "time_last_update_utc":"..."}
"""
import json
import ssl
import urllib.request
from typing import Any

from app import config

# 常用币种代码与名称：全项目统一为「中文名称（简称）」
# （VES 与 Bs 是同一种货币，统一显示为 玻利瓦尔（Bs））
CURRENCY_NAMES = {
    code: config.currency_label(code)
    for code in ("EUR", "USD", "CNY", "Bs", "USDT",
                 "MXN", "ARS", "COP", "PEN", "CLP")
}

# 委内瑞拉官方/备用数据源（优先官方 dolarapi，失败后使用通用汇率 API）
_VES_SOURCES = [
    ("https://ve.dolarapi.com/v1/dolares/oficial", "dolarapi"),
    ("https://api.ve.dolarapi.com/v1/dolares/oficial", "dolarapi"),
    ("https://api.exchangerate-api.com/v4/latest/USD", "exchangerate-api"),
    ("https://open.er-api.com/v6/latest/USD", "open.er-api"),
]

# 通用 USD -> 其他币种 备用数据源
_GENERIC_RATES_SOURCES = [
    "https://api.exchangerate-api.com/v4/latest/USD",
    "https://open.er-api.com/v6/latest/USD",
]


def _get_json(url: str, timeout: int = 15) -> Any:
    """GET JSON，带 UA、超时，并忽略 SSL 证书验证（打包环境常缺少证书）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "GestionFacturas/1.0"})
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_date(data: dict) -> str:
    """从不同 API 返回中提取更新时间。"""
    return (
        data.get("fechaActualizacion")
        or data.get("time_last_update_utc")
        or data.get("time_last_update")
        or data.get("date")
        or ""
    )


def _extract_rate(data: dict, code: str) -> float:
    """从通用汇率 API 返回中读取 1 USD = X code。"""
    rates = data.get("rates", {})
    if code in rates:
        val = rates[code]
    elif code in data:
        val = data[code]
    elif "rate" in data:
        val = data["rate"]
    else:
        raise ValueError(f"{code} 未找到")
    rate = float(val)
    if rate <= 0:
        raise ValueError(f"{code} 汇率为空")
    return rate


def fetch_usd_ves() -> dict:
    """在线获取委内瑞拉官方汇率（BCV），即 1 USD = X Bs。

    返回 {"usd_ves": float, "date": str, "source": str}；
    全部源失败时抛 RuntimeError。
    """
    last_err = None
    for url, kind in _VES_SOURCES:
        try:
            data = _get_json(url)
            if kind == "dolarapi":
                rate = float(data.get("promedio") or data.get("venta") or 0)
                if rate <= 0:
                    raise ValueError("BCV 官方汇率为空")
                return {
                    "usd_ves": round(rate, 4),
                    "date": data.get("fechaActualizacion", ""),
                    "source": url,
                }
            rate = _extract_rate(data, "VES")
            return {
                "usd_ves": round(rate, 4),
                "date": _extract_date(data),
                "source": url,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法获取委内瑞拉官方汇率：{last_err}")


def fetch_usd_eur() -> dict:
    """在线获取美元兑欧元汇率（1 USD = X EUR）。"""
    last_err = None
    for url in _GENERIC_RATES_SOURCES:
        try:
            data = _get_json(url)
            rate = _extract_rate(data, "EUR")
            return {
                "usd_eur": round(rate, 4),
                "date": _extract_date(data),
                "source": url,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法获取美元/欧元汇率：{last_err}")


def fetch_usd_cny() -> dict:
    """在线获取美元兑人民币汇率（1 USD = X CNY）。"""
    last_err = None
    for url in _GENERIC_RATES_SOURCES:
        try:
            data = _get_json(url)
            rate = _extract_rate(data, "CNY")
            return {
                "usd_cny": round(rate, 4),
                "date": _extract_date(data),
                "source": url,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法获取美元/人民币汇率：{last_err}")


def convert_to_base(amount: float, currency: str, settings: dict,
                    doc_rate: float = 0.0, date: str = None,
                    rate_kind: str = "auto"):
    """把单据金额换算为本位币金额，按单据日期优先取历史汇率。

    参数 doc_rate：单据上标注的汇率（1 USD = X 本国货币），即「手改汇率」。
    参数 date：业务日期；为空时使用当前设置汇率兜底。
    参数 rate_kind：汇率口径
        · 'auto'/'manual' — 优先手改汇率（doc_rate）→ BCV → 平行
        · 'bcv'           — BCV 官方 → 平行 → 手改
        · 'parallel'      — 平行市场 → BCV → 手改
    返回 (换算后金额, 是否成功换算)。
    """
    if not amount:
        return 0.0, True

    from app.accounting import rates as acc_rates

    base = config.normalize_currency(
        settings.get("base_currency") or config.DEFAULT_BASE_CURRENCY).upper()
    # 注意：currency_label() 返回「美元（USD）」这类显示名，先转回代码再比对，
    # 否则中文显示名匹配不到任何分支，所有单据都会被判为「未换算」。
    cur = config.normalize_currency(
        config.currency_code(currency) or currency or base).upper()
    if cur == base:
        return amount, True

    chain = acc_rates.KIND_CHAINS.get(
        (rate_kind or "auto").lower(),
        acc_rates.KIND_CHAINS[acc_rates.RATE_MANUAL])

    def _kind_rate(kind: str) -> float:
        """某一口径下 1 cur = ? 本位币；取不到返回 0。"""
        if kind == acc_rates.RATE_MANUAL:
            # 手改汇率：仅 Bs/CNY 支持单据汇率（1 USD = X 本国货币）
            if cur in ("BS", "VES", "CNY") and doc_rate > 0:
                usd_to_base = float(settings.get("usd_to_base") or 0)
                if usd_to_base <= 0:
                    usd_to_base = acc_rates.to_base("USD", acc_rates.RATE_BCV, date)
                return (usd_to_base / doc_rate) if usd_to_base else 0.0
            return 0.0
        return acc_rates.to_base(cur, kind, date)

    for kind in chain:
        rate = _kind_rate(kind)
        if rate > 0:
            return amount * rate, True
    return amount, False
