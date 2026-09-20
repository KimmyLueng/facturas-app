"""店铺收入日报表。

- 一笔一行：同一天可录入不同币种、不同支付方式的多笔收入。
- 列表按「明细行」展示；点击某一行即把该笔数据回填到表单，可修改后再保存（再编辑）。
- 备注按笔独立保存：改其中一笔的备注不会影响同一天的其他笔。
- 「分店」下拉读取「设置 → 分店列表（Sucursales）」。
- 「支付方式」下拉：银行卡 / 电子支付 / 现钞，各自限定可选币种。
- 科目归属（财务报表，按支付方式 + 币种）：
    现钞     + 法定货币（USD/Bs/CNY）→ 库存现金
    银行卡   + 法定货币              → 银行存款
    电子支付（扫码支付）              → 其他货币资金
    稳定币（USDT）无现钞形态，只能记银行存款 / 其他货币资金
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app import config, settings
from app.accounting import reports
from app.db import database
from app.utils import format_amount, parse_amount, date_iso


# 科目归集展示：科目 key → 说明
ACCOUNT_LABELS = (
    ("cash", "现钞（USD/Bs/CNY）→ 库存现金"),
    ("bank", "银行卡 → 银行存款"),
    ("crypto", "电子支付/扫码 → 其他货币资金"),
)


class DailyIncomePage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.vars = {}
        self.current_row_id = None      # 正在编辑的明细行 id（None = 新增）
        self.current_income_id = None   # 该明细行所属日报 id
        self.rows_by_iid = {}           # 列表行 → 数据

    # ------------------------------------------------------------ 构建界面
    def build(self):
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # -------------------------------------------------------- 列表
        list_frame = ttk.LabelFrame(f, text="店铺收入日报表", padding=10)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        cols = (
            ("date", "日期", 100),
            ("store", "分店", 110),
            ("method", "支付方式", 100),
            ("currency", "币种", 170),
            ("amount", "金额", 140),
            ("notes", "备注", 190),
        )
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols],
                                 show="headings", height=10)
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
            f, text="录入 / 编辑（同一天可录入多笔不同币种 / 支付方式）", padding=10)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        ttk.Label(form, text="日期").grid(row=0, column=0, sticky="w", pady=3)
        self.vars["date"] = tk.StringVar(value=date_iso(datetime.date.today()))
        ttk.Entry(form, textvariable=self.vars["date"], width=14).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="分店").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.vars["store"] = tk.StringVar()
        self.store_combo = ttk.Combobox(form, textvariable=self.vars["store"],
                                        state="readonly", width=14)
        self.store_combo.grid(row=0, column=3, sticky="w", padx=8)

        ttk.Label(form, text="支付方式").grid(row=0, column=4, sticky="w", padx=(14, 0))
        self.vars["method"] = tk.StringVar(value=config.INCOME_SOURCE_CARD)
        self.method_combo = ttk.Combobox(
            form, textvariable=self.vars["method"], state="readonly", width=12,
            values=list(config.INCOME_SOURCES))
        self.method_combo.grid(row=0, column=5, sticky="w", padx=8)
        self.method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        ttk.Label(form, text="币种").grid(row=1, column=0, sticky="w", pady=3)
        self.vars["currency"] = tk.StringVar()
        self.cur_combo = ttk.Combobox(form, textvariable=self.vars["currency"],
                                      state="readonly", width=26)
        self.cur_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="金额").grid(row=1, column=3, sticky="w", padx=(14, 0))
        self.vars["amount"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["amount"], width=16).grid(
            row=1, column=4, sticky="w", padx=8)

        ttk.Label(form, text="备注").grid(row=1, column=5, sticky="w", padx=(14, 0))
        self.vars["notes"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["notes"], width=28).grid(
            row=1, column=6, sticky="w", padx=8)

        btn = ttk.Frame(form)
        btn.grid(row=2, column=0, columnspan=7, sticky="w", pady=8)
        ttk.Button(btn, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn, text="删除选中", command=self._delete).pack(side="left", padx=4)
        ttk.Button(btn, text="刷新分店", command=self._reload).pack(side="left", padx=4)
        ttk.Label(btn, text="（点击列表中的一行即可再编辑）",
                  foreground="gray").pack(side="left", padx=8)

        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=3, column=0, columnspan=7, sticky="w")

        self.account_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.account_var, foreground="#1f6feb",
                  font=("Microsoft YaHei UI", 9)).grid(
            row=4, column=0, columnspan=7, sticky="w", pady=(6, 0))

        self._reload_stores()
        self._sync_currencies()
        self.refresh()

    # ------------------------------------------------------------ 下拉联动
    def _reload_stores(self):
        """从设置读取分店列表，填充下拉菜单。"""
        stores = settings.get_stores()
        self.store_combo["values"] = stores
        if not (self.vars["store"].get() or "").strip() and stores:
            self.vars["store"].set(stores[0])

    @staticmethod
    def _cur_code(label):
        """界面中文标签 → 币种代码（已是代码则原样返回）。"""
        for c in (config.INCOME_CUR_BS, config.INCOME_CUR_USD, config.INCOME_CUR_CNY,
                  config.INCOME_CUR_USDT):
            if config.income_currency_label(c) == label:
                return c
        return label

    def _on_method_change(self, _event=None):
        """切换支付方式后刷新可选币种。"""
        self._sync_currencies()

    def _sync_currencies(self):
        codes = config.INCOME_SOURCE_CURRENCIES.get(
            self.vars["method"].get(), [config.INCOME_CUR_BS])
        labels = [config.income_currency_label(c) for c in codes]
        self.cur_combo["values"] = labels
        current = self.vars["currency"].get()
        if current not in labels:
            self.vars["currency"].set(labels[0] if labels else "")

    # ------------------------------------------------------------ 数据
    def refresh(self):
        self._reload_stores()
        self.tree.delete(*self.tree.get_children())
        self.rows_by_iid = {}
        for r in database.list_daily_income_rows():
            iid = f"row{r['row_id']}"
            self.rows_by_iid[iid] = r
            self.tree.insert("", "end", iid=iid, values=(
                r["date"],
                r["store"] or "-",
                r["source"] or "",
                config.income_currency_label(r["currency"]),
                format_amount(r["amount"]),
                r["notes"]))
        self._refresh_summary()

    def _refresh_summary(self):
        """底部展示营业额按来源归集到的财务报表科目及金额。"""
        try:
            chart = reports.load_chart_index()
            agg = database.daily_income_by_account()
        except Exception:  # noqa: BLE001
            self.account_var.set("")
            return
        parts = []
        for key, label in ACCOUNT_LABELS:
            by_cur = agg.get(key) or {}
            if not by_cur:
                continue
            code = reports.resolve_account(chart, key)
            txt = "  ".join(f"{format_amount(v)} {c}"
                            for c, v in sorted(by_cur.items()))
            parts.append(f"{label}（科目 {code or '-'}）：{txt}")
        self.account_var.set("    |    ".join(parts) if parts else "")

    # ------------------------------------------------------------ 交互
    def _on_select(self, event=None):
        """选中列表中的一行 → 把该笔收入回填表单，进入再编辑状态。"""
        sel = self.tree.selection()
        if not sel:
            return
        r = self.rows_by_iid.get(sel[0])
        if not r:
            rec = database.get_daily_income_row(int(str(sel[0]).lstrip("row") or 0))
            if not rec:
                return
            r = rec
        self.current_row_id = r["row_id"]
        self.current_income_id = r.get("income_id")
        self._reload_stores()
        self.vars["date"].set(r.get("date") or "")
        if r.get("store"):
            self.vars["store"].set(r["store"])
        self.vars["method"].set(r.get("source") or config.INCOME_SOURCE_CARD)
        self._sync_currencies()
        if r.get("currency"):
            self.vars["currency"].set(config.income_currency_label(r["currency"]))
        self.vars["amount"].set(f"{float(r.get('amount') or 0):.2f}")
        self.vars["notes"].set(r.get("notes") or "")
        self.status.config(
            text=f"正在编辑：{r.get('date') or ''} {r.get('store') or ''} "
                 f"{r.get('source') or ''}（改完点「保存」）",
            foreground="#1f6feb")

    def _collect(self) -> dict:
        amt = parse_amount(self.vars["amount"].get())
        notes = self.vars["notes"].get()
        rows = []
        if amt:
            rows.append({
                "store": (self.vars["store"].get() or "").strip(),
                "source": self.vars["method"].get(),
                "currency": self._cur_code(self.vars["currency"].get()),
                "amount": amt,
                "notes": notes,      # 备注跟着这一笔走，不影响同一天其他笔
            })
        d = self.vars["date"].get().strip() or date_iso(datetime.date.today())
        return {"id": self.current_row_id, "date": d, "notes": notes, "rows": rows}

    def _save(self):
        try:
            rec = self._collect()
            if not rec["rows"]:
                messagebox.showwarning("提示", "请输入金额。", parent=self.frame)
                return
            row = rec["rows"][0]
            if not row["store"]:
                messagebox.showwarning("提示", "请选择分店（设置里可维护分店列表）。",
                                       parent=self.frame)
                return
            if self.current_row_id:
                # 再编辑：只更新这一笔（含本笔备注），同一天的其他笔保持不变
                income_id = database.get_or_create_daily_income(rec["date"])
                database.update_daily_income_row(self.current_row_id, row)
                if income_id != self.current_income_id:
                    # 日期改了：把这笔移到那一天的记录里
                    database.move_daily_income_row(self.current_row_id, income_id)
                msg = "已更新该笔收入"
            else:
                income_id = database.get_or_create_daily_income(rec["date"])
                database.add_daily_income_row(income_id, row)
                msg = "已新增一笔收入"
            self.status.config(text=msg, foreground="green")
            self.refresh()
            self._new()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        """清空表单，进入新增状态。"""
        self.current_row_id = None
        self.current_income_id = None
        self.vars["date"].set(date_iso(datetime.date.today()))
        self.vars["amount"].set("0")
        self.vars["notes"].set("")
        self.tree.selection_remove(self.tree.selection())
        self.status.config(text="", foreground="gray")

    def _reload(self):
        """重新读取设置里的分店列表并刷新界面。"""
        self._reload_stores()
        self.refresh()

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一行", parent=self.frame)
            return
        r = self.rows_by_iid.get(sel[0]) or {}
        label = (f"{r.get('date') or ''} {r.get('store') or ''} "
                 f"{r.get('source') or ''} {format_amount(r.get('amount'))}")
        if messagebox.askyesno("确认删除", f"确定删除这笔收入？\n{label}",
                               parent=self.frame):
            row_id = r.get("row_id") or int(str(sel[0]).lstrip("row") or 0)
            database.delete_daily_income_row(row_id)
            self.refresh()
            self._new()
