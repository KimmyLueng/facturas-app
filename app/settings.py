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
    "expense_categories": [],    # 自定义费用类别（支出日报里手工新增的名称）
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


# ------------------------------------------------------- 费用类别（支出日报）
def get_expense_categories() -> list:
    """费用类别 [(key, label)]：内置科目 + 设置里手工新增的自定义类别。

    自定义类别以名称同时作为 key 存入该列（如「加班餐费」）。
    """
    out = list(config.EXPENSE_CATEGORIES)
    seen = {k for k, _l in out} | {label for _k, label in out}
    for name in load_settings().get("expense_categories") or []:
        name = str(name).strip()
        if name and name not in seen:
            out.append((name, name))
            seen.add(name)
    return out


def expense_category_keys() -> set:
    """全部已知费用类别 key 的集合。"""
    return {k for k, _l in get_expense_categories()}


def add_expense_category(label: str) -> str:
    """新增自定义费用类别并持久化，返回其 key。

    内置类别直接返回对应 key；自定义类别 key 即名称本身。
    """
    name = (label or "").strip()
    if not name:
        return ""
    for key, builtin_label in config.EXPENSE_CATEGORIES:
        if name in (key, builtin_label):
            return key
    s = load_settings()
    customs = [str(x).strip() for x in (s.get("expense_categories") or [])
               if str(x).strip()]
    if name not in customs:
        customs.append(name)
        s["expense_categories"] = customs
        save_settings(s)
    return name


def get_custom_expense_categories() -> list:
    """仅返回用户自定义的类别名称列表（内置类别不可改名/删除）。"""
    return [str(x).strip() for x in (load_settings().get("expense_categories") or [])
            if str(x).strip()]


def is_builtin_expense_category(label: str) -> bool:
    """判断某类别名是否为内置类别（内置类别只允许选用，不允许改名/删除）。"""
    name = (label or "").strip()
    for _k, builtin_label in config.EXPENSE_CATEGORIES:
        if name in (builtin_label, _k):
            return True
    return False


def rename_expense_category(old_label: str, new_label: str) -> str:
    """重命名一个自定义费用类别，并同步更新已录入的支出明细。

    内置类别不可改名；新名称与已有类别（内置或自定义）重复时报错。
    返回新的 key（自定义类别 key 即名称本身）。
    """
    old = (old_label or "").strip()
    new = (new_label or "").strip()
    if not old or not new:
        raise ValueError("类别名不能为空")
    if is_builtin_expense_category(old):
        raise ValueError("内置类别不可改名")
    if is_builtin_expense_category(new):
        raise ValueError("该名称与内置类别冲突")
    customs = get_custom_expense_categories()
    if old not in customs:
        raise ValueError("待改名的类别不存在")
    others = [c for c in customs if c != old]
    if new in others:
        raise ValueError("已存在同名类别")

    s = load_settings()
    s["expense_categories"] = [new if c == old else c for c in customs]
    save_settings(s)

    # 同步更新已录入明细里引用该类别的记录（category 存的是 key=名称）
    from app.db import database
    database.reassign_expense_category(old, new)
    return new


def delete_expense_category(label: str) -> int:
    """删除一个自定义费用类别，并把它名下的支出明细改挂到默认内置类别。

    内置类别不可删除。返回被改挂的明细条数。
    """
    name = (label or "").strip()
    if not name:
        raise ValueError("类别名不能为空")
    if is_builtin_expense_category(name):
        raise ValueError("内置类别不可删除")
    customs = get_custom_expense_categories()
    if name not in customs:
        raise ValueError("待删除的类别不存在")

    s = load_settings()
    s["expense_categories"] = [c for c in customs if c != name]
    save_settings(s)

    # 名下明细改挂到第一个内置类别，避免数据丢失
    fallback = config.EXPENSE_CATEGORIES[0][0]
    from app.db import database
    return database.reassign_expense_category(name, fallback)

