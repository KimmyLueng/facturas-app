"""财务报表引擎：基于科目表（chart_of_accounts）+ 期初余额 + 单据生成报表。

数据来源：
- 科目体系与期初余额：科目表 + opening_balances（《财务初始余额.xlsx》模板导入）
- 本期发生额：进货/出货单据按 config.ACCOUNTING_MAP 映射到具体科目

会计模型（借贷记账，signed 约定：借方为正、贷方为负）：
- 进货:  借 库存商品(1405) +base        借 应交税费—进项税额(22210101) +iva
         贷 库存现金(1001)               -total
- 出货:  借 库存现金(1001)               +total
         贷 主营业务收入(5001)           -base
         贷 应交税费—销项税额(22210106)  -iva
         并结转成本: 借 主营业务成本(5401) +coste   贷 库存商品(1405) -coste
- 销售成本默认按加权平均法计算（也可用单据行项目中的成本）。
- 科目表为空（旧库）或期初未录入时，回退到 config 中的西班牙 PGC 科目常量与
  设置里的期初资本，保持旧行为。
"""
import datetime

from app import config
from app.db import database
from app.rates import convert_to_base
from app.settings import load_settings
from app.utils import format_amount


# ---------------------------------------------------------------- 成本计算
def _running_avg_cost(docs):
    """按时间顺序计算加权平均单位成本。返回每张出货单对应的 cost_total。"""
    key = lambda d: ((d["date"] or "9999"), d["id"])
    purchases = sorted([d for d in docs if d["direction"] == "compra"], key=key)
    sales = sorted([d for d in docs if d["direction"] == "venta"], key=key)

    inv_qty, inv_cost = 0.0, 0.0
    p_idx = 0
    sale_costs = {}
    for d in sales:
        # 先把日期不晚于本次出货的进货全部入库
        while p_idx < len(purchases) and (purchases[p_idx]["date"] or "9999") <= (d["date"] or "9999"):
            p = purchases[p_idx]
            pq = sum(it["qty"] for it in p.get("items", []) or [])
            if pq > 0:
                inv_qty += pq
                inv_cost += (p["total"] or 0) - (p["iva_amount"] or 0)  # 不含税成本
            p_idx += 1

        qty = sum(it["qty"] for it in d.get("items", []) or [])
        if qty <= 0:
            sale_costs[d["id"]] = 0.0
            continue
        avg = inv_cost / inv_qty if inv_qty > 0 else 0.0
        # 优先使用行项目中的单位成本；否则用加权平均成本
        cost_total = sum((it.get("cost_unit", 0) or 0) * (it.get("qty", 0) or 0)
                         for it in d.get("items", []) or [])
        if cost_total <= 0:
            cost_total = avg * qty
        # 扣减库存（允许负库存但成本保留）
        take = min(qty, inv_qty)
        if inv_qty > 0:
            inv_cost -= avg * take
        inv_qty = max(0.0, inv_qty - qty)

        sale_costs[d["id"]] = cost_total
    return sale_costs


# ---------------------------------------------------------------- 科目表 / 期初
# 科目表为空（旧库）时的回退科目（西班牙 PGC 常量）
FALLBACK_ACCOUNTS = {
    "cash": config.ACCOUNT_CASH,        # 现钞 → 库存现金
    "bank": config.ACCOUNT_BANK,        # 银行卡 → 银行存款
    "crypto": config.ACCOUNT_CRYPTO,    # 加密稳定币 → 其他货币资金
    "inventory": config.ACCOUNT_INVENTORY,
    "sales": config.ACCOUNT_SALES,
    "cost_of_sales": config.ACCOUNT_COST_OF_SALES,
    "iva_input": config.ACCOUNT_IVA_INPUT,
    "iva_output": config.ACCOUNT_IVA_OUTPUT,
    "capital": config.ACCOUNT_CAPITAL,
    "receivable": config.ACCOUNT_CUSTOMERS,
    "payable": config.ACCOUNT_SUPPLIERS,
    "expense_salary": config.ACCOUNT_EXPENSE_SALARY,
    "expense_welfare": config.ACCOUNT_EXPENSE_WELFARE,
    "expense_tax": config.ACCOUNT_EXPENSE_TAX,
    "expense_utilities": config.ACCOUNT_EXPENSE_UTILITIES,
    "expense_rent": config.ACCOUNT_EXPENSE_RENT,
    "expense_other": config.ACCOUNT_EXPENSE_OTHER,
}


