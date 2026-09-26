"""跨平台 Web 界面（Flask）。

用途：
  · 手机 / 电脑浏览器访问（局域网多终端录入）
  · Android APK 内嵌（Chaquopy + WebView，见 platforms/android）
Windows / macOS 桌面仍使用 Tk 客户端（main.py）。

启动：
    python -m app.web.server                       # http://127.0.0.1:8080
    python -m app.web.server --host 0.0.0.0 -p 8080
"""
import argparse
import datetime
from urllib.parse import quote

from flask import Flask, redirect, render_template, request, url_for

from app import config
from app import settings as settings_mod
from app.accounting import reports as reports_mod
from app.accounting import fx as fx_mod
from app.db import database
from app.sync import manager as sync_mgr
from app.utils import (date_iso, format_amount, format_base_amount,
                       parse_amount, parse_date)

app = Flask(__name__)
app.jinja_env.filters["money"] = lambda v, cur=None: format_amount(
    float(v or 0), currency=cur)
# 报表金额：只显示数字，不跟货币符号（各科目币种可能不同）
app.jinja_env.filters["num"] = lambda v: format_amount(float(v or 0),
                                                       symbols=False)
# 币种统一显示「中文名称（简称）」，模板里：{{ d.currency | cur }}
app.jinja_env.filters["cur"] = lambda v: config.currency_label(v) or (v or "")
# 无币种列的金额（商品价格）：带本位币符号，如 "1.234,50 Bs."
app.jinja_env.filters["basemoney"] = lambda v: format_base_amount(
    float(v or 0))

NAV = [
    ("dashboard", "概览"),
    ("income", "收入日报"),
    ("expense", "支出日报"),
    ("fx", "结汇兑换"),
    ("documents", "单据"),
    ("products", "库存"),
    ("reports", "报表"),
    ("settings", "设置"),
    ("sync", "同步"),
]


@app.context_processor
def _inject():
    return {"nav": NAV, "db_path": config.DB_PATH}


def _go(endpoint, msg=None, ok=True, **kw):
    """重定向到目标页面并携带提示信息。"""
    url = url_for(endpoint, **kw)
    if msg:
        sep = "&" if "?" in url else "?"
        url += f"{sep}msg={quote(str(msg))}&ok={1 if ok else 0}"
    return redirect(url)


def _today() -> str:
    return date_iso(datetime.date.today())


def _income_rows(limit: int = None) -> list:
    """把「日报记录 + 明细行」展开成一笔一行，供列表展示（最新在前）。"""
    out = database.list_daily_income_rows(limit=limit)
    for r in out:
        r["currency_label"] = config.income_currency_label(r.get("currency"))
    out.reverse()
    return out


# ------------------------------------------------------------------ 概览
@app.get("/")
def dashboard():
    docs = database.list_documents()
    incomes = _income_rows()
    expenses = database.list_daily_expense_items()
    try:
        low = database.low_stock_products()
    except Exception:  # noqa: BLE001
        low = []
    return render_template(
        "dashboard.html", active="dashboard",
        n_docs=len(docs),
        purchases=sum(float(d["total"] or 0) for d in docs if d["direction"] == "compra"),
        sales=sum(float(d["total"] or 0) for d in docs if d["direction"] == "venta"),
        income_total=sum(r["amount"] for r in incomes),
        expense_total=sum(float(r["amount"] or 0) for r in expenses),
        recent_docs=list(reversed(docs))[:8],
        recent_expenses=list(reversed(expenses))[:8],
        low=low)


# ------------------------------------------------------------------ 收入日报
@app.route("/income", methods=["GET", "POST"])
def income():
    if request.method == "POST":
        try:
            date = request.form.get("date") or _today()
            notes = request.form.get("notes", "")
            row = {
                "store": request.form.get("store", ""),
                "source": request.form.get("source", ""),
                "currency": request.form.get("currency", ""),
                "amount": parse_amount(request.form.get("amount")),
                "notes": notes,      # 备注按笔存，不影响同一天其他笔
            }
            row_id = request.form.get("row_id", type=int)
            if row_id:      # 再编辑：只更新这一笔，同一天其他笔保持不变
                before = database.get_daily_income_row(row_id) or {}
                income_id = database.get_or_create_daily_income(date)
                database.update_daily_income_row(row_id, row)
                if before.get("income_id") != income_id:
                    # 日期改了：把这笔移到那一天的记录里
                    database.move_daily_income_row(row_id, income_id)
                return _go("income", "已更新该笔收入")
            database.save_daily_income({"date": date, "rows": [row]})
            return _go("income", "已保存一笔收入")
        except Exception as e:  # noqa: BLE001
            return _go("income", str(e), False)
    edit_id = request.args.get("edit", type=int)
    edit = database.get_daily_income_row(edit_id) if edit_id else None
    return render_template(
        "income.html", active="income", rows=_income_rows(),
        today=_today(), stores=settings_mod.get_stores(),
        sources=config.INCOME_SOURCES,
        currencies=config.INCOME_CURRENCY_LABELS,
        source_currencies=config.INCOME_SOURCE_CURRENCIES,
        edit=edit)


