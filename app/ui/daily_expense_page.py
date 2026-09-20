"""店铺支出日报表。

- 一笔一行：同一天可录入不同币种、不同付款方式的多笔支出。
- 列表一行一笔；点击某一行即把该笔支出回填到表单，修改后保存即可（再编辑）。
- 费用类别：内置科目 + 手工新增的自定义类别（下拉可直接选择，
  下拉框也可直接输入新类别名，保存时自动登记；或点「＋ 新增类别」）。
- 付款方式、币种为下拉菜单。
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from app import config, settings
from app.db import database
from app.utils import format_amount, parse_amount, date_iso


class DailyExpensePage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.vars = {}
        self.current_id = None
        self.cat_combo = None
        self.method_combo = None
        self.method_hint = None
        # 费用类别：界面显示名称 ←→ 数据库 key（含设置里自定义的类别）
        self._reload_categories()
        # 付款方式：科目表里货币资金的明细科目
        self._reload_methods()

    # ------------------------------------------------------ 付款方式
    def _reload_methods(self):
        """付款方式下拉 = 科目表货币资金类明细科目（同名子科目优先）。"""
        try:
            from app.accounting.reports import payment_account_options
            self.pay_options = payment_account_options()
        except Exception:  # noqa: BLE001
            self.pay_options = [{"code": "", "name": m, "label": m, "root": ""}
                                for m in config.PAY_METHODS]
        self.pay_methods = [o["label"] for o in self.pay_options]
        self._method_label_to_name = {o["label"]: o["name"]
                                      for o in self.pay_options}
        if self.method_combo is not None:
            self.method_combo["values"] = self.pay_methods

    def _default_method(self) -> str:
        return self.pay_methods[0] if self.pay_methods else ""

    def _method_name(self, label: str) -> str:
        """下拉文本 → 入库文本（科目名称；手工输入时原样保存）。"""
        text = (label or "").strip()
        return self._method_label_to_name.get(text, text)

    def _method_label(self, name: str) -> str:
        """入库文本 → 下拉显示文本（旧数据 银行卡/现金 原样显示）。"""
        text = (name or "").strip()
        if not text:
            return self._default_method()
        for opt in self.pay_options:
            if opt["name"] == text or opt["label"] == text:
                return opt["label"]
        return text

    def _update_method_hint(self, _event=None):
        """提示该付款方式对应的科目。"""
        if self.method_hint is None:
            return
        name = self._method_name(self.vars["method"].get())
        if not name:
            self.method_hint.config(text="")
            return
        try:
            from app.accounting.reports import resolve_payment_account
            code = resolve_payment_account(name)
        except Exception:  # noqa: BLE001
            code = ""
        self.method_hint.config(
            text=f"→ 科目 {code} {name}" if code else f"→ {name}")

    # ------------------------------------------------------ 费用类别
    def _reload_categories(self):
        """从设置读取费用类别（内置 + 自定义），刷新映射与下拉内容。"""
        cats = settings.get_expense_categories()
        self.categories = cats
        self._label_to_key = {label: key for key, label in cats}
        self._key_to_label = {key: label for key, label in cats}
        if self.cat_combo is not None:
            self.cat_combo["values"] = [label for _k, label in cats]

    def _default_category(self) -> str:
        cats = self.categories or list(config.EXPENSE_CATEGORIES)
        return cats[0][1]

    def _resolve_category_key(self, label: str) -> str:
        """显示名称 → 数据库 key；手工输入的新类别自动登记到设置。"""
        label = (label or "").strip()
        if not label:
            return ""
        key = self._label_to_key.get(label)
        if key:
            return key
        key = settings.add_expense_category(label)
        self._reload_categories()
        return key

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
        self.vars["category"] = tk.StringVar(value=self._default_category())
        self.cat_combo = ttk.Combobox(
            form, textvariable=self.vars["category"], width=14,
            values=[label for _k, label in self.categories])
        self.cat_combo.grid(row=1, column=1, sticky="w", padx=8, pady=3)

        # 付款方式：取科目表里货币资金的明细科目（同名子科目），可直接输入
        ttk.Label(form, text="付款方式").grid(row=1, column=2, sticky="w", padx=(14, 0))
        self.vars["method"] = tk.StringVar(value=self._default_method())
        self.method_combo = ttk.Combobox(
            form, textvariable=self.vars["method"], width=18,
            values=self.pay_methods)
        self.method_combo.grid(row=1, column=3, sticky="w", padx=8)
        self.method_hint = ttk.Label(form, text="", foreground="gray")
        self.method_hint.grid(row=1, column=6, sticky="w", padx=(8, 0))
        self.method_combo.bind("<<ComboboxSelected>>", self._update_method_hint)

        ttk.Label(form, text="币种").grid(row=1, column=4, sticky="w", padx=(14, 0))
        self.vars["currency"] = tk.StringVar(value=config.currency_label(
            config.PAY_CURRENCY_BS))
        ttk.Combobox(form, textvariable=self.vars["currency"], state="readonly",
                     width=16, values=config.pay_currency_labels()).grid(
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
        ttk.Button(btn_frame, text="＋ 新增类别",
                   command=self._add_category).pack(side="left", padx=4)
        ttk.Label(btn_frame, text="（点击列表中的一行即可再编辑）",
                  foreground="gray").pack(side="left", padx=8)

        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=4, column=0, columnspan=6, sticky="w")

        self._update_method_hint()
        self.refresh()

    # ------------------------------------------------------ 新增费用类别
    def _add_category(self):
        """手工新增一个费用类别（保存到设置，下拉立即可用）。"""
        name = simpledialog.askstring(
            "新增费用类别", "类别名称（如：加班餐费、维修费）：",
            parent=self.frame)
        if not name or not name.strip():
            return
        key = settings.add_expense_category(name)
        self._reload_categories()
        self.vars["category"].set(self._key_to_label.get(key, name.strip()))
        self.status.config(text=f"已新增费用类别：{self._key_to_label.get(key, name)}",
                           foreground="green")

    # ------------------------------------------------------------ 数据
    def refresh(self):
        self._reload_categories()
        self._reload_methods()
        self.tree.delete(*self.tree.get_children())
        for r in database.list_daily_expense_items():
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["date"] or "",
                r["summary"] or "",
                database.expense_category_label(r["category"]),
                r["method"] or "",
                config.currency_label(r["currency"]) or r["currency"] or "",
                format_amount(r["amount"]),
                r["notes"] or ""))

    def _on_select(self, event):
        """选中列表中的一行 → 回填表单，进入再编辑状态。"""
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
        self.vars["method"].set(self._method_label(rec.get("method")))
        self.vars["currency"].set(
            config.currency_label(rec.get("currency")) or config.currency_label(
                config.PAY_CURRENCY_BS))
        self.vars["amount"].set(f"{float(rec.get('amount') or 0):.2f}")
        self.vars["notes"].set(rec["notes"] or "")
        self._update_method_hint()
        self.status.config(
            text=f"正在编辑：{rec.get('date') or ''} "
                 f"{database.expense_category_label(rec.get('category'))}"
                 f"（改完点「保存」）",
            foreground="#1f6feb")

    def _collect(self) -> dict:
        label = self.vars["category"].get()
        return {
            "id": self.current_id,
            "date": self.vars["date"].get().strip() or date_iso(datetime.date.today()),
            "summary": self.vars["summary"].get(),
            "category": self._resolve_category_key(label),
            "method": self._method_name(self.vars["method"].get()),
            "currency": config.currency_code(self.vars["currency"].get()),
            "amount": parse_amount(self.vars["amount"].get()),
            "notes": self.vars["notes"].get(),
        }

    def _save(self):
        try:
            editing = bool(self.current_id)
            rec = self._collect()
            if not rec["amount"]:
                messagebox.showwarning("提示", "请输入金额。", parent=self.frame)
                return
            if not rec["category"]:
                messagebox.showwarning("提示", "请选择或输入费用类别。", parent=self.frame)
                return
            database.save_daily_expense_item(rec)
            self.status.config(text="已更新该笔支出" if editing else "已保存一笔支出",
                               foreground="green")
            self.refresh()
            self._new()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        self.current_id = None
        self.vars["date"].set(date_iso(datetime.date.today()))
        self.vars["summary"].set("")
        self.vars["category"].set(self._default_category())
        self.vars["method"].set(self._default_method())
        self.vars["currency"].set(config.currency_label(config.PAY_CURRENCY_BS))
        self.vars["amount"].set("0")
        self.vars["notes"].set("")
        self.tree.selection_remove(self.tree.selection())
        self.status.config(text="", foreground="gray")
        self._update_method_hint()

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