def _child_codes(chart: dict, code: str) -> list:
    """科目的直接下级编码（优先 parent 字段，缺失时按编码前缀推断）。"""
    kids = [c for c, n in chart.items()
            if c != code and ((n or {}).get("parent") or "").strip() == code]
    if not kids:
        kids = [c for c in chart
                if c.startswith(code) and len(c) > len(code)
                and not ((chart.get(c) or {}).get("parent") or "").strip()]
    return sorted(kids)


def _leaf_account(chart: dict, code: str, depth: int = 0) -> str:
    """把科目下钻到末级（叶子）科目。

    报表里父科目是「自动汇总行」，金额若直接记在父科目上，
    末级科目合计就会漏掉这笔（科目余额表借贷不平），所以统一落到叶子科目。
    """
    cur = code or ""
    for _ in range(6):
        if cur not in chart:
            return cur
        kids = _child_codes(chart, cur)
        if not kids:
            return cur
        # 优先「其他/杂项」明细，其次第一个明细
        pick = kids[0]
        for k in kids:
            nm = (chart.get(k) or {}).get("name") or ""
            if "其他" in nm or "杂项" in nm:
                pick = k
                break
        cur = pick
    return cur


def resolve_expense_account(chart: dict, category: str, label: str = "") -> str:
    """支出日报的「费用类别」→ 科目编码。

    1) 类别 key（salary / utilities …）→ config.EXPENSE_ACCOUNT_KEYS；
    2) 类别显示名（如「水电费」）反查内置类别 key；
    3) 自定义类别（如「设备维修费」）在损益类科目里按名称匹配；
    4) 仍匹配不到时回退「其他费用」；最后统一下钻到末级科目。
    """
    cat = (category or "").strip()
    lab = (label or "").strip()
    key = config.EXPENSE_ACCOUNT_KEYS.get(cat, "")
    if not key:
        key = config.EXPENSE_ACCOUNT_KEYS.get(lab, "")
    if not key:
        for ck, cl in config.EXPENSE_CATEGORIES:
            if cat in (ck, cl) or (lab and lab in (ck, cl)):
                key = config.EXPENSE_ACCOUNT_KEYS.get(ck, "")
                if key:
                    break
    if not key:
        hit = _find_account_by_name(chart, cat or lab, "pnl")
        if hit:
            return _leaf_account(chart, hit)
        key = "expense_other"
    code = resolve_account(chart, key)
    if not code:
        code = resolve_account(chart, "expense_other")
    return _leaf_account(chart, code)


def _find_account_by_name(chart: dict, text: str, category: str = None) -> str:
    """按科目名称匹配：精确 → 包含 → 名称前缀（「水电费」命中「水电管理费」）。"""
    t = (text or "").strip()
    if not t:
        return ""

    def _ok(code):
        return (not category
                or config.account_category(code) == category)

    for code in sorted(chart):
        if (chart[code] or {}).get("name") == t and _ok(code):
            return code
    for n in range(len(t), 1, -1):        # 逐步缩短：水电费 → 水电
        sub = t[:n]
        for code in sorted(chart):
            name = (chart[code] or {}).get("name") or ""
            if sub and sub in name and _ok(code):
                return code
    return ""


def load_chart_index() -> dict:
    """{code: {"name", "direction", "is_leaf", "parent"}}"""
    try:
        rows = database.list_chart_of_accounts()
    except Exception:  # noqa: BLE001
        return {}
    return {r["code"]: r for r in rows}


def resolve_account(chart: dict, key: str) -> str:
    """按 config.ACCOUNTING_MAP 解析业务科目：先候选编码，再名称关键字，最后回退常量。"""
    codes, keywords = config.ACCOUNTING_MAP.get(key, ([], []))
    for c in codes:
        if c in chart:
            return c
    for c in sorted(chart):
        name = (chart[c] or {}).get("name") or ""
        if any(k in name for k in keywords):
            return c
    return FALLBACK_ACCOUNTS.get(key, "")


# ------------------------------------------------ 付款方式 ↔ 货币资金大类
# 付款方式下拉固定为货币资金**三大类**（1001 库存现金 / 1002 银行存款 /
# 1012 其他货币资金），与收入日报支付来源一一对应；入账时按币种下钻明细科目。
FUND_ROOT_CODES = ("1001", "1002", "1012")
# 科目表未初始化 / 缺该一级科目时的默认名称（与收入日报支付来源一一对应）
FUND_ROOT_NAMES = {"1001": "库存现金", "1002": "银行存款",
                   "1012": "其他货币资金"}


def _fund_root(code: str) -> str:
    for root in FUND_ROOT_CODES:
        if str(code or "").startswith(root):
            return root
    return ""


