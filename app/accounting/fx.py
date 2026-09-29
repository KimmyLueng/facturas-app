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


def book_entries(date_from=None, date_to=None, chart: dict = None) -> tuple:
    """兑换单 → 财务报表分录（与 reports.daily_book_entries 同口径：借正贷负）。

    兑换必然涉及两种币种，报表只按金额汇总，因此**统一按本位币入账**
    （与单据口径一致），借贷自然平衡：

        借  库存现金（换入币种明细科目）    本位币到账 home_amount
        贷  库存现金（换出币种明细科目）    换出账面价值 from_amount × book_rate
        借/贷 汇兑损益                      差额（收益记贷方、损失记借方）

    from_book_value = home_amount − gain_loss，故 借 = 贷（恒等平衡）。

    返回 (entries, stats, unconverted)：
      entries = [(科目编码, 金额), ...]；
      stats = {fx_count, fx_amount（本位币到账合计）, fx_gain_loss}；
      unconverted = 缺汇率而无法折算的单据日期列表。
    """
    from app.db import database

    if chart is None:
        try:
            chart = reports.load_chart_index()
        except Exception:  # noqa: BLE001
            chart = {}

    def _iso(d):
        return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else d

    try:
        orders = database.list_fx_orders(_iso(date_from), _iso(date_to))
    except Exception:  # noqa: BLE001  旧库缺表时跳过
        orders = []

    entries = []
    stats = {"fx_count": 0, "fx_amount": 0.0, "fx_gain_loss": 0.0}
    unconverted = []

    cash_root = reports.resolve_account(chart, "cash")
    fx_acc = reports._leaf_account(
        chart, reports.resolve_account(chart, "fx") or config.ACCOUNT_FX)

    for o in orders or []:
        from_amt = float(o.get("from_amount") or 0)
        home = float(o.get("home_amount") or 0)
        gain = float(o.get("gain_loss") or 0)
        if not from_amt:
            continue
        if not home:      # 成交汇率/官方汇率缺失，无法折算为本位币
            unconverted.append(o.get("date") or f"#{o.get('id')}")
            continue
        book_value = round(home - gain, 4)     # 换出原币的账面本位币价值
        to_acc = reports._currency_leaf(chart, cash_root, o.get("to_currency"))
        from_acc = reports._currency_leaf(chart, cash_root, o.get("from_currency"))
        entries.append((to_acc, home))         # 借：换入币种现金（本位币到账）
        entries.append((from_acc, -book_value))  # 贷：换出币种现金（账面价值）
        entries.append((fx_acc, -gain))        # 贷：汇兑收益（损失为借）
        stats["fx_count"] += 1
        stats["fx_amount"] += home
        stats["fx_gain_loss"] += gain

    return entries, stats, unconverted
