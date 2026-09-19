"""应用设置（JSON 持久化）。"""
import json
import os

from app import config

SETTINGS_PATH = os.path.join(config.DATA_DIR, "settings.json")

DEFAULTS = {
    "capital_inicial": config.DEFAULT_CAPITAL,   # 期初资本（本位币）
    # ---- 币种与汇率 ----
    "base_currency": config.DEFAULT_BASE_CURRENCY,   # 本位币（记账币种）
    "usd_to_base": 1.0,          # 1 USD 兑本位币（本位币为 USD 时保持 1；EUR 时可在线更新）
    "usd_ves_official": 0.0,     # 委内瑞拉官方汇率：1 USD = X Bs（BCV）
    "usd_ves_date": "",          # 官方汇率更新时间
    "usd_cny": 0.0,              # 美元兑人民币：1 USD = X CNY（可在线更新）
    "stores": list(config.DEFAULT_STORES),   # 分店列表
    # ---- 数据同步（WebDAV）----
    "webdav": {},        # 服务器配置，结构见 app/sync/manager.py: DEFAULT_WEBDAV
    "sync_state": {},    # 同步基线：上次同步的本地/云端哈希、时间与结果
}


def load_settings() -> dict:
    config.ensure_data_dir()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save_settings(data: dict):
    config.ensure_data_dir()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_stores() -> list:
    """当前分店列表（设置 + 默认）。"""
    s = load_settings()
    return list(s.get("stores") or config.DEFAULT_STORES)


def add_store(name: str) -> bool:
    """把分店加入设置并持久化（已存在返回 False）。"""
    name = (name or "").strip()
    if not name:
        return False
    s = load_settings()
    stores = list(s.get("stores") or config.DEFAULT_STORES)
    if name in stores:
        return False
    stores.append(name)
    s["stores"] = stores
    save_settings(s)
    return True