def payment_account_options() -> list:
    """付款方式下拉项：货币资金**三大类**（与收入日报的支付来源对齐）。

      库存现金（1001） ← 收入来源「现钞」
      银行存款（1002） ← 收入来源「银行卡」
      其他货币资金（1012）← 收入来源「电子支付/扫码」

    返回 [{'code','name','label','root'}]；名称取科目表里的一级科目名，
    科目表未初始化时用默认名称。入账时再按币种下钻到该类的明细科目
    （见 _currency_leaf：库存现金 + USD → 库存现金（USD））。
    """
    chart = load_chart_index()
    out = []
    for root in FUND_ROOT_CODES:
        node = chart.get(root) or {}
        name = (node.get("name") or "").strip() or FUND_ROOT_NAMES.get(root, root)
        out.append({"code": root, "name": name, "label": name, "root": root})
    return out


def payment_account_labels() -> list:
    """付款方式下拉显示文本列表。"""
    return [o["label"] for o in payment_account_options()]


def resolve_payment_account(method: str) -> str:
    """付款方式文本 → 科目编码。

    先按科目编码 / 科目名称精确匹配（同名子科目优先），再按关键字回退
    （现金→库存现金、银行卡→银行存款、电子支付→其他货币资金）。
    """
    text = (method or "").strip()
    if not text:
        return ""
    chart = load_chart_index()
    if text in chart:
        return text
    for code, node in chart.items():
        if (node or {}).get("name") == text:
            return code
    for opt in payment_account_options():
        if opt["label"] == text or (opt["name"] and opt["name"] in text):
            return opt["code"]
    if "现金" in text:
        return resolve_account(chart, "cash")
    if "银行" in text or "卡" in text:
        return resolve_account(chart, "bank")
    if "电子" in text or "扫码" in text or "USDT" in text.upper():
        return resolve_account(chart, "crypto")
    return ""


def payment_channel(method: str) -> str:
    """付款方式 → 资金渠道：bank（银行）/ cash（现金）。

    兼容旧数据里的「银行卡」「现金」文本。
    """
    text = (method or "").strip()
    if not text:
        return ""
    if text == config.PAY_METHOD_CARD:
        return "bank"
    if text == config.PAY_METHOD_CASH:
        return "cash"
    code = resolve_payment_account(text) or resolve_account(
        load_chart_index(), "bank")
    root = _fund_root(code)
    if root == "1001":
        return "cash"
    if root in ("1002", "1012"):
        return "bank"
    return ""


def opening_balances(year=None) -> dict:
    """科目表期初余额（signed：借正贷负）。

    损益类科目（5xxx）另计“本年累计损益发生额 pnl_cum”，
    使利润表为年初至报表截止日的累计口径。
    """
    try:
        rows = database.list_opening_balances(year=year)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        sign = -1 if (r.get("direction") == "贷") else 1
        amt = float(r.get("period_balance") or 0)
        if config.account_category(r["code"]) == "pnl":
            amt += float(r.get("pnl_cum") or 0)
        if amt:
            out[r["code"]] = out.get(r["code"], 0.0) + sign * amt
    return out


def opening_source(year=None, capital=0.0) -> str:
    """报表期初数据来自哪里（用于界面/ PDF 提示）。"""
    if any(opening_balances(year).values()):
        return f"科目表期初余额（{year or '全部年度'}）"
    if capital:
        return "设置中的期初资本（科目表期初未录入）"
    return "无期初余额"


# ---------------------------------------------------------------- 科目余额
def compute_movements(docs, capital=0.0, year=None, costs=None, entries=None):
    """返回 (科目余额 {code: signed}, 本期发生额 {code: {'debit', 'credit'}})。

    约定借方为正、贷方为负；期初余额不计入本期发生额。
    entries：额外的本期分录 [(科目编码, signed 金额)]，
    用于把店铺收入/支出日报（不生成单据的模块）并入报表。
    """
    chart = load_chart_index()
    acc = {k: resolve_account(chart, k) for k in FALLBACK_ACCOUNTS}
    bal = {}
    moves = {}

    def add(code, amount, move=True):
        if not code:
            return
        code = _leaf_account(chart, code)
        bal[code] = bal.get(code, 0.0) + amount
        if not move:      # 期初不算本期发生额
            return
        mv = moves.setdefault(code, {"debit": 0.0, "credit": 0.0})
        if amount >= 0:
            mv["debit"] += amount
        else:
            mv["credit"] += -amount

    # 期初：优先科目表期初余额，否则回退设置中的期初资本
    opening = opening_balances(year)
    if any(opening.values()):
        for code, amt in opening.items():
            add(code, amt, move=False)
    elif capital:
        add(acc["cash"], float(capital), move=False)
        add(acc["capital"], -float(capital), move=False)

    if costs is None:
        costs = _running_avg_cost(docs)
    for d in docs:
        base = d["base"] or 0.0
        iva = d["iva_amount"] or 0.0
        total = d["total"] or 0.0
        if d["direction"] == "compra":
            add(acc["inventory"], base)
            add(acc["iva_input"], iva)
            add(acc["cash"], -total)
        else:  # venta
            cost = costs.get(d["id"], 0.0)
            add(acc["cash"], total)
            add(acc["sales"], -base)
            add(acc["iva_output"], -iva)
            add(acc["cost_of_sales"], cost)
            add(acc["inventory"], -cost)
            d["cost_total"] = cost

    # 店铺收入 / 支出日报（模块间关联：日报数据同样进报表）
    for code, amount in (entries or []):
        add(code, amount)

    return bal, moves


