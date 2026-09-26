"""按「业务日期」取汇率（而非系统当天汇率），并区分两种委内瑞拉并行汇率。

委内瑞拉国内实际并行的汇率：
  · BCV 汇率（Dólar BCV）：央行每日发布的官方参考汇率，会计/税务/海关法定依据。
  · 平行汇率（Dólar Paralelo）：平行市场汇率，用于实际交易参考。

汇率统一表达为：1 单位币种 = rate 个本位币（to_base）。
并可按两个币种直接计算交叉汇率（cross_rate）：1 换出币种 = X 换入币种。

优先取 exchange_rates 表里该日期（或之前最近）的记录（按 kind 区分口径）；
没有历史记录时，按设置里的当前汇率折算兜底。

设置里的汇率键：
    base_currency      本位币（默认 USD）
    usd_to_base        1 USD = X 本位币
    usd_ves_official   1 USD = X Bs（BCV 官方）
    usd_ves_parallel   1 USD = X Bs（Dólar Paralelo 平行市场）
    usd_cny            1 USD = X CNY
USDT 近似 1:1 与 USD。
"""
from app import config
from app.db import database
from app.utils import date_iso

RATE_BCV = "bcv"
RATE_PARALLEL = "parallel"


def _get_settings() -> dict:
    try:
        from app import settings as settings_mod
        return settings_mod.load_settings()
    except Exception:  # noqa: BLE001
        return {}


def _live_to_base(currency: str, kind: str = RATE_BCV) -> float:
    """当前设置下，1 单位 currency = 多少本位币（指定口径）。"""
    s = _get_settings()
    base = (s.get("base_currency") or config.DEFAULT_BASE_CURRENCY).strip().upper()
    usd_to_base = float(s.get("usd_to_base") or 0.0) or 1.0
    usd_ves = float(s.get("usd_ves_official") or 0.0) or 0.0
    usd_ves_p = float(s.get("usd_ves_parallel") or usd_ves or 0.0)
    usd_cny = float(s.get("usd_cny") or 0.0) or 0.0

    c = (currency or "").strip().upper()
    if c == base:
        return 1.0
    if c == "USD":
        return usd_to_base
    if c in ("BS", "VES"):
        ves = usd_ves_p if kind == RATE_PARALLEL else usd_ves
        return (usd_to_base / ves) if ves > 0 else 0.0
    if c == "CNY":
        return (usd_to_base / usd_cny) if usd_cny > 0 else 0.0
    if c == "USDT":
        return usd_to_base
    return 0.0


def _live_rates(kind: str = RATE_BCV) -> dict:
    return {c: _live_to_base(c, kind) for c in config.PAY_CURRENCIES}


def to_base(currency: str, kind: str = RATE_BCV, date: str = None) -> float:
    """取某口径下 1 单位 currency = 多少本位币（优先该日期历史，否则当前设置兜底）。"""
    cur = (currency or "").strip()
    if date:
        hist = database.get_rate_on_or_before(date, cur, kind)
        if hist is not None:
            return hist
    return _live_to_base(cur, kind)


def cross_rate(from_currency: str, to_currency: str,
               kind: str = RATE_BCV, date: str = None) -> float:
    """1 换出币种 = X 换入币种（指定口径/日期）。"""
    f = to_base(from_currency, kind, date)
    t = to_base(to_currency, kind, date)
    return (f / t) if t else 0.0


def rate_on_date(date: str, currency: str, kind: str = RATE_BCV) -> float:
    """兼容别名：按日期取某口径的 to_base。"""
    return to_base(currency, kind, date)


def rates_on_date(date: str, kind: str = RATE_BCV) -> dict:
    return {c: to_base(c, kind, date) for c in config.PAY_CURRENCIES}


def record_today_rates(date: str = None):
    """把当前设置折算出的各币种汇率（BCV + 平行），按今天记录到汇率历史。"""
    date = date or date_iso(None) or ""
    if not date:
        return
    database.save_rates_for_date(date, _live_rates(RATE_BCV), RATE_BCV)
    database.save_rates_for_date(date, _live_rates(RATE_PARALLEL), RATE_PARALLEL)
