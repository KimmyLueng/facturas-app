"""经营概览（仪表盘）：日/月销售额、商品与库存预警、近期库存变动。"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app.db import database
from app.utils import format_amount, date_iso, parse_amount

_MOVE_LABELS = {
    "compra": "进货入库", "venta": "销售出库",
    "ajuste": "手工调整", "inventario": "盘点",
}


class DashboardPage:
    def __init__(self, app):
        self.app = app
        self.frame = None

    def build(self):
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(2, weight=1)

        # ----------------------------------------------------- 概览卡片
        cards = ttk.Frame(f)
        cards.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=10)
        for i in range(4):
            cards.columnconfigure(i, weight=1)
        self._cards = {}
        for i, key in enumerate(("today", "month", "products", "low")):
            cf = ttk.LabelFrame(cards, text="", padding=10)
            cf.grid(row=0, column=i, sticky="ew", padx=4)
            val = ttk.Label(cf, text="", font=("Microsoft YaHei UI", 18, "bold"),
                            foreground="#1f6feb")
            val.pack()
            self._cards[key] = (cf, val)

        # ----------------------------------------------------- 低库存
        low_frame = ttk.LabelFrame(f, text="库存预警（低于下限）", padding=8)
        low_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        low_frame.rowconfigure(0, weight=1)
        low_frame.columnconfigure(0, weight=1)
        self.low_tree = ttk.Treeview(
            low_frame, columns=("name", "stock", "min", "unit"),
            show="headings", height=8)
        for k, t, w in (("name", "商品", 160), ("stock", "库存", 70),
                        ("min", "下限", 70), ("unit", "单位", 50)):
            self.low_tree.heading(k, text=t)
            self.low_tree.column(k, width=w, anchor="e" if k in ("stock", "min") else "w")
        self.low_tree.grid(row=0, column=0, sticky="nsew")
        self.low_tree.tag_configure("low", foreground="#c0392b")

        # ----------------------------------------------------- 近期库存变动
        mv_frame = ttk.LabelFrame(f, text="近期库存变动", padding=8)
        mv_frame.grid(row=1, column=1, sticky="nsew", padx=12, pady=4)
        mv_frame.rowconfigure(0, weight=1)
        mv_frame.columnconfigure(0, weight=1)
        self.mv_tree = ttk.Treeview(
            mv_frame,
            columns=("date", "name", "type", "qty", "balance"),
            show="headings", height=8)
        for k, t, w in (("date", "日期", 90), ("name", "商品", 150),
                        ("type", "类型", 80), ("qty", "变动", 70),
                        ("balance", "结余", 80)):
            self.mv_tree.heading(k, text=t)
            self.mv_tree.column(k, width=w,
                                anchor="e" if k in ("qty", "balance") else "w")
        self.mv_tree.grid(row=0, column=0, sticky="nsew")

        ttk.Button(f, text="刷新", command=self.refresh).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=12, pady=6)

        self.refresh()

    def refresh(self):
        today = date_iso(datetime.date.today())
        first = today[:8] + "01"
        venta_today = database.list_documents(
            direction="venta", date_from=today, date_to=today)
        venta_month = database.list_documents(
            direction="venta", date_from=first, date_to=today)
        today_sum = sum(parse_amount(d["total"]) for d in venta_today)
        month_sum = sum(parse_amount(d["total"]) for d in venta_month)

        prods = database.list_products()
        low = database.low_stock_products()

        self._set_card("today", "今日销售额", f"{format_amount(today_sum, symbols=False)}\n"
                       f"{len(venta_today)} 单出货")
        self._set_card("month", "本月销售额", f"{format_amount(month_sum, symbols=False)}\n"
                       f"{len(venta_month)} 单出货")
        self._set_card("products", "商品种类", f"{len(prods)}")
        self._set_card("low", "库存预警", f"{len(low)} 件", warn=len(low) > 0)

        self.low_tree.delete(*self.low_tree.get_children())
        for p in low:
            self.low_tree.insert("", "end", tags=("low",),
                                 values=(p["name"],
                                         format_amount(p["stock_qty"], symbols=False),
                                         format_amount(p["min_stock"], symbols=False),
                                         p["unit"] or "-"))

        self.mv_tree.delete(*self.mv_tree.get_children())
        for m in database.list_stock_moves(20):
            self.mv_tree.insert("", "end",
                                values=(
                                    m["date"] or "-",
                                    m["pname"] or m["pcode"] or "(商品已删)",
                                    _MOVE_LABELS.get(m["move_type"], m["move_type"]),
                                    ("+" if m["qty"] >= 0 else "")
                                    + format_amount(m["qty"], symbols=False),
                                    format_amount(m["balance"], symbols=False),
                                ))
        if not low:
            self.low_tree.insert("", "end", values=("— 暂无预警 —", "", "", ""))

    def _set_card(self, key, title, text, warn=False):
        cf, val = self._cards[key]
        cf.config(text=title)
        val.config(text=text, foreground="#c0392b" if warn else "#1f6feb")
