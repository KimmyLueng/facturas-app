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
    """GET JSON，带 UA 与超时。"""
    req = urllib.request.Request(url, headers={"User-Agent": "GestionFacturas/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def fetch_usd_rates(*codes) -> dict:
    """一次请求获取 1 USD 兑多个币种（带多个备用源）。

    返回 {"EUR": x, "CNY": y, "date": "...", "source": "..."}；
    任一币种缺失即继续尝试下一个源，全部失败时报错。
    """
    last_err = None
    for url in _GENERIC_RATES_SOURCES:
        try:
            data = _get_json(url)
            out = {"date": _extract_date(data), "source": url}
            for c in codes:
                out[c] = round(_extract_rate(data, c), 4)
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法获取 USD 汇率：{last_err}")


def fetch_usd_cny() -> dict:
    """在线获取美元兑人民币汇率（1 USD = X CNY）。"""
    try:
        data = fetch_usd_rates("CNY")
        return {
            "usd_cny": data["CNY"],
            "date": data.get("date", ""),
            "source": data.get("source", ""),
        }
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"无法获取美元/人民币汇率：{e}") from e


def convert_to_base(amount: float, currency: str, settings: dict,
                    doc_rate: float = 0.0):
    """把单据金额换算为本位币金额。

    参数 doc_rate：单据上标注的汇率（1 USD = X 本国货币），优先于官方汇率。
    返回 (换算后金额, 是否成功换算)。
    - 币种 = 本位币             → 原值
    - USD：金额 × usd_to_base
    - Bs（含旧写法 VES）：金额 ÷ 汇率 × usd_to_base（汇率 = 单据自带或官方 usd_ves）
    - CNY：金额 ÷ 汇率 × usd_to_base（汇率 = 单据自带或设置中的 usd_cny）
    - 其他/缺汇率              → 原值返回，成功=False（报表提示未换算）
    """
    if not amount:
        return 0.0, True
    base = config.normalize_currency(
        settings.get("base_currency") or config.DEFAULT_BASE_CURRENCY).upper()
    cur = config.normalize_currency(currency or base).upper()
    if cur == base:
        return amount, True

    usd_to_base = float(settings.get("usd_to_base") or 0)
    usd_ves = float(settings.get("usd_ves_official") or 0)

    if cur in ("USD", "USDT"):
        # USDT 稳定币与美元 1:1 锚定，换算同美元
        if usd_to_base <= 0:
            return amount, False
        return amount * usd_to_base, True
    if cur == config.CURRENCY_BS.upper():      # Bs（VES/BS 等旧写法已在上方归一）
        rate = doc_rate or usd_ves
        if rate <= 0 or usd_to_base <= 0:
            return amount, False
        return amount / rate * usd_to_base, True
    if cur == "CNY":
        rate = doc_rate or float(settings.get("usd_cny") or 0)
        if rate <= 0 or usd_to_base <= 0:
            return amount, False
        return amount / rate * usd_to_base, True
    # 其他币种：无汇率，按原值并标记未换算
    return amount, False
