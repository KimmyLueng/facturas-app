"""外币兑换单的会计分录（凭证）生成。

一笔兑换：
   借  库存现金（换入币种）            换入原币金额（折合本位币 = 本位币到账）
   贷  库存现金（换出币种）            换出原币金额（账面折合 = 换出原币 × 账面汇率）
   借/贷  汇兑损益                    差额（本位币到账 − 换出账面折合）

约定：借方为正、贷方为负（与 reports.daily_book_entries 一致）。
库存现金按币种下钻到明细科目（如 库存现金（USD）/ 库存现金（Bs））。
"""
from app import config
from app.accounting import reports


def compute_amounts(from_amount: float, book_rate: float,
                    settle_rate: float) -> dict:
    """根据原币金额与两个汇率，计算本位币到账与汇兑损益。"""
    from_amount = float(from_amount or 0)
    book_rate = float(book_rate or 0)
    settle_rate = float(settle_rate or 0)
    home_amount = round(from_amount * settle_rate, 4)
    gain_loss = round(home_amount - from_amount * book_rate, 4)
    return {
        "home_amount": home_amount,
        "from_book_value": round(from_amount * book_rate, 4),
        "gain_loss": gain_loss,
    }


def build_voucher(order: dict, chart: dict = None) -> dict:
    """为一条 fx_orders 记录生成凭证（用于界面展示 / 导出）。

    返回 {
        'entries': [ {account, account_name, debit, credit, currency, amount_str}, ... ],
        'home_amount', 'from_book_value', 'gain_loss', 'balanced'
    }
    cash 科目按原币列示，汇兑损益按本位币列示。
    """
    order = order or {}
    from_currency = (order.get("from_currency") or "").strip()
    to_currency = (order.get("to_currency") or "").strip()
    from_amount = float(order.get("from_amount") or 0)
    book_rate = float(order.get("book_rate") or 0)
    settle_rate = float(order.get("settle_rate") or 0)
    to_amount = float(order.get("to_amount") or 0)

    amts = compute_amounts(from_amount, book_rate, settle_rate)
    home_amount = amts["home_amount"]
    gain_loss = amts["gain_loss"]

    if chart is None:
        try:
            chart = reports.load_chart_index()
        except Exception:  # noqa: BLE001
            chart = {}
    cash_root = reports.resolve_account(chart, "cash")
    from_acc = reports._currency_leaf(chart, cash_root, from_currency)
    to_acc = reports._currency_leaf(chart, cash_root, to_currency)
    fx_acc = reports.resolve_account(chart, "fx") or config.ACCOUNT_FX

    def _name(code):
        return (chart.get(code) or {}).get("name") or code

    entries = []
    # 借：换入币种现金（原币）
    entries.append({
        "account": to_acc, "account_name": _name(to_acc),
        "debit": to_amount, "credit": 0.0,
        "currency": to_currency, "amount_str": f"{to_amount:,.2f} {to_currency}",
    })
    # 贷：换出币种现金（原币）
    entries.append({
        "account": from_acc, "account_name": _name(from_acc),
        "debit": 0.0, "credit": from_amount,
        "currency": from_currency, "amount_str": f"{from_amount:,.2f} {from_currency}",
    })
    # 汇兑损益（本位币）：gain>0 表示收益→贷方；loss<0 表示损失→借方
    if gain_loss >= 0:
        entries.append({
            "account": fx_acc, "account_name": _name(fx_acc),
            "debit": 0.0, "credit": gain_loss,
            "currency": "", "amount_str": f"{gain_loss:,.2f} 本位币",
        })
    else:
        entries.append({
            "account": fx_acc, "account_name": _name(fx_acc),
            "debit": -gain_loss, "credit": 0.0,
            "currency": "", "amount_str": f"{-gain_loss:,.2f} 本位币",
        })

    return {
        "entries": entries,
        "home_amount": home_amount,
        "to_amount": to_amount,
        "from_book_value": amts["from_book_value"],
        "gain_loss": gain_loss,
        "balanced": True,
    }


