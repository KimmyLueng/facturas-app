"""自检脚本：验证解析器、数据库、报表引擎（不依赖 OCR 模型）。

用法:  python selftest.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ocr.parser import (  # noqa: E402
    parse_document, detect_currency, detect_exchange_rate)
from app.utils import (  # noqa: E402
    parse_amount, parse_date, parse_document_number, format_amount)
from app import config  # noqa: E402
from app.db import database  # noqa: E402
from app.rates import convert_to_base  # noqa: E402
from app.accounting import build_balance_sheet, build_income_statement  # noqa: E402
from app.sync import manager as sync_manager  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def main():
    print("== 1. 金额/日期/单据号解析 ==")
    check("parse_amount 1.234,56 €", parse_amount("1.234,56 €") == 1234.56)
    check("parse_amount $ 1.234,56", parse_amount("$ 1.234,56") == 1234.56)
    check("parse_amount 37,80", parse_amount("37,80") == 37.8)
    check("parse_amount 1234.56", parse_amount("1234.56") == 1234.56)
    check("format_amount 默认美元符号", format_amount(1234.56) == "1.234,56 $")
    d = parse_date("25/08/2026")
    check("parse_date 25/08/2026", d is not None and d.day == 25 and d.month == 8 and d.year == 2026)
    check("parse_document_number N 2026-045",
          parse_document_number("Factura N 2026-045") == "2026-045")
    check("parse_document_number 排除日期",
          parse_document_number("Fecha: 25/08/2026") == "")

    print("== 2. 单据解析（进货） ==")
    compra = parse_document([
        "FACTURA", "Proveedor: Distribuciones Sol S.L. NIF B12345678",
        "Fecha: 25/08/2026", "Factura N 2026-045", "CONCEPTO",
        "Harina 5kg 10 x 2.50 25,00", "Aceite 1L 4 x 3,20 12,80",
        "Base imponible 37,80", "IVA 21% 7,94", "TOTAL 45,74",
    ])
    check("方向=compra", compra["direction"] == "compra")
    check("供应商名称", compra["partner"] == "Distribuciones Sol S.L.",
          f"got={compra['partner']!r}")
    check("单据号", compra["doc_number"] == "2026-045",
          f"got={compra['doc_number']!r}")
    check("Base", compra["base"] == 37.8)
    check("IVA", compra["iva_amount"] == 7.94, f"got={compra['iva_amount']}")
    check("Total", compra["total"] == 45.74)
    check("行项目数", len(compra["items"]) == 2)

    print("== 3. 单据解析（出货） ==")
    venta = parse_document([
        "FACTURA DE VENTA", "Cliente: Panaderia La Espiga S.L.",
        "Fecha 02/09/2026", "Factura F-2026-120", "ARTICULO",
        "Pan integral 50 x 1,20 60,00", "Bolleria 30 x 2,00 60,00",
        "BASE IMPONIBLE 120,00", "CUOTA IVA 25,20", "TOTAL 145,20",
    ])
    check("方向=venta", venta["direction"] == "venta")
    check("客户名称", venta["partner"] == "Panaderia La Espiga S.L.",
          f"got={venta['partner']!r}")
    check("单据号 F-2026-120", venta["doc_number"] == "F-2026-120",
          f"got={venta['doc_number']!r}")
    check("Base=120", venta["base"] == 120.0)
    check("IVA=25.2", venta["iva_amount"] == 25.2)
    check("Total=145.2", venta["total"] == 145.2)

    print("== 4. 币种与汇率识别 ==")
    check("EUR (€)", detect_currency(["TOTAL 45,74 €"]) == "EUR")
    check("USD ($)", detect_currency(["TOTAL $ 45,74"]) == "USD")
    check("USD (USD)", detect_currency(["Total en USD 100,00"]) == "USD")
    # VES 与 Bs 是同一种货币，统一识别/存储为 Bs
    check("Bs (Bs.)", detect_currency(["TOTAL Bs. 1.234,56"]) == "Bs")
    check("Bs (Bs.S)", detect_currency(["TOTAL Bs.S 1.234,56"]) == "Bs")
    check("Bs (BOLIVARES)", detect_currency(["Total en Bolivares 1.234,56"]) == "Bs")
    check("Bs (VES 代码)", detect_currency(["TOTAL 1.234,56 VES"]) == "Bs")
    check("汇率 Tasa: 36,50",
          detect_exchange_rate(["Tasa de cambio: 36,50"]) == 36.5)
    check("汇率 1 USD = 785,07 Bs",
          detect_exchange_rate(["1 USD = 785,07 Bs"]) == 785.07)
    check("汇率 Bs 785,07 / USD",
          detect_exchange_rate(["Bs. 785,07 / USD"]) == 785.07)
    check("汇率行不影响币种",
          detect_currency(["Tasa: 36,50", "TOTAL $ 100,00"]) == "USD")

    print("== 5. 汇率换算 ==")
    st_eur = {"base_currency": "EUR", "usd_to_base": 0.92, "usd_ves_official": 785.07}
    v, ok = convert_to_base(100, "EUR", st_eur)
    check("EUR 不换算", v == 100 and ok)
    v, ok = convert_to_base(100, "USD", st_eur)
    check("USD→EUR", abs(v - 92.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(78507, "Bs", st_eur)
    check("Bs→EUR(官方汇率)", abs(v - 92.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(78507, "VES", st_eur)
    check("旧写法 VES 仍按 Bs 换算", abs(v - 92.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(100, "USD", {"base_currency": "EUR", "usd_to_base": 0})
    check("缺汇率标记未换算", not ok)
    v, ok = convert_to_base(36.5, "Bs",
                            {"base_currency": "EUR", "usd_to_base": 0.92,
                             "usd_ves_official": 0}, doc_rate=36.5)
    check("单据自带汇率优先", abs(v - 0.92) < 0.01 and ok, f"got={v}")

    print("== 5b. 人民币（CNY）识别与换算 ==")
    st_cny = {"base_currency": "USD", "usd_to_base": 1.0, "usd_cny": 7.2}
    v, ok = convert_to_base(720, "CNY", st_cny)
    check("CNY→USD（720 ÷ 7.2 = 100）", abs(v - 100.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(720, "CNY", st_cny, doc_rate=7.2)
    check("CNY 单据自带汇率优先", abs(v - 100.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(100, "CNY", {"base_currency": "USD", "usd_to_base": 1.0})
    check("CNY 缺汇率标记未换算", not ok)
    st_base_cny = {"base_currency": "CNY", "usd_to_base": 7.2}
    v, ok = convert_to_base(100, "USD", st_base_cny)
    check("USD→CNY（本位币人民币，100 × 7.2 = 720）",
          abs(v - 720.0) < 0.01 and ok, f"got={v}")
    v, ok = convert_to_base(500, "CNY", st_base_cny)
    check("本位币=CNY 原值返回", v == 500 and ok)

    check("识别 ¥ 为 CNY", detect_currency(["TOTAL ¥ 1.234,56"]) == "CNY",
          f"got={detect_currency(['TOTAL ¥ 1.234,56'])}")
    check("识别 ￥ 为 CNY", detect_currency(["合计 ￥888.00"]) == "CNY")
    check("识别“人民币”为 CNY", detect_currency(["金额单位：人民币"]) == "CNY")
    check("识别 CNY 代码", detect_currency(["Total: 100.00 CNY"]) == "CNY")
    check("人民币汇率行 1 USD = 7,20 CNY",
          abs(detect_exchange_rate(["1 USD = 7,20 CNY"]) - 7.2) < 0.01,
          f"got={detect_exchange_rate(['1 USD = 7,20 CNY'])}")

    check("人民币金额显示 ¥ 符号",
          format_amount(1234.5, currency="CNY").endswith("¥"),
          format_amount(1234.5, currency="CNY"))

    print("== 6. 数据库 + 报表引擎 ==")
    # 使用临时数据库
    tmp_db = os.path.join(tempfile.mkdtemp(prefix="facturas_selftest_"), "t.db")
    old_db = config.DB_PATH
    config.DB_PATH = tmp_db
    try:
        database.init_db()
        # 全新安装（只有表结构）应判定为“无数据”，同步时建议从云端恢复
        check("空账套 has_local_data=False",
              sync_manager.has_local_data() is False)
        c1 = dict(compra)
        c1["direction"] = "compra"
        c1["store"] = "A店"
        c1["items"] = [{"desc": "Harina", "qty": 10, "unit_price": 2.5,
                        "amount": 25.0, "discount": 8.0, "neto": 23.0},
                       {"desc": "Aceite", "qty": 4, "unit_price": 3.2, "amount": 12.8}]
        v1 = dict(venta)
        v1["direction"] = "venta"
        v1["store"] = "B店"
        v1["items"] = [{"desc": "Pan", "qty": 50, "unit_price": 1.2, "amount": 60.0},
                       {"desc": "Bolleria", "qty": 30, "unit_price": 2.0, "amount": 60.0}]
        database.save_document(c1)
        database.save_document(v1)

        docs = database.list_documents()
        check("已保存 2 张单据", len(docs) == 2)
        check("有业务数据后 has_local_data=True", sync_manager.has_local_data())

        # 分店字段保存/读回 + 按分店筛选
        check("分店保存并读回",
              any(d.get("store") == "A店" for d in docs) and
              any(d.get("store") == "B店" for d in docs),
              f"stores={[d.get('store') for d in docs]}")
        a_docs = database.list_documents(store="A店")
        b_docs = database.list_documents(store="B店")
        check("按分店筛选",
              len(a_docs) == 1 and a_docs[0]["store"] == "A店"
              and len(b_docs) == 1 and b_docs[0]["store"] == "B店")
        check("分店去重列表",
              set(database.list_stores()) == {"A店", "B店"},
              f"got={database.list_stores()}")

        # 行项目折扣字段保存/读回
        full = database.get_document(docs[0]["id"])
        harina = full["items"][0]
        check("行项目折扣保存并读回",
              abs(harina["discount"] - 8.0) < 0.01 and abs(harina["neto"] - 23.0) < 0.01,
              f"got discount={harina.get('discount')} neto={harina.get('neto')}")

        docs = database.list_documents()
        for d in docs:
            full = database.get_document(d["id"])
            d["items"] = full["items"]

        bal = build_balance_sheet(docs, capital=1000.0)
        print(f"    资产合计: {bal['total_activo']}  负债+净资产: {bal['total_pasivo_pat']}")
        check("资产负债表平衡", bal["balanced"], f"diff={bal['diff']}")
        check("现金 = 资本 + 收入 - 进货",
              abs(bal["activo"][0]["amount"] - (1000 + 145.2 - 45.74)) < 0.01)

        inc = build_income_statement(docs)
        print(f"    收入: {inc['ventas']}  成本: {inc['coste']}  净利: {inc['resultado']}")
        check("利润表收入=120", inc["ventas"] == 120.0)
        # 平均成本: 进货 37.8 / 14 件 = 2.70；出货 80 件 → 成本 216.0
        check("销售成本(加权平均)=216",
              abs(inc["coste"] - (37.8 / 14) * 80) < 0.01,
              f"got={inc['coste']}")
        check("净利润=收入-成本", abs(inc["resultado"] - (120.0 - inc["coste"])) < 0.01)

        print("== 6b. 店铺收支/支出日报与供应商结算 ==")
        database.save_daily_income({
            "date": "2026-08-25",
            "rows": [
                {"store": "A", "source": config.INCOME_SOURCE_CASH,
                 "currency": config.INCOME_CUR_USD, "amount": 30},
                {"store": "A", "source": config.INCOME_SOURCE_CASH,
                 "currency": config.INCOME_CUR_BS, "amount": 200},
                {"store": "A", "source": config.INCOME_SOURCE_EPAY,
                 "currency": config.INCOME_CUR_USDT, "amount": 100},
                {"store": "A", "source": config.INCOME_SOURCE_CARD,
                 "currency": config.INCOME_CUR_USD, "amount": 50},
            ],
        })
        incomes = database.list_daily_income_full()
        check("收支日报保存并读取",
              len(incomes) == 1 and len(incomes[0]["rows"]) == 4
              and incomes[0]["rows"][0]["amount"] == 30,
              f"got={len(incomes[0]['rows']) if incomes else 0} 行")

        # 备注按笔独立：只改其中一笔，同一天其他笔不受影响（回归）
        flat = database.list_daily_income_rows()
        database.update_daily_income_row(flat[0]["row_id"], {
            "store": flat[0]["store"], "source": flat[0]["source"],
            "currency": flat[0]["currency"], "amount": flat[0]["amount"],
            "notes": "第一笔备注"})
        flat = database.list_daily_income_rows()
        check("再编辑备注只改这一笔",
              flat[0]["notes"] == "第一笔备注"
              and all(r["notes"] == "" for r in flat[1:]),
              f"got={[r['notes'] for r in flat]}")
        agg = database.daily_income_by_account()
        check("日报按支付方式+币种归集科目",
              abs(agg["cash"].get("USD", 0) - 30) < 0.01
              and abs(agg["cash"].get("Bs", 0) - 200) < 0.01
              and abs(agg["bank"].get("USD", 0) - 50) < 0.01
              and abs(agg["crypto"].get("USDT", 0) - 100) < 0.01,
              f"got={agg}")

        # 收入「支付方式+币种」→ 财务报表科目
        check("现钞 Bs → 库存现金(cash)",
              config.income_account_key("现钞", "Bs") == "cash",
              f"got={config.income_account_key('现钞', 'Bs')}")
        check("现钞 USD → 库存现金(cash)",
              config.income_account_key("现钞", "USD") == "cash")
        check("现钞 CNY → 库存现金(cash)",
              config.income_account_key("现钞", "CNY") == "cash")
        check("银行卡 USD → 银行存款(bank)",
              config.income_account_key("银行卡", "USD") == "bank")
        check("电子支付 CNY → 其他货币资金(crypto)",
              config.income_account_key("电子支付", "CNY") == "crypto")
        # 稳定币无现钞形态：现钞来源改记银行存款，电子支付记其他货币资金
        check("USDT 只能记银行/其他货币资金(不可现金)",
              config.income_account_options("USDT") == ["bank", "crypto"])
        check("现钞 USDT → 银行存款(bank)",
              config.income_account_key("现钞", "USDT") == "bank")
        check("电子支付 USDT → 其他货币资金(crypto)",
              config.income_account_key("电子支付", "USDT") == "crypto")
        check("旧写法 VES 现钞 → 库存现金(cash)",
              config.income_account_key("现钞", "VES") == "cash")
        check("法定货币三种科目均可记",
              config.income_account_options("Bs") == ["cash", "bank", "crypto"])

        database.save_daily_expense({
            "date": "2026-08-25", "summary": "日常支出",
            "salary": 100, "overtime": 20, "meal": 30, "tax": 10,
            "utilities": 25, "rent": 200, "municipal": 15,
            "pay_method": config.PAY_METHOD_CARD,
            "pay_currency": config.PAY_CURRENCY_BS,
        })
        expenses = database.list_daily_expense()
        check("支出日报自动归集到刷卡",
              len(expenses) == 1 and expenses[0]["total_card"] == 400
              and expenses[0]["total_ves"] == 0 and expenses[0]["total_usd"] == 0)

        database.save_daily_expense({
            "date": "2026-08-25", "summary": "现金美元支出",
            "salary": 0, "overtime": 0, "meal": 0, "tax": 0,
            "utilities": 0, "rent": 0, "municipal": 0,
            "pay_method": config.PAY_METHOD_CASH,
            "pay_currency": config.PAY_CURRENCY_USD,
        })
        expenses = database.list_daily_expense(
            date_from="2026-08-25", date_to="2026-08-25")
        check("支出日报按日期筛选", len(expenses) == 2)

        database.save_supplier_settlement({
            "date": "2026-08-25", "partner_name": "Proveedor A",
            "summary": "Pago", "doc_number": "P-001",
            "supply_amount_ves": 1000,
            "pay_method": config.PAY_METHOD_CASH,
            "pay_currency": config.PAY_CURRENCY_BS,
            "pay_amount": 500,
            "store": "B店",
        })
        settlements = database.list_supplier_settlements()
        check("供应商结算现金委币",
              len(settlements) == 1 and settlements[0]["pay_cash_ves"] == 500
              and settlements[0]["pay_bank"] == 0
              and settlements[0]["pay_cash_usd"] == 0)
        check("结算入库分店保存读回",
              len(settlements) == 1 and settlements[0].get("store") == "B店",
              f"store={settlements[0].get('store') if settlements else None}")

        # 人民币收付归集
        database.save_daily_expense({
            "date": "2026-08-26", "summary": "人民币现金支出",
            "salary": 100, "overtime": 0, "meal": 0, "tax": 0,
            "utilities": 0, "rent": 0, "municipal": 0,
            "pay_method": config.PAY_METHOD_CASH,
            "pay_currency": config.PAY_CURRENCY_CNY,
        })
        exps = database.list_daily_expense(
            date_from="2026-08-26", date_to="2026-08-26")
        check("人民币现金支出归集到 total_cny",
              len(exps) == 1 and exps[0]["total_cny"] == 100
              and exps[0]["total_ves"] == 0 and exps[0]["total_usd"] == 0,
              f"got={exps[0] if exps else None}")

        database.save_supplier_settlement({
            "date": "2026-08-26", "partner_name": "Proveedor B",
            "summary": "Pago", "doc_number": "P-002",
            "supply_amount_ves": 0,
            "pay_method": config.PAY_METHOD_CASH,
            "pay_currency": config.PAY_CURRENCY_CNY,
            "pay_amount": 800,
        })
        sts = database.list_supplier_settlements(
            date_from="2026-08-26", date_to="2026-08-26")
        check("人民币结算归集到 pay_cash_cny",
              len(sts) == 1 and sts[0]["pay_cash_cny"] == 800,
              f"got={sts[0] if sts else None}")

        # PDF 导出（需要 reportlab）
        try:
            from app.accounting import export_pdf
            out = export_pdf("balance", out_path=os.path.join(
                os.path.dirname(tmp_db), "b.pdf"))
            check("PDF 导出", os.path.exists(out) and os.path.getsize(out) > 500)
        except ImportError:
            print("  [SKIP] PDF 导出：未安装 reportlab")

        print("== 6c. 财务期初余额（科目体系 + 期初数） ==")
        # 构造《财务初始余额.xlsx》模板格式的临时 Excel（含明细科目列与多级编码）
        try:
            from openpyxl import Workbook
            xlsx = os.path.join(os.path.dirname(tmp_db), "财务初始余额.xlsx")
            wb = Workbook()
            ws = wb.active
            ws["A1"] = "财务初始余额"
            ws["A2"] = "测试企业"
            ws["G2"] = "启用期间：2026年07期"
            headers = ["*科目编码", "*科目名称", "明细科目(是/否)", "借贷", "年初余额",
                       "本年累计借方发生额", "本年累计贷方发生额", "期初余额",
                       "本年累计损益发生额"]
            for i, h in enumerate(headers, 1):
                ws.cell(row=3, column=i, value=h)
            data = [
                ["1001", "库存现金", "是", "借", 0, 0, 0, 5000, 0],
                ["1002", "银行存款", "否", "借", 0, 0, 0, 0, 0],
                ["100201", "基本户", "是", "借", 0, 0, 0, 15000, 0],
                ["1405", "库存商品", "是", "借", 0, 0, 0, 8000, 0],
                ["4001", "实收资本", "是", "贷", 0, 0, 0, 28000, 0],
            ]
            for r, row in enumerate(data, 4):
                for c, v in enumerate(row, 1):
                    ws.cell(row=r, column=c, value=v)
            wb.save(xlsx)

            # 清空科目表与期初余额，保证用例自包含（不受默认科目表 JSON 影响）
            conn = database.get_conn()
            conn.execute("DELETE FROM opening_balances")
            conn.execute("DELETE FROM chart_of_accounts")
            conn.commit()
            conn.close()

            res = database.import_opening_balances_from_xlsx(xlsx)
            check("导入 5 个科目", res["accounts"] == 5, f"got={res['accounts']}")
            check("导入年度=2026", res["year"] == "2026", f"got={res['year']}")
            check("明细科目 4 个", res["leaf"] == 4, f"got={res['leaf']}")

            rows = database.list_opening_balances(year="2026")
            check("期初余额列出 5 条",
                  len(rows) == 5 and rows[0]["name"] == "库存现金")
            by_code = {r["code"]: r for r in rows}
            check("层级推断：100201 上级=1002",
                  by_code["100201"]["parent"] == "1002",
                  f"got={by_code['100201'].get('parent')}")
            check("汇总科目标记：1002 is_leaf=0",
                  by_code["1002"]["is_leaf"] == 0,
                  f"got={by_code['1002'].get('is_leaf')}")

            total = database.get_opening_balance_total(year="2026", only_leaf=True)
            check("明细口径借贷平衡（5000+15000+8000=28000）",
                  abs(total["diff"]) < 0.005,
                  f"借={total['debit']} 贷={total['credit']}")

            # 修改期初数后重算平衡
            records = [{"account_code": "1001", "period_balance": 6000},
                       {"account_code": "4001", "period_balance": 29000}]
            database.save_opening_balances(records, year="2026")
            total2 = database.get_opening_balance_total(year="2026", only_leaf=True)
            check("修改期初数后仍平衡（6000+15000+8000=29000）",
                  abs(total2["diff"]) < 0.005,
                  f"借={total2['debit']} 贷={total2['credit']}")

            # 级联删除：删除 1002 应连带 100201 及其期初余额
            n = database.delete_chart_of_account("1002", cascade=True)
            check("级联删除 2 个科目", n == 2, f"got={n}")
            rows2 = database.list_opening_balances(year="2026")
            check("删除后剩余 3 条", len(rows2) == 3, f"got={len(rows2)}")

            print("== 6d. 财务报表与科目表打通 ==")
            # 建立与模板编码一致的科目体系
            for a in ({"code": "1001", "name": "库存现金", "direction": "借", "is_leaf": 1},
                      {"code": "1405", "name": "库存商品", "direction": "借", "is_leaf": 1},
                      {"code": "22210101", "name": "进项税额", "direction": "借", "is_leaf": 1},
                      {"code": "22210106", "name": "销项税额", "direction": "贷", "is_leaf": 1},
                      {"code": "3001", "name": "实收资本", "direction": "贷", "is_leaf": 1},
                      {"code": "5001", "name": "主营业务收入", "direction": "贷", "is_leaf": 1},
                      {"code": "5401", "name": "主营业务成本", "direction": "借", "is_leaf": 1}):
                database.save_chart_of_account(a)
            database.delete_chart_of_account("4001")
            # 期初：借 1001 20000 + 1405 8000 = 贷 3001 28000
            database.save_opening_balances(
                [{"account_code": "1001", "period_balance": 20000},
                 {"account_code": "1405", "period_balance": 8000},
                 {"account_code": "3001", "period_balance": 28000}], year="2026")

            docs2 = database.list_documents()
            for d in docs2:
                full = database.get_document(d["id"])
                d["items"] = full["items"] if full else []

            rep = build_balance_sheet(docs2, capital=1000.0, year="2026")
            codes = [x["code"] for x in rep["activo"]]
            check("资产行取自科目表", "1001" in codes and "1405" in codes, f"got={codes}")
            check("资产负债表平衡（科目表期初）", rep["balanced"], f"diff={rep['diff']}")
            cash = next((x["amount"] for x in rep["activo"] if x["code"] == "1001"), None)
            check("现金=期初20000+收145.2-付45.74",
                  cash is not None and abs(cash - (20000 + 145.2 - 45.74)) < 0.01,
                  f"got={cash}")
            check("期初来源=科目表",
                  str(rep.get("opening_source", "")).startswith("科目表"),
                  f"got={rep.get('opening_source')}")

            inc2 = build_income_statement(docs2, year="2026")
            check("利润表收入=120（科目口径）",
                  abs(inc2["ventas"] - 120.0) < 0.01, f"got={inc2['ventas']}")
            check("利润表成本=216（科目口径）",
                  abs(inc2["coste"] - 216.0) < 0.01, f"got={inc2['coste']}")
            check("净利润=-96（科目口径）",
                  abs(inc2["resultado"] - (-96.0)) < 0.01, f"got={inc2['resultado']}")

            print("== 6e. 商品库存 / 进销存联动 ==")
            pid = database.save_product({
                "code": "H171", "name": "Leche", "category": "饮料",
                "unit": "UND", "cost_price": 1, "sale_price": 1.5,
                "stock_qty": 0, "min_stock": 5})
            check("新建商品", pid is not None)
            database.save_document({
                "direction": "compra", "partner": "Prov1", "date": "2026-09-12",
                "total": 10.0,
                "items": [{"code": "H171", "desc": "Leche", "qty": 10,
                           "unit_price": 1}]})
            check("进货入库 +10", database.get_product(pid)["stock_qty"] == 10)
            database.save_document({
                "direction": "venta", "partner": "Cli1", "date": "2026-09-12",
                "total": 3,
                "items": [{"code": "H171", "desc": "Leche", "qty": 3,
                           "unit_price": 1.5}]})
            check("销售出库 -3", database.get_product(pid)["stock_qty"] == 7)
            check("库存高于下限不预警",
                  len(database.low_stock_products()) == 0)
            database.apply_stock_change(pid, -10, "ajuste",
                                        note="报损", date="2026-09-12")
            check("手工调整到 -3 触发预警",
                  len(database.low_stock_products()) == 1)
            rb = database.rebuild_stock_from_documents()
            check("从单据重建库存=7",
                  database.get_product(pid)["stock_qty"] == 7,
                  f"got={database.get_product(pid)['stock_qty']}")
            check("重建流水命中 1 商品", rb["products"] == 1 and rb["moves"] == 2,
                  f"got={rb}")
            nmoves = len(database.list_stock_moves(50))
            database.delete_product(pid)
            check("删除商品级联清空其流水",
                  len(database.list_stock_moves(50)) == 0 and nmoves == 2,
                  f"before={nmoves} after={len(database.list_stock_moves(50))}")
        except ImportError:
            print("  [SKIP] 期初余额 Excel：未安装 openpyxl")
    finally:
        config.DB_PATH = old_db

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
