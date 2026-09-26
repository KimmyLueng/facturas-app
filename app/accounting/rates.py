"""按「业务日期」取汇率（而非系统当天汇率）。

汇率统一表达为：1 单位币种 = rate 个本位币（rate_to_base）。
优先取 exchange_rates 表里该日期（或之前最近）的记录；
没有历史记录时，按设置里的当前汇率折算兜底。

设置里的汇率键：
    base_currency   本位币（默认 USD）
    usd_to_base     1 USD = X 本位币
    usd_ves_official 1 USD = X Bs（BCV 委内瑞拉官方）
    usd_cny         1 USD = X CNY
USDT 近似 1:1 与 USD。
"""
from app import config
from app.db import database
from app.utils import date_iso


def _settings_rates() -> dict:
    """按当前设置计算每个币种的 rate_to_base。"""
    s = _get_settings()
    base = (s.get("base_currency") or config.DEFAULT_BASE_CURRENCY).strip().upper()
    usd_to_base = float(s.get("usd_to_base") or 0.0) or 1.0
    usd_ves = float(s.get("usd_ves_official") or 0.0) or 0.0
    usd_cny = float(s.get("usd_cny") or 0.0) or 0.0

    rate = {}
    for cur in config.PAY_CURRENCIES:
        c = cur.strip().upper()
        if c == base:
            rate[cur] = 1.0
        elif c == "USD":
            rate[cur] = usd_to_base
        elif c in ("BS", "VES", "Bs".upper()):
            rate[cur] = (usd_to_base / usd_ves) if usd_ves > 0 else 0.0
        elif c == "CNY":
            rate[cur] = (usd_to_base / usd_cny) if usd_cny > 0 else 0.0
        elif c == "USDT":
            rate[cur] = usd_to_base   # 稳定币近似 1:1
        else:
            rate[cur] = 0.0
    return rate


def _get_settings() -> dict:
    try:
        from app import settings as settings_mod
        return settings_mod.load_settings()
    except Exception:  # noqa: BLE001
        return {}


def live_rate_to_base(currency: str) -> float:
    """当前设置下，1 单位 currency = 多少本位币。"""
    cur = (currency or "").strip()
    return _settings_rates().get(cur, 0.0)


def rate_on_date(date: str, currency: str) -> float:
    """取该业务日期（或之前最近）的 rate_to_base；无历史则按当前设置兜底。"""
    cur = (currency or "").strip()
    hist = database.get_rate_on_or_before(date, cur)
    if hist is not None:
        return hist
    return live_rate_to_base(cur)


def rates_on_date(date: str) -> dict:
    """取该日期所有交易币种的 rate_to_base（用历史或当前设置兜底）。"""
    return {c: rate_on_date(date, c) for c in config.PAY_CURRENCIES}


def record_today_rates(date: str = None):
    """把当前设置折算出的各币种汇率，记录到 exchange_rates（便于日后按业务日期取历史）。"""
    date = date or date_iso(None) or ""
    if not date:
        return
    database.save_rates_for_date(date, _settings_rates())