def compute_balances(docs, capital=0.0, year=None, costs=None,
                     entries=None) -> dict:
    """返回科目余额 dict {account_code: signed}，约定借方为正、贷方为负。"""
    bal, _moves = compute_movements(docs, capital, year, costs, entries)
    return bal


def _set_sale_costs(docs, costs):
    for d in docs:
        if d["direction"] == "venta":
            d["cost_total"] = costs.get(d["id"], 0.0)
    return docs


# ---------------------------------------------------------------- 报表结构
def build_balance_sheet(docs, capital=0.0, year=None, entries=None) -> dict:
    """资产负债表：按科目表分组（资产 1xxx/4xxx、负债 2xxx、权益 3xxx/6xxx + 本期损益）。"""
    chart = load_chart_index()
    bal = compute_balances(docs, capital, year, entries=entries)

    activo, pasivo, patrimonio = [], [], []
    for code in sorted(bal):
        signed = bal[code]
        if abs(signed) < 0.005:
            continue
        name = (chart.get(code, {}) or {}).get("name") or config.ACCOUNT_NAMES.get(code, "")
        row = {"name": f"{code} {name}".strip(), "code": code}
        cat = config.account_category(code)
        if cat == "asset":
            activo.append({**row, "amount": round(signed, 2)})
        elif cat == "liability":
            pasivo.append({**row, "amount": round(-signed, 2)})
        elif cat == "equity":
            patrimonio.append({**row, "amount": round(-signed, 2)})

    # 本期损益 = 损益类科目余额的相反数（收入贷方 - 成本费用借方）
    result = round(-sum(v for k, v in bal.items()
                        if config.account_category(k) == "pnl"), 2)
    patrimonio.append({"name": "本年利润（本期损益）", "code": "pnl", "amount": result})

    total_activo = round(sum(x["amount"] for x in activo), 2)
    total_pasivo = round(sum(x["amount"] for x in pasivo), 2)
    total_pat = round(sum(x["amount"] for x in patrimonio), 2)
    total_pasivo_pat = round(total_pasivo + total_pat, 2)

    return {
        "activo": activo, "pasivo": pasivo, "patrimonio": patrimonio,
        "total_activo": total_activo, "total_pasivo": total_pasivo,
        "total_pat": total_pat, "total_pasivo_pat": total_pasivo_pat,
        "resultado": result, "year": year,
        "opening_source": opening_source(year, capital),
        "balanced": abs(total_activo - total_pasivo_pat) < 0.01,
        "diff": round(total_activo - total_pasivo_pat, 2),
    }


def build_income_statement(docs, year=None, entries=None) -> dict:
    """利润表：按损益类科目（5xxx）生成，含期初“本年累计损益发生额”。"""
    chart = load_chart_index()
    costs = _running_avg_cost(docs)
    docs = _set_sale_costs(docs, costs)
    bal = compute_balances(docs, capital=0.0, year=year, costs=costs,
                           entries=entries)

    income_rows, expense_rows = [], []
    for code in sorted(bal):
        signed = bal[code]
        if config.account_category(code) != "pnl" or abs(signed) < 0.005:
            continue
        name = (chart.get(code, {}) or {}).get("name") or config.ACCOUNT_NAMES.get(code, code)
        row = {"name": f"{code} {name}".strip(), "code": code,
               "amount": round(-signed if signed < 0 else signed, 2), "indent": 1}
        (income_rows if signed < 0 else expense_rows).append(row)

    ventas = round(sum(r["amount"] for r in income_rows), 2)
    coste = round(sum(r["amount"] for r in expense_rows), 2)
    margen = round(ventas - coste, 2)

    iva_in = bal.get(resolve_account(chart, "iva_input"), 0.0)
    iva_out = -bal.get(resolve_account(chart, "iva_output"), 0.0)
    iva_neto = round(iva_in - iva_out, 2)   # 正=可退/抵，负=应交

    rows = [
        {"name": "营业收入", "amount": ventas, "indent": 0, "bold": True},
        *income_rows,
        {"name": "营业成本及费用", "amount": -coste, "indent": 0, "bold": True},
        *expense_rows,
        {"name": "本期净利润（收入 − 成本费用）", "amount": margen,
         "indent": 0, "bold": True},
    ]
    return {
        "rows": rows, "ventas": ventas, "coste": coste,
        "margen": margen, "resultado": margen,
        "iva_neto": iva_neto, "year": year,
        "opening_source": opening_source(year, 0.0),
        "num_venta": sum(1 for d in docs if d["direction"] == "venta"),
        "num_compra": sum(1 for d in docs if d["direction"] == "compra"),
    }


