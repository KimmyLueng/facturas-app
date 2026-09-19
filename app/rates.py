"""币种与汇率：委内瑞拉官方汇率在线获取、美元/本位币汇率、金额换算。

官方汇率源（dolarapi，来源 BCV 委内瑞拉中央银行）：
    GET https://ve.dolarapi.com/v1/dolares/oficial
    -> {"moneda":"USD","fuente":"oficial","promedio":785.07,
        "fechaActualizacion":"2026-08-25T00:00:00-04:00"}
美元兑欧元（备用源）：
    GET https://open.er-api.com/v6/latest/USD
"""
import json
import urllib.request

from app import config

# 常用币种代码与名称（VES 与 Bs 是同一种货币，统一显示为 Bs）
CURRENCY_NAMES = {
    "EUR": "欧元 EUR",
    "USD": "美元 USD",
    "CNY": "人民币 CNY",
    "Bs": "玻利瓦尔 Bs（委内瑞拉）",
    "BS": "玻利瓦尔 Bs（委内瑞拉）",
    "VES": "玻利瓦尔 Bs（委内瑞拉，VES 为 ISO 代码）",
    "MXN": "墨西哥比索 MXN",
    "ARS": "阿根廷比索 ARS",
    "COP": "哥伦比亚比索 COP",
    "PEN": "秘鲁索尔 PEN",
    "CLP": "智利比索 CLP",
    "USDT": "USDT 泰达币（稳定币，1:1 美元）",
}


def _get_json(url: str, timeout: int = 12) -> dict:
    """GET JSON，带 UA 与超时。"""
    req = urllib.request.Request(url, headers={"User-Agent": "GestionFacturas/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_usd_ves() -> dict:
    """在线获取委内瑞拉官方汇率（BCV），即 1 USD = X Bs。

    返回 {"usd_ves": float, "date": str, "source": str}；
    全部源失败时抛 RuntimeError。
    """
    urls = [
        "https://ve.dolarapi.com/v1/dolares/oficial",
        "https://api.ve.dolarapi.com/v1/dolares/oficial",
    ]
    last_err = None
    for url in urls:
        try:
            data = _get_json(url)
            rate = float(data.get("promedio") or data.get("venta") or 0)
            if rate <= 0:
                raise ValueError("汇率为空")
            return {
                "usd_ves": round(rate, 4),
                "date": data.get("fechaActualizacion", ""),
                "source": url,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"无法获取委内瑞拉官方汇率：{last_err}")


def fetch_usd_eur() -> dict:
    """在线获取美元兑欧元汇率（1 USD = X EUR）。"""
    try:
        data = _get_json("https://open.er-api.com/v6/latest/USD")
        eur = float(data.get("rates", {}).get("EUR") or 0)
        if eur <= 0:
            raise ValueError("EUR 汇率为空")
        return {"usd_eur": round(eur, 4),
                "date": data.get("time_last_update_utc", "")}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"无法获取美元/欧元汇率：{e}") from e


def fetch_usd_rates(*codes) -> dict:
    """一次请求获取 1 USD 兑多个币种（open.er-api.com）。

    返回 {"EUR": x, "CNY": y, "date": "..."}；任一币种缺失即报错。
    """
    data = _get_json("https://open.er-api.com/v6/latest/USD")
    rates = data.get("rates", {})
    out = {"date": data.get("time_last_update_utc", "")}
    for c in codes:
        v = float(rates.get(c) or 0)
        if v <= 0:
            raise ValueError(f"{c} 汇率为空")
        out[c] = round(v, 4)
    return out


def fetch_usd_cny() -> dict:
    """在线获取美元兑人民币汇率（1 USD = X CNY）。"""
    try:
        data = fetch_usd_rates("CNY")
        return {"usd_cny": data["CNY"], "date": data.get("date", "")}
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