@app.post("/income/delete/<int:row_id>")
def income_delete(row_id):
    database.delete_daily_income_row(row_id)
    return _go("income", "已删除该笔收入")


# ------------------------------------------------------------------ 支出日报
@app.route("/expense", methods=["GET", "POST"])
def expense():
    if request.method == "POST":
        try:
            # 费用类别：下拉选择，或手工输入新类别（自动登记到设置）
            category = request.form.get("category", "")
            new_category = (request.form.get("category_new") or "").strip()
            if new_category:
                category = settings_mod.add_expense_category(new_category)
            elif category:
                category = settings_mod.add_expense_category(category)
            rec = {
                "date": request.form.get("date") or _today(),
                "store": request.form.get("store", ""),
                "summary": request.form.get("summary", ""),
                "category": category,
                "method": request.form.get("method", ""),
                "currency": request.form.get("currency", ""),
                "amount": parse_amount(request.form.get("amount")),
                "notes": request.form.get("notes", ""),
            }
            rec_id = request.form.get("id", type=int)
            if rec_id:
                rec["id"] = rec_id
            database.save_daily_expense_item(rec)
            return _go("expense", "已更新该笔支出" if rec_id else "已保存一笔支出")
        except Exception as e:  # noqa: BLE001
            return _go("expense", str(e), False)
    rows = database.list_daily_expense_items()
    rows = list(reversed(rows))
    for r in rows:
        r["category_label"] = database.expense_category_label(r.get("category"))
    edit_id = request.args.get("edit", type=int)
    edit = database.get_daily_expense_item(edit_id) if edit_id else None
    return render_template(
        "expense.html", active="expense", rows=rows, today=_today(),
        stores=settings_mod.get_stores(),
        categories=settings_mod.get_expense_categories(),
        # 付款方式 = 科目表里货币资金的明细科目
        methods=reports_mod.payment_account_options(),
        currencies=[{"code": c, "label": config.currency_label(c)}
                    for c in config.PAY_CURRENCIES],
        edit=edit)


@app.post("/expense/delete/<int:rec_id>")
def expense_delete(rec_id):
    database.delete_daily_expense_item(rec_id)
    return _go("expense", "已删除该笔支出")


# ------------------------------------------------------------------ 结汇/兑换单
@app.route("/fx", methods=["GET", "POST"])
def fx():
    if request.method == "POST":
        try:
            rec = {
                "id": request.form.get("id", type=int) or None,
                "date": request.form.get("date") or _today(),
                "from_currency": config.normalize_currency(
                    request.form.get("from_currency", "")),
                "from_amount": parse_amount(request.form.get("from_amount")),
                "book_rate": parse_amount(request.form.get("book_rate")),
                "settle_rate": parse_amount(request.form.get("settle_rate")),
                "to_currency": config.normalize_currency(
                    request.form.get("to_currency", "")),
                "to_amount": parse_amount(request.form.get("to_amount")),
                "notes": request.form.get("notes", ""),
            }
            if rec["from_currency"] == rec["to_currency"]:
                return _go("fx", "换出与换入币种不能相同", False)
            database.save_fx_order(rec)
            return _go("fx", "已保存兑换单")
        except Exception as e:  # noqa: BLE001
            return _go("fx", str(e), False)
    rows = list(reversed(database.list_fx_orders()))
    for r in rows:
        r["from_label"] = config.currency_label(r.get("from_currency"))
        r["to_label"] = config.currency_label(r.get("to_currency"))
    cur_list = [{"code": c, "label": config.currency_label(c)}
                for c in config.PAY_CURRENCIES]
    edit_id = request.args.get("edit", type=int)
    edit = database.get_fx_order(edit_id) if edit_id else None
    voucher = None
    if edit:
        voucher = fx_mod.build_voucher(edit)
    return render_template(
        "fx.html", active="fx", rows=rows, today=_today(),
        currencies=cur_list, edit=edit, voucher=voucher)


@app.post("/fx/delete/<int:rec_id>")
def fx_delete(rec_id):
    database.delete_fx_order(rec_id)
    return _go("fx", "已删除该笔兑换单")