def _ancestor_codes(chart: dict, code: str) -> list:
    """科目的所有上级科目编码（由近到远）。"""
    out, seen = [], {code}
    cur = ((chart.get(code) or {}).get("parent") or "").strip()
    if not cur:      # 科目表未维护 parent 时按编码前缀推断
        for i in range(len(code) - 1, 1, -1):
            if code[:i] in chart:
                cur = code[:i]
                break
    while cur and cur in chart and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = ((chart[cur] or {}).get("parent") or "").strip()
    return out


def build_trial_balance(docs, capital=0.0, year=None, entries=None) -> dict:
    """科目余额表：列出全部科目（按层级缩进，父科目自动汇总其明细）。

    每行含 期初余额（借/贷）、本期发生额（借/贷）、期末余额（借/贷）。
    """
    chart = load_chart_index()
    _bal, moves = compute_movements(docs, capital, year, entries=entries)
    opening = opening_balances(year)
    if not any(opening.values()) and capital:
        acc = {k: resolve_account(chart, k) for k in FALLBACK_ACCOUNTS}
        opening = {acc["cash"]: float(capital),
                   acc["capital"]: -float(capital)}

    parents = set()
    codes = sorted(set(chart) | set(moves) | set(opening))
    for code in codes:
        parents.update(_ancestor_codes(chart, code))

    own = {}
    for code in codes:
        op = float(opening.get(code, 0.0) or 0)
        mv = moves.get(code) or {}
        debit = float(mv.get("debit", 0.0))
        credit = float(mv.get("credit", 0.0))
        own[code] = {"opening": op, "debit": debit, "credit": credit,
                     "ending": op + debit - credit}

    agg = {c: dict(v) for c, v in own.items()}
    for code in codes:
        for anc in _ancestor_codes(chart, code):
            node = agg.setdefault(
                anc, {"opening": 0.0, "debit": 0.0, "credit": 0.0,
                      "ending": 0.0})
            for k in ("opening", "debit", "credit", "ending"):
                node[k] += own[code][k]

    rows = []
    for code in sorted(agg):
        v = agg[code]
        node = chart.get(code) or {}
        name = node.get("name") or config.ACCOUNT_NAMES.get(code, code)
        level = len(_ancestor_codes(chart, code))
        rows.append({
            "code": code,
            "name": ("　" * level) + str(name),
            "plain_name": str(name),
            "level": level,
            "is_parent": code in parents,
            "opening_debit": round(v["opening"] if v["opening"] > 0 else 0.0, 2),
            "opening_credit": round(-v["opening"] if v["opening"] < 0 else 0.0, 2),
            "debit": round(v["debit"], 2),
            "credit": round(v["credit"], 2),
            "ending_debit": round(v["ending"] if v["ending"] > 0 else 0.0, 2),
            "ending_credit": round(-v["ending"] if v["ending"] < 0 else 0.0, 2),
        })

    keys = ("opening_debit", "opening_credit", "debit", "credit",
            "ending_debit", "ending_credit")
    leaves = [r for r in rows if not r["is_parent"]]
    totals = {k: round(sum(r[k] for r in leaves), 2) for k in keys}
    return {"rows": rows, "totals": totals, "year": year,
            "opening_source": opening_source(year, capital)}


def _currency_words(currency) -> list:
    """币种的识别词（代码 / 中文名 / 旧代码），用于匹配按币种命名的明细科目。"""
    cur = config.normalize_currency(currency) or ""
    if not cur:
        return []
    words = {cur.upper()}
    zh = config.CURRENCY_ZH.get(cur)
    if zh:
        words.add(zh.upper())
    if cur == "Bs":
        words.update({"VES", "VED", "玻利瓦尔"})
    if cur == "USDT":
        words.add("泰达币")
    return [w for w in words if w]


