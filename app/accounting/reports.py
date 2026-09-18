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
}


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
def compute_balances(docs, capital=0.0, year=None, costs=None) -> dict:
    """返回科目余额 dict {account_code: signed}，约定借方为正、贷方为负。"""
    chart = load_chart_index()
    acc = {k: resolve_account(chart, k) for k in FALLBACK_ACCOUNTS}
    bal = {}

    def add(code, amount):
        if code:
            bal[code] = bal.get(code, 0.0) + amount

    # 期初：优先科目表期初余额，否则回退设置中的期初资本
    opening = opening_balances(year)
    if any(opening.values()):
        for code, amt in opening.items():
            add(code, amt)
    elif capital:
        add(acc["cash"], float(capital))
        add(acc["capital"], -float(capital))

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
    return bal


def _set_sale_costs(docs, costs):
    for d in docs:
        if d["direction"] == "venta":
            d["cost_total"] = costs.get(d["id"], 0.0)
    return docs


# ---------------------------------------------------------------- 报表结构
def build_balance_sheet(docs, capital=0.0, year=None) -> dict:
    """资产负债表：按科目表分组（资产 1xxx/4xxx、负债 2xxx、权益 3xxx/6xxx + 本期损益）。"""
    chart = load_chart_index()
    bal = compute_balances(docs, capital, year)

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


def build_income_statement(docs, year=None) -> dict:
    """利润表：按损益类科目（5xxx）生成，含期初“本年累计损益发生额”。"""
    chart = load_chart_index()
    costs = _running_avg_cost(docs)
    docs = _set_sale_costs(docs, costs)
    bal = compute_balances(docs, capital=0.0, year=year, costs=costs)

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


def get_report(doc_type: str, date_from=None, date_to=None, capital=0.0, year=None):
    """统一入口。doc_type: 'balance' / 'income'

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
    if doc_type == "balance":
        report = build_balance_sheet(docs, capital, year)
    else:
        report = build_income_statement(docs, year)
    report["base_currency"] = base_currency
    report["currency_note"] = ""
    if unconverted:
        report["currency_note"] = (
            f"注意：{len(unconverted)} 张单据币种/汇率缺失，金额按原值计入"
            f"（{', '.join(unconverted[:5])}{'…' if len(unconverted) > 5 else ''}），"
            "请检查单据币种与官方汇率设置。")
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
        from app import config
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

    doc = SimpleDocTemplate(out_path, pagesize=A4, rightMargin=15*mm,
                            leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []
    if doc_type == "balance":
        story.append(Paragraph("BALANCE DE SITUACIÓN 资产负债表", title_style))
        story.append(Paragraph("（科目表 + 期初余额）" + span, h2))
        if report.get("opening_source"):
            story.append(Paragraph(f"期初来源：{report['opening_source']}", h2))
        if report.get("base_currency"):
            story.append(Paragraph(f"币种：本位币 {report['base_currency']}", h2))
        if report.get("currency_note"):
            story.append(Paragraph(report["currency_note"], h2))
        story.append(Spacer(1, 6*mm))

        def seccion(title, rows, total, total_label):
            data = [[Paragraph("<b>%s</b>" % title, cell), ""]]
            for r in rows:
                data.append([Paragraph(r["name"], cell),
                             Paragraph(format_amount(r["amount"]), cell)])
            data.append([Paragraph("<b>%s</b>" % total_label, cell),
                         Paragraph("<b>%s</b>" % format_amount(total), cell)])
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
                         Paragraph("<b>%s</b>" % format_amount(report["total_pasivo_pat"]), cell)])
        all_rows.append([Paragraph(("✓ 平衡" if report["balanced"] else
                                    f"✗ 不平衡（差额 {format_amount(report['diff'])}）"), cell), ""])
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
            story.append(Paragraph(f"币种：本位币 {report['base_currency']}", h2))
        if report.get("currency_note"):
            story.append(Paragraph(report["currency_note"], h2))
        story.append(Spacer(1, 6*mm))
        data = [["", "Importe 金额"]]
        for r in report["rows"]:
            name = r["name"]
            if r.get("bold"):
                name = "<b>%s</b>" % name
            amt = format_amount(r["amount"])
            if r.get("bold"):
                amt = "<b>%s</b>" % amt
            data.append([Paragraph(name, cell), Paragraph(amt, cell)])
        data.append([Paragraph("<b>IVA neto 增值税净额（负=应交）</b>", cell),
                     Paragraph("<b>%s</b>" % format_amount(report["iva_neto"]), cell)])
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