# ------------------------------------------------------------------ 单据
@app.route("/documents", methods=["GET", "POST"])
def documents():
    if request.method == "POST":
        try:
            total = parse_amount(request.form.get("total"))
            iva_rate = parse_amount(request.form.get("iva_rate"))
            base = round(total / (1 + iva_rate / 100), 2) if iva_rate else total
            database.save_document({
                "doc_type": request.form.get("doc_type", "FACTURA"),
                "direction": request.form.get("direction", "compra"),
                "doc_number": request.form.get("doc_number", ""),
                "date": request.form.get("date") or _today(),
                "partner": request.form.get("partner", ""),
                "tax_id": request.form.get("tax_id", ""),
                "store": request.form.get("store", ""),
                "base": base,
                "iva_rate": iva_rate,
                "iva_amount": round(total - base, 2),
                "total": total,
                "currency": request.form.get("currency", ""),
                "exchange_rate": parse_amount(request.form.get("exchange_rate")),
                "items": [],
            })
            return _go("documents", "单据已保存")
        except Exception as e:  # noqa: BLE001
            return _go("documents", str(e), False)
    docs = list(reversed(database.list_documents()))
    return render_template("documents.html", active="documents",
                           docs=docs, today=_today(),
                           stores=settings_mod.get_stores(),
                           currencies=config.CURRENCY_CODES)


@app.post("/documents/delete/<int:doc_id>")
def documents_delete(doc_id):
    database.delete_document(doc_id)
    return _go("documents", "单据已删除")


# ------------------------------------------------------------------ 库存
@app.route("/products", methods=["GET", "POST"])
def products():
    if request.method == "POST":
        try:
            database.save_product({
                "code": request.form.get("code", "").strip(),
                "name": request.form.get("name", "").strip(),
                "category": request.form.get("category", ""),
                "unit": request.form.get("unit", ""),
                "cost_price": parse_amount(request.form.get("cost_price")),
                "sale_price": parse_amount(request.form.get("sale_price")),
                "stock_qty": parse_amount(request.form.get("stock_qty")),
                "min_stock": parse_amount(request.form.get("min_stock")),
                "supplier": request.form.get("supplier", ""),
            })
            return _go("products", "商品已保存")
        except Exception as e:  # noqa: BLE001
            return _go("products", str(e), False)
    return render_template("products.html", active="products",
                           products=database.list_products())


@app.post("/products/delete/<int:pid>")
def products_delete(pid):
    database.delete_product(pid)
    return _go("products", "商品已删除")


# ------------------------------------------------------------------ 报表
_AMOUNT_KEYS = ("amount", "balance", "total", "value", "base", "iva_amount",
                "saldo", "importe", "debit", "credit")
_LABEL_KEYS = ("name", "label", "title", "account", "concept", "desc",
               "description", "code")

# 报表字段名 → 中文显示名
_LABELS = {
    "activo": "资产 Activo",
    "pasivo": "负债 Pasivo",
    "patrimonio": "所有者权益 Patrimonio",
    "total_activo": "资产合计",
    "total_pasivo": "负债合计",
    "total_pat": "所有者权益合计",
    "total_pasivo_pat": "负债与所有者权益合计",
    "resultado": "本期损益",
    "ingresos": "收入 Ingresos",
    "gastos": "费用 Gastos",
    "coste_ventas": "销售成本",
    "total_ingresos": "收入合计",
    "total_gastos": "费用合计",
    "neto": "净利润",
    "year": "会计年度",
    "base_currency": "本位币",
}


def _report_rows(node, depth=0, out=None) -> list:
    """把报表结果（嵌套 dict/list）摊平成可渲染的行。"""
    if out is None:
        out = []
    if isinstance(node, dict):
        label = next((str(node[k]) for k in _LABEL_KEYS if node.get(k)), None)
        amount = next((node[k] for k in _AMOUNT_KEYS
                       if isinstance(node.get(k), (int, float))), None)
        if label and amount is not None:
            out.append({"kind": "row", "depth": depth, "label": label,
                        "value": float(amount)})
            return out
        for k, v in node.items():
            text = _LABELS.get(str(k), str(k))
            if isinstance(v, (dict, list)):
                out.append({"kind": "section", "depth": depth, "label": text})
                _report_rows(v, depth + 1, out)
            elif isinstance(v, (int, float)):
                out.append({"kind": "row", "depth": depth, "label": text,
                            "value": float(v)})
    elif isinstance(node, list):
        for item in node:
            _report_rows(item, depth, out)
    return out


@app.get("/reports")
def reports():
    rtype = request.args.get("type", "balance")
    frm = request.args.get("from", "")
    to = request.args.get("to", "")
    dfrom = parse_date(frm) if frm else None
    dto = parse_date(to) if to else None
    capital = float(settings_mod.load_settings().get("capital_inicial", 0) or 0)
    rows, error, trial, src = [], None, None, None
    try:
        # get_report 返回 (报表 dict, 未换算单据 list)
        res = reports_mod.get_report(rtype, dfrom, dto, capital)
        data = res[0] if isinstance(res, tuple) else res
        src = (data or {}).get("sources")
        if rtype == "trial":     # 科目余额表：单独的多列表格
            trial = data or {}
        else:
            rows = _report_rows(data or {})
    except Exception as e:  # noqa: BLE001
        error = str(e)
    return render_template("reports.html", active="reports", rtype=rtype,
                           rows=rows, error=error, frm=frm, to=to, trial=trial,
                           sources=src)