def _currency_leaf(chart: dict, code: str, currency) -> str:
    """货币资金科目按币种选明细叶子。

    例如 1001 库存现金 → 100101 库存现金（Bs）/ 100102 库存现金（USD）；
    匹配不到币种明细时回退该科目下的第一个末级科目。
    """
    if not code or code not in chart:
        return code
    words = _currency_words(currency)
    leaves = [c for c in chart
              if c.startswith(code) and not _child_codes(chart, c)]
    if not leaves:
        return code
    for c in sorted(leaves):
        nm = str((chart.get(c) or {}).get("name") or "").strip().upper()
        if not nm:
            continue
        if nm in words or any(w and w in nm for w in words):
            return c
    return _leaf_account(chart, code)


def daily_book_entries(date_from=None, date_to=None, settings: dict = None):
    """把「店铺收入日报 + 店铺支出日报」生成报表分录。

    模块关联：这两个模块不生成单据，以前进不了财务报表，现在按下列口径入账：

      收入日报：借 货币资金（支付方式+币种 → 库存现金/银行存款/其他货币资金
                  的币种明细，如 库存现金（Bs）/ 库存现金（USD））
               贷 主营业务收入
      支出日报：借 费用科目（费用类别 → 工资/福利/水电/租赁/税金/其他）
               贷 货币资金（付款方式对应的明细科目）

    说明：金额按**原币入账，不做汇率折算**（Bs 记 Bs 明细科目、USD 记 USD 明细科目）。
    返回 (entries, stats, unconverted)。
    """
    settings = settings if settings is not None else load_settings()
    chart = load_chart_index()

    def _iso(d):
        return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else d

    d_from, d_to = _iso(date_from), _iso(date_to)

    entries = []
    stats = {"income_count": 0, "income_amount": 0.0,
             "expense_count": 0, "expense_amount": 0.0}
    unconverted = []

    try:
        income_rows = database.list_daily_income_rows(d_from, d_to)
    except Exception:  # noqa: BLE001  旧库缺表时跳过
        income_rows = []
    sales_acc = resolve_account(chart, "sales")
    for r in income_rows:
        amt = float(r.get("amount") or 0)
        if not amt:
            continue
        cur = config.normalize_currency(r.get("currency")) or config.DEFAULT_BASE_CURRENCY
        fund_root = resolve_account(
            chart, config.income_account_key(r.get("source"), cur))
        fund_acc = _currency_leaf(chart, fund_root, cur)
        entries.append((fund_acc, amt))           # 借：货币资金（按币种明细）
        entries.append((sales_acc, -amt))         # 贷：主营业务收入
        stats["income_count"] += 1
        stats["income_amount"] += amt

    try:
        expense_rows = database.list_daily_expense_items(d_from, d_to)
    except Exception:  # noqa: BLE001  旧库缺表时跳过
        expense_rows = []
    for r in expense_rows:
        amt = float(r.get("amount") or 0)
        if not amt:
            continue
        cur = config.normalize_currency(r.get("currency")) or config.DEFAULT_BASE_CURRENCY
        exp_acc = resolve_expense_account(
            chart, r.get("category"),
            database.expense_category_label(r.get("category")))
        pay_root = resolve_payment_account(r.get("method"))
        if not pay_root:
            channel = payment_channel(r.get("method"))
            pay_root = resolve_account(
                chart, channel if channel in ("cash", "bank") else "cash")
        pay_acc = _currency_leaf(chart, pay_root, cur)
        entries.append((exp_acc, amt))            # 借：费用
        entries.append((pay_acc, -amt))           # 贷：货币资金（按币种明细）
        stats["expense_count"] += 1
        stats["expense_amount"] += amt

    return entries, stats, unconverted


