"""结汇 / 兑换单的会计分录（凭证）生成。

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
        "from_book_value": amts["from_book_value"],
        "gain_loss": gain_loss,
        "balanced": True,
    }
