"""店铺支出日报表。

- 一笔一行：同一天可录入不同币种、不同付款方式的多笔支出。
- 费用类别、付款方式、币种均为下拉菜单。
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app import config
from app.db import database
from app.utils import format_amount, parse_amount, date_iso


class DailyExpensePage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.vars = {}
        self.current_id = None
        # 费用类别：界面显示名称 ←→ 数据库 key
        self._label_to_key = {label: key for key, label in config.EXPENSE_CATEGORIES}
        self._key_to_label = {key: label for key, label in config.EXPENSE_CATEGORIES}

    def build(self):
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # -------------------------------------------------------- 列表
        list_frame = ttk.LabelFrame(f, text="店铺支出日报表", padding=10)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        cols = (
            ("date", "日期", 95),
            ("summary", "摘要", 140),
            ("category", "费用类别", 105),
            ("method", "付款方式", 95),
            ("currency", "币种", 140),
            ("amount", "金额", 130),
            ("notes", "备注", 170),
        )
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols],
                                 show="headings", height=11)
        for key, text, width in cols:
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width,
                             anchor="e" if key == "amount" else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # -------------------------------------------------------- 编辑表单
        form = ttk.LabelFrame(
            f, text="录入 / 编辑（同一天可录入多笔不同币种 / 付款方式）", padding=10)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        ttk.Label(form, text="日期").grid(row=0, column=0, sticky="w", pady=3)
        self.vars["date"] = tk.StringVar(value=date_iso(datetime.date.today()))
        ttk.Entry(form, textvariable=self.vars["date"], width=14).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="摘要").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.vars["summary"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["summary"], width=38).grid(
            row=0, column=3, columnspan=3, sticky="w", padx=8)

        ttk.Label(form, text="费用类别").grid(row=1, column=0, sticky="w", pady=3)
        self.vars["category"] = tk.StringVar(
            value=self._key_to_label[config.EXPENSE_CATEGORIES[0][0]])
        ttk.Combobox(form, textvariable=self.vars["category"], state="readonly",
                     width=14,
                     values=[label for _k, label in config.EXPENSE_CATEGORIES]).grid(
            row=1, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="付款方式").grid(row=1, column=2, sticky="w", padx=(14, 0))
        self.vars["method"] = tk.StringVar(value=config.PAY_METHOD_CARD)
        ttk.Combobox(form, textvariable=self.vars["method"], state="readonly",
                     width=12, values=config.PAY_METHODS).grid(
            row=1, column=3, sticky="w", padx=8)

        ttk.Label(form, text="币种").grid(row=1, column=4, sticky="w", padx=(14, 0))
        self.vars["currency"] = tk.StringVar(value=config.PAY_CURRENCY_VES)
        ttk.Combobox(form, textvariable=self.vars["currency"], state="readonly",
                     width=16, values=config.PAY_CURRENCIES).grid(
            row=1, column=5, sticky="w", padx=8)

        ttk.Label(form, text="金额").grid(row=2, column=0, sticky="w", pady=3)
        self.vars["amount"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["amount"], width=16).grid(
            row=2, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="备注").grid(row=2, column=2, sticky="w", padx=(14, 0))
        self.vars["notes"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["notes"], width=38).grid(
            row=2, column=3, columnspan=3, sticky="w", padx=8)

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=3, column=0, columnspan=6, sticky="w", pady=8)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="删除选中", command=self._delete).pack(side="left", padx=4)

        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=4, column=0, columnspan=6, sticky="w")

        self.refresh()

    # ------------------------------------------------------------ 数据
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for r in database.list_daily_expense_items():
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["date"] or "",
                r["summary"] or "",
                database.expense_category_label(r["category"]),
                r["method"] or "",
                r["currency"] or "",
                format_amount(r["amount"]),
                r["notes"] or ""))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        rec = database.get_daily_expense_item(int(sel[0]))
        if not rec:
            return
        self.current_id = rec["id"]
        self.vars["date"].set(rec["date"] or "")
        self.vars["summary"].set(rec["summary"] or "")
        self.vars["category"].set(
            self._key_to_label.get(rec["category"], rec["category"] or ""))
        self.vars["method"].set(rec["method"] or config.PAY_METHOD_CARD)
        self.vars["currency"].set(rec["currency"] or config.PAY_CURRENCY_VES)
        self.vars["amount"].set(f"{float(rec.get('amount') or 0):.2f}")
        self.vars["notes"].set(rec["notes"] or "")

    def _collect(self) -> dict:
        label = self.vars["category"].get()
        return {
            "id": self.current_id,
            "date": self.vars["date"].get().strip() or date_iso(datetime.date.today()),
            "summary": self.vars["summary"].get(),
            "category": self._label_to_key.get(label, label),
            "method": self.vars["method"].get(),
            "currency": self.vars["currency"].get(),
            "amount": parse_amount(self.vars["amount"].get()),
            "notes": self.vars["notes"].get(),
        }

    def _save(self):
        try:
            rec = self._collect()
            if not rec["amount"]:
                messagebox.showwarning("提示", "请输入金额。", parent=self.frame)
                return
            database.save_daily_expense_item(rec)
            self.status.config(text="保存成功", foreground="green")
            self.current_id = None
            self.refresh()
            self._new()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        self.current_id = None
        self.vars["date"].set(date_iso(datetime.date.today()))
        self.vars["summary"].set("")
        self.vars["category"].set(self._key_to_label[config.EXPENSE_CATEGORIES[0][0]])
        self.vars["method"].set(config.PAY_METHOD_CARD)
        self.vars["currency"].set(config.PAY_CURRENCY_VES)
        self.vars["amount"].set("0")
        self.vars["notes"].set("")
        self.tree.selection_remove(self.tree.selection())
        self.status.config(text="", foreground="gray")

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一行", parent=self.frame)
            return
        if messagebox.askyesno("确认删除", "确定删除选中的记录？", parent=self.frame):
            database.delete_daily_expense_item(int(sel[0]))
            self.current_id = None
            self.refresh()
            self._new()