def get_report(doc_type: str, date_from=None, date_to=None, capital=0.0, year=None):
    """统一入口。doc_type: 'balance' / 'income' / 'trial'

    先把各单据金额按币种/汇率换算为本位币，再按科目表生成报表。
    期初余额取该会计年度（year 缺省时按报表起止日期推断）的科目表期初。
    """
    docs = database.list_documents(
        date_from=date_from and date_from.strftime("%Y-%m-%d"),
        date_to=date_to and date_to.strftime("%Y-%m-%d"))
    # 加载行项目（成本计算需要）
    for d in docs:
        full = database.get_document(d["id"])
        d["items"] = full.get("items", []) if full else []

    # 币种换算：统一到本位币（保留原值到 *_orig）
    settings = load_settings()
    base_currency = settings.get("base_currency") or config.DEFAULT_BASE_CURRENCY
    unconverted = []
    for d in docs:
        cur = d.get("currency") or base_currency
        doc_rate = d.get("exchange_rate") or 0.0
        d["base_orig"], ok_b = convert_to_base(d.get("base"), cur, settings, doc_rate)
        d["iva_amount_orig"], ok_i = convert_to_base(d.get("iva_amount"), cur, settings, doc_rate)
        d["total_orig"], ok_t = convert_to_base(d.get("total"), cur, settings, doc_rate)
        d["base"], d["iva_amount"], d["total"] = (
            d["base_orig"], d["iva_amount_orig"], d["total_orig"])
        if not (ok_b and ok_i and ok_t):
            unconverted.append(d.get("doc_number") or f"#{d['id']}")

    if year is None:
        ref = date_from or date_to
        year = str(ref.year) if ref is not None else str(datetime.date.today().year)

    # 店铺收入 / 支出日报 → 分录（与单据一起进报表）
    entries, daily_stats, daily_unconverted = daily_book_entries(
        date_from, date_to, settings)

    if doc_type == "trial":
        report = build_trial_balance(docs, capital, year, entries=entries)
    elif doc_type == "balance":
        report = build_balance_sheet(docs, capital, year, entries=entries)
    else:
        report = build_income_statement(docs, year, entries=entries)
    report["base_currency"] = base_currency
    report["sources"] = {
        "docs": len(docs),
        "income_rows": daily_stats["income_count"],
        "income_amount": round(daily_stats["income_amount"], 2),
        "expense_rows": daily_stats["expense_count"],
        "expense_amount": round(daily_stats["expense_amount"], 2),
    }
    report["currency_note"] = ""
    unconverted = unconverted + daily_unconverted
    if unconverted:
        report["currency_note"] = (
            f"注意：{len(unconverted)} 笔（单据/日报）币种或汇率缺失，金额按原值计入"
            f"（{', '.join(unconverted[:5])}{'…' if len(unconverted) > 5 else ''}），"
            "请检查币种与官方汇率设置。")
    return report, docs