# ------------------------------------------------------------------ 设置
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            s = settings_mod.load_settings()
            s["capital_inicial"] = parse_amount(request.form.get("capital_inicial"))
            # 下拉里是「中文名称（简称）」，存库仍用代码
            s["base_currency"] = config.currency_code(
                request.form.get("base_currency"))
            s["usd_to_base"] = parse_amount(request.form.get("usd_to_base"))
            s["usd_ves_official"] = parse_amount(request.form.get("usd_ves_official"))
            s["usd_cny"] = parse_amount(request.form.get("usd_cny"))
            stores = [x.strip() for x in
                      (request.form.get("stores") or "").replace("，", ",").split(",")
                      if x.strip()]
            s["stores"] = stores or list(config.DEFAULT_STORES)
            settings_mod.save_settings(s)
            return _go("settings", "设置已保存")
        except Exception as e:  # noqa: BLE001
            return _go("settings", str(e), False)
    return render_template("settings.html", active="settings",
                           s=settings_mod.load_settings(),
                           currencies=config.CURRENCY_CODES)


@app.post("/settings/fetch-rates")
def settings_fetch_rates():
    """在线获取委内瑞拉官方汇率（BCV）+ 美元兑人民币。"""
    from app.rates import fetch_usd_ves, fetch_usd_cny, fetch_usd_eur
    try:
        ves = fetch_usd_ves()
        s = settings_mod.load_settings()
        s["usd_ves_official"] = float(ves["usd_ves"])
        s["usd_ves_date"] = (ves.get("date") or "")[:10]
        try:
            cny = fetch_usd_cny()
            s["usd_cny"] = float(cny["usd_cny"])
        except Exception:  # noqa: BLE001
            pass
        try:
            eur = fetch_usd_eur()
            if (s.get("base_currency") or "") == "EUR":
                s["usd_to_base"] = float(eur["usd_eur"])
        except Exception:  # noqa: BLE001
            pass
        settings_mod.save_settings(s)
        return _go("settings", f"已获取：1 USD = {ves['usd_ves']} Bs")
    except Exception as e:  # noqa: BLE001
        return _go("settings", str(e), False)


# ------------------------------------------------------------------ 同步
def _sync_cfg_from_form() -> dict:
    return {
        "enabled": request.form.get("enabled") == "1",
        "url": (request.form.get("url") or "").strip(),
        "user": (request.form.get("user") or "").strip(),
        "password": request.form.get("password") or "",
        "remote_dir": (request.form.get("remote_dir") or "").strip() or "GestionFacturas",
        "verify_ssl": request.form.get("verify_ssl") == "1",
        "auto_sync": request.form.get("auto_sync") == "1",
        "interval_min": int(request.form.get("interval_min") or 30),
    }


@app.route("/sync", methods=["GET", "POST"])
def sync():
    if request.method == "POST":
        action = request.form.get("action", "")
        cfg = _sync_cfg_from_form()
        sync_mgr.save_config(cfg)
        try:
            if action == "save":
                return _go("sync", "配置已保存")
            if action == "test":
                ok, msg = sync_mgr.test_connection(cfg)
                return _go("sync", msg, ok)
            if action == "upload":
                res = sync_mgr.upload(force=request.form.get("force") == "1")
                return _go("sync", res.get("message"), bool(res.get("ok")))
            if action == "download":
                res = sync_mgr.download(force=request.form.get("force") == "1")
                return _go("sync", res.get("message"), bool(res.get("ok")))
            if action == "auto":
                res = sync_mgr.auto_sync()
                return _go("sync", res.get("message"), bool(res.get("ok")))
        except Exception as e:  # noqa: BLE001
            return _go("sync", str(e), False)
    try:
        plan = sync_mgr.plan()
    except Exception as e:  # noqa: BLE001
        plan = {"action": "error", "message": str(e)}
    return render_template("sync.html", active="sync",
                           cfg=sync_mgr.get_config(),
                           state=sync_mgr.get_state(),
                           info=sync_mgr.remote_info(),
                           plan=plan, logs=sync_mgr.read_log()[:50])


# ------------------------------------------------------------------ 其它
@app.get("/healthz")
def healthz():
    return {"ok": True, "data_dir": config.DATA_DIR, "db": config.DB_PATH}


def main(argv=None):
    ap = argparse.ArgumentParser(description="GestionFacturas Web 界面")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("-p", "--port", type=int, default=8080)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)
    database.init_db()
    print(f"Web 界面已启动： http://{args.host}:{args.port}")
    print(f"数据目录：{config.DATA_DIR}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