def book_entries(date_from=None, date_to=None, chart: dict = None,
                 rate_kind: str = "manual") -> tuple:
    """兑换单 → 财务报表分录（与 reports.daily_book_entries 同口径：借正贷负）。

    与兑换单凭证一致：**现金两腿按原币入账**，汇兑损益单独列（本位币）：

        借  库存现金（换入币种明细科目）      换入原币 to_amount
        贷  库存现金（换出币种明细科目）      换出原币 from_amount
        借/贷 汇兑损益（本位币）              本位币到账 − 换出账面价值
        借/贷 货币折算差额（权益类）          两腿原币直接相加的差额（对冲）

    最后一行是对冲：报表把各币种金额直接相加，而 换入原币 ≠ 换出原币，
    差额记入权益类「货币折算差额」（类似外币报表折算差额），
    这样科目余额表 / 资产负债表仍然借贷平衡，且利润表里的
    「汇兑损益」保持真实的经济金额（不会被这个差额污染）。

    参数 rate_kind：缺失本位币到账时的换算口径
        'manual'/'auto' — 优先单据手改汇率（rate/settle_rate）→ BCV → 平行
        'bcv'           — BCV 官方 → 平行 → 手改
        'parallel'      — 平行市场 → BCV → 手改

    返回 (entries, stats, unconverted)：
      entries = [(科目编码, 金额), ...]；
      stats = {fx_count, fx_amount（换入原币合计）, fx_gain_loss, fx_diff}；
      unconverted = 缺汇率而无法折算的单据日期列表。
    """
    from app.accounting import rates as rates_mod
    from app.db import database

    if chart is None:
        try:
            chart = reports.load_chart_index()
        except Exception:  # noqa: BLE001
            chart = {}

    rk = (rate_kind or "manual").lower()
    prefer = rates_mod.KIND_CHAINS.get(
        rk, rates_mod.KIND_CHAINS[rates_mod.RATE_MANUAL])

    def _iso(d):
        return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else d

    try:
        orders = database.list_fx_orders(_iso(date_from), _iso(date_to))
    except Exception:  # noqa: BLE001  旧库缺表时跳过
        orders = []

    entries = []
    stats = {"fx_count": 0, "fx_amount": 0.0, "fx_gain_loss": 0.0,
             "fx_diff": 0.0}
    unconverted = []

    cash_root = reports.resolve_account(chart, "cash")
    fx_acc = reports._leaf_account(
        chart, reports.resolve_account(chart, "fx") or config.ACCOUNT_FX)
    diff_acc = reports._leaf_account(
        chart, reports.resolve_account(chart, "fx_diff")
        or config.ACCOUNT_FX_DIFF)

    for o in orders or []:
        from_amt = float(o.get("from_amount") or 0)
        to_amt = float(o.get("to_amount") or 0)
        home = float(o.get("home_amount") or 0)
        gain = float(o.get("gain_loss") or 0)
        if not from_amt:
            continue
        odate = o.get("date") or ""
        # 本位币到账缺失时自动重算：优先单据自带 settle_rate（手改成交汇率），
        # 否则按换入金额 × 换入币种汇率（口径按 rate_kind 兜底链）折算
        if not home:
            settle = float(o.get("settle_rate") or 0)
            if settle > 0:
                home = round(from_amt * settle, 4)
            elif to_amt:
                tb = rates_mod.to_base_chain(o.get("to_currency"), odate, prefer)
                if tb > 0:
                    home = round(float(to_amt) * tb, 4)
        # 换出账面价值缺失时同样按口径重算
        book = float(o.get("book_rate") or 0)
        if not book:
            book = rates_mod.to_base_chain(o.get("from_currency"), odate, prefer)
            if book > 0:
                gain = round(home - from_amt * book, 4)
        if not to_amt or not home:   # 成交汇率/官方汇率缺失，无法折算
            unconverted.append(o.get("date") or f"#{o.get('id')}")
            continue
        to_acc = reports._currency_leaf(chart, cash_root, o.get("to_currency"))
        from_acc = reports._currency_leaf(chart, cash_root, o.get("from_currency"))
        # 原币两腿 + 本位币汇兑损益 的差额 → 权益类「货币折算差额」对冲
        diff = round(from_amt + gain - to_amt, 4)
        entries.append((to_acc, to_amt))        # 借：换入币种现金（换入原币）
        entries.append((from_acc, -from_amt))   # 贷：换出币种现金（换出原币）
        entries.append((fx_acc, -gain))         # 贷：汇兑收益（损失为借）
        if diff:
            entries.append((diff_acc, diff))
        stats["fx_count"] += 1
        stats["fx_amount"] += to_amt
        stats["fx_gain_loss"] += gain
        stats["fx_diff"] += diff

    return entries, stats, unconverted