# ---------------------------------------------------------------- PDF 导出
def export_pdf(doc_type: str, date_from=None, date_to=None, capital=0.0,
               out_path: str = None) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)

    report, docs = get_report(doc_type, date_from, date_to, capital)
    if not out_path:
        import os
        out_path = os.path.join(config.DATA_DIR,
                                f"informe_{doc_type}_{datetime.date.today().isoformat()}.pdf")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=16)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9)

    span = ""
    if date_from:
        span = f" desde {date_from.strftime('%d/%m/%Y')}"
    if date_to:
        span += f" hasta {date_to.strftime('%d/%m/%Y')}"

    def fmt(v):
        """报表金额只显示数字，不跟货币符号（各科目币种可能不同）。"""
        return format_amount(v, symbols=False)

    src = report.get("sources") or {}
    sources_line = (
        f"数据来源：单据 {src.get('docs', 0)} 张 · "
        f"店铺收入日报 {src.get('income_rows', 0)} 笔"
        f"（{fmt(src.get('income_amount', 0.0))}） · "
        f"店铺支出日报 {src.get('expense_rows', 0)} 笔"
        f"（{fmt(src.get('expense_amount', 0.0))}）")

    doc = SimpleDocTemplate(out_path, pagesize=A4, rightMargin=15*mm,
                            leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []
    if doc_type == "trial":
        story.append(Paragraph("BALANCE DE COMPROBACIÓN 科目余额表", title_style))
        story.append(Paragraph("（科目表 + 期初余额）" + span, h2))
        if report.get("opening_source"):
            story.append(Paragraph(f"期初来源：{report['opening_source']}", h2))
        if report.get("base_currency"):
            story.append(Paragraph(
                "金额按各科目币种明细列示（如 库存现金（Bs）/（USD）），"
                "不换算、不显示货币符号", h2))
        if report.get("currency_note"):
            story.append(Paragraph(report["currency_note"], h2))
        if sources_line:
            story.append(Paragraph(sources_line, h2))
        story.append(Spacer(1, 6*mm))

        head = ["编码", "科目名称", "期初借方", "期初贷方",
                "本期借方", "本期贷方", "期末借方", "期末贷方"]
        data = [[Paragraph(f"<b>{h}</b>", cell) for h in head]]
        for r in report["rows"]:
            nm = r["name"]
            if r.get("is_parent"):
                nm = "<b>%s</b>" % nm
            data.append([
                Paragraph(r["code"], cell), Paragraph(nm, cell),
                *[Paragraph(fmt(r[k]), cell) for k in (
                    "opening_debit", "opening_credit", "debit", "credit",
                    "ending_debit", "ending_credit")]])
        t = report.get("totals") or {}
        data.append([Paragraph("<b>合计</b>", cell), Paragraph("<b>（末级科目）</b>", cell),
                     *[Paragraph("<b>%s</b>" % fmt(t.get(k, 0.0)), cell)
                       for k in ("opening_debit", "opening_credit", "debit",
                                 "credit", "ending_debit", "ending_credit")]])
        tb = Table(data, colWidths=[22*mm, 56*mm, 17*mm, 17*mm, 17*mm, 17*mm,
                                    17*mm, 17*mm], repeatRows=1)
        tb.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f2f2f2")),
        ]))
        story.append(tb)
    elif doc_type == "balance":
        story.append(Paragraph("BALANCE DE SITUACIÓN 资产负债表", title_style))
        story.append(Paragraph("（科目表 + 期初余额）" + span, h2))
        if report.get("opening_source"):
            story.append(Paragraph(f"期初来源：{report['opening_source']}", h2))
        if report.get("base_currency"):
            story.append(Paragraph(
                "金额按各科目币种明细列示（如 库存现金（Bs）/（USD）），"
                "不换算、不显示货币符号", h2))
        if report.get("currency_note"):
            story.append(Paragraph(report["currency_note"], h2))
        if sources_line:
            story.append(Paragraph(sources_line, h2))
        story.append(Spacer(1, 6*mm))

        def seccion(title, rows, total, total_label):
            data = [[Paragraph("<b>%s</b>" % title, cell), ""]]
            for r in rows:
                data.append([Paragraph(r["name"], cell),
                             Paragraph(fmt(r["amount"]), cell)])
            data.append([Paragraph("<b>%s</b>" % total_label, cell),
                         Paragraph("<b>%s</b>" % fmt(total), cell)])
            return data

        all_rows = []
        all_rows += seccion("ACTIVO 资产", report["activo"], report["total_activo"], "TOTAL ACTIVO 资产合计")
        all_rows.append(["", ""])
        all_rows += seccion("PASIVO 负债", report["pasivo"],
                            sum(x["amount"] for x in report["pasivo"]), "TOTAL PASIVO 负债合计")
        all_rows += seccion("PATRIMONIO NETO 净资产", report["patrimonio"],
                            sum(x["amount"] for x in report["patrimonio"]), "TOTAL PN 净资产合计")
        all_rows.append(["", ""])
        all_rows.append([Paragraph("<b>PASIVO + PN 负债与净资产合计</b>", cell),
                         Paragraph("<b>%s</b>" % fmt(report["total_pasivo_pat"]), cell)])
        all_rows.append([Paragraph(("✓ 平衡" if report["balanced"] else
                                    f"✗ 不平衡（差额 {fmt(report['diff'])}）"), cell), ""])
        t = Table(all_rows, colWidths=[110*mm, 60*mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("SPAN", (0, 0), (1, 0)),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("CUENTA DE RESULTADOS 利润表", title_style))
        story.append(Paragraph("（科目表 + 期初余额）" + span, h2))
        if report.get("opening_source"):
            story.append(Paragraph(f"期初来源：{report['opening_source']}", h2))
        if report.get("base_currency"):
            story.append(Paragraph(
                "金额按各科目币种明细列示（如 库存现金（Bs）/（USD）），"
                "不换算、不显示货币符号", h2))
        if report.get("currency_note"):
            story.append(Paragraph(report["currency_note"], h2))
        if sources_line:
            story.append(Paragraph(sources_line, h2))
        story.append(Spacer(1, 6*mm))
        data = [["", "Importe 金额"]]
        for r in report["rows"]:
            name = r["name"]
            if r.get("bold"):
                name = "<b>%s</b>" % name
            amt = fmt(r["amount"])
            if r.get("bold"):
                amt = "<b>%s</b>" % amt
            data.append([Paragraph(name, cell), Paragraph(amt, cell)])
        data.append([Paragraph("<b>IVA neto 增值税净额（负=应交）</b>", cell),
                     Paragraph("<b>%s</b>" % fmt(report["iva_neto"]), cell)])
        data.append([Paragraph("Nº documentos 单据数：venta %d / compra %d"
                               % (report["num_venta"], report["num_compra"]), cell), ""])
        t = Table(data, colWidths=[130*mm, 40*mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(t)

    doc.build(story)
    return out_path
