"""结汇 / 兑换单：外币原币 ↔ 各币种库存现金互相兑换，并生成会计凭证。

业务规则：
  · 汇率按「录入日期」取（exchange_rates 历史，或当前设置兜底），不是系统当天。
  · 选好日期/换出币种后，账面汇率 & 结汇汇率自动带出（可手改）。
  · 填入汇出原币金额后，按当日交叉汇率自动带出换入原币金额（可手改）。
凭证结构（见 app.accounting.fx）：
    借  库存现金（换入币种）  换入原币
    贷  库存现金（换出币种）  换出原币
    借/贷 汇兑损益            本位币到账 − 换出原币×账面汇率
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app import config
from app.accounting import fx as fx_mod
from app.accounting import rates as rates_mod
from app.db import database
from app.utils import format_amount, parse_amount, date_iso


class FxExchangePage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.current_id = None
        self.vars = {}
        self._loading = False
        self._busy = False
        self._last_to = ""

    # ------------------------------------------------------------ 构建
    def build(self):
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # ----------------------------------------------------- 列表
        list_frame = ttk.LabelFrame(f, text="结汇 / 兑换单列表", padding=10)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        cols = (
            ("date", "日期", 95),
            ("from_currency", "换出币种", 90),
            ("from_amount", "汇出原币", 110),
            ("settle_rate", "结汇汇率", 95),
            ("to_currency", "换入币种", 90),
            ("to_amount", "换入原币", 110),
            ("home_amount", "本位币到账", 120),
            ("gain_loss", "汇兑损益", 110),
            ("notes", "备注", 150),
        )
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols],
                                 show="headings", height=10)
        for key, text, width in cols:
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width,
                             anchor="e" if key not in ("date", "notes") else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ----------------------------------------------------- 表单
        form = ttk.LabelFrame(
            f, text="录入 / 编辑兑换单（库存现金各币种可互相兑换）", padding=10)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        cur_codes = list(config.PAY_CURRENCIES)
        cur_labels = [config.currency_label(c) for c in cur_codes]

        self.vars["date"] = tk.StringVar(value=date_iso(datetime.date.today()))
        self.vars["from_currency"] = tk.StringVar(value=cur_labels[0])
        self.vars["from_amount"] = tk.StringVar(value="0")
        self.vars["book_rate"] = tk.StringVar(value="")
        self.vars["settle_rate"] = tk.StringVar(value="")
        self.vars["to_currency"] = tk.StringVar(
            value=cur_labels[1] if len(cur_labels) > 1 else cur_labels[0])
        self.vars["to_amount"] = tk.StringVar(value="0")
        self.vars["notes"] = tk.StringVar()

        ttk.Label(form, text="日期").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.vars["date"], width=14).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(form, text="换出币种").grid(row=0, column=2, sticky="w", padx=(14, 0))
        ttk.Combobox(form, textvariable=self.vars["from_currency"], state="readonly",
                     width=12, values=cur_labels).grid(
            row=0, column=3, sticky="w", padx=8)
        ttk.Label(form, text="汇出原币金额").grid(row=0, column=4, sticky="w", padx=(14, 0))
        ttk.Entry(form, textvariable=self.vars["from_amount"], width=14).grid(
            row=0, column=5, sticky="w", padx=8)

        ttk.Label(form, text="账面汇率").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.vars["book_rate"], width=12).grid(
            row=1, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(form, text="结汇汇率").grid(row=1, column=2, sticky="w", padx=(14, 0))
        ttk.Entry(form, textvariable=self.vars["settle_rate"], width=12).grid(
            row=1, column=3, sticky="w", padx=8)
        ttk.Label(form, text="（按录入日期自动带出，可手改）").grid(row=1, column=4, sticky="w")

        ttk.Label(form, text="换入币种").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(form, textvariable=self.vars["to_currency"], state="readonly",
                     width=12, values=cur_labels).grid(
            row=2, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(form, text="换入原币金额").grid(row=2, column=2, sticky="w", padx=(14, 0))
        ttk.Entry(form, textvariable=self.vars["to_amount"], width=14).grid(
            row=2, column=3, sticky="w", padx=8)
        ttk.Label(form, text="（按汇出金额+当日汇率自动带出，可手改）").grid(row=2, column=4, sticky="w")
        ttk.Label(form, text="备注").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.vars["notes"], width=30).grid(
            row=3, column=1, columnspan=5, sticky="w", padx=8)

        btn = ttk.Frame(form)
        btn.grid(row=4, column=0, columnspan=8, sticky="w", pady=8)
        ttk.Button(btn, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn, text="删除选中", command=self._delete).pack(side="left", padx=4)
        ttk.Button(btn, text="查看凭证", command=self._show_voucher).pack(side="left", padx=4)
        ttk.Label(btn, text="（点击列表中的一行即可再编辑）",
                  foreground="gray").pack(side="left", padx=8)

        self.result = ttk.Label(form, text="", foreground="#1f6feb")
        self.result.grid(row=5, column=0, columnspan=8, sticky="w")
        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=6, column=0, columnspan=8, sticky="w")

        # ----------------------------------------------------- 联动
        for name in ("date", "from_currency", "to_currency"):
            self.vars[name].trace_add("write", lambda *a, n=name: self._on_date_ccy(n))
        self.vars["from_amount"].trace_add("write", lambda *a: self._on_amount())

        self.refresh()
        self._on_date_ccy("date")  # 首次按今天带出汇率

    # ------------------------------------------------------------ 自动联动
    def _safe(self, fn):
        if self._busy or self._loading:
            return
        self._busy = True
        try:
            fn()
        finally:
            self._busy = False

    def _on_date_ccy(self, _name):
        self._safe(self._refill_rates)

    def _on_amount(self):
        self._safe(lambda: self._recompute(force=False))

    def _refill_rates(self):
        """按录入日期 + 换出币种，自动带出账面/结汇汇率。"""
        date = self.vars["date"].get().strip()
        from_cur = config.normalize_currency(self.vars["from_currency"].get())
        if not date or not from_cur:
            return
        from_rate = rates_mod.rate_on_date(date, from_cur)
        note = ""
        hist = database.get_rate_on_or_before(date, from_cur)
        if hist is None:
            note = "（该日期无历史汇率，已用当前设置汇率兜底，可手改）"
        if from_rate and from_rate > 0:
            self.vars["book_rate"].set(f"{from_rate:.4f}")
            self.vars["settle_rate"].set(f"{from_rate:.4f}")
        self._recompute(force=True)
        if note:
            self.status.config(text=note, foreground="gray")

    def _recompute(self, force=False):
        """重算换入原币（自动带出）与本位币到账 / 汇兑损益预览。"""
        try:
            from_amt = parse_amount(self.vars["from_amount"].get())
            book = parse_amount(self.vars["book_rate"].get())
            settle = parse_amount(self.vars["settle_rate"].get())
        except Exception:  # noqa: BLE001
            return
        date = self.vars["date"].get().strip()
        from_cur = config.normalize_currency(self.vars["from_currency"].get())
        to_cur = config.normalize_currency(self.vars["to_currency"].get())
        from_rate = rates_mod.rate_on_date(date, from_cur) if date else 0
        to_rate = rates_mod.rate_on_date(date, to_cur) if date else 0

        if from_amt and from_rate and to_rate:
            new_to = from_amt * from_rate / to_rate
            cur_to = self.vars["to_amount"].get().strip()
            if force or cur_to in ("", "0", "0.0", "0.00") or \
                    abs(parse_amount(cur_to) - (parse_amount(self._last_to) or -1)) < 1e-6:
                self.vars["to_amount"].set(f"{new_to:.2f}")
                self._last_to = f"{new_to:.2f}"

        amts = fx_mod.compute_amounts(from_amt, book, settle)
        self.result.config(
            text=f"本位币到账：{format_amount(amts['home_amount'], symbols=False)}"
                 f"　汇兑损益：{format_amount(amts['gain_loss'], symbols=False)}")

    # ------------------------------------------------------------ 数据
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for r in database.list_fx_orders():
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["date"] or "",
                config.currency_label(r["from_currency"]) or r["from_currency"],
                format_amount(r["from_amount"], symbols=False),
                format_amount(r["settle_rate"], symbols=False),
                config.currency_label(r["to_currency"]) or r["to_currency"],
                format_amount(r["to_amount"], symbols=False),
                format_amount(r["home_amount"], symbols=False),
                format_amount(r["gain_loss"], symbols=False),
                r["notes"] or ""))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        rec = database.get_fx_order(int(sel[0]))
        if not rec:
            return
        self.current_id = rec["id"]
        self._loading = True
        self.vars["date"].set(rec["date"] or "")
        self.vars["from_currency"].set(
            config.currency_label(rec["from_currency"]) or rec["from_currency"])
        self.vars["from_amount"].set(f"{float(rec.get('from_amount') or 0):.2f}")
        self.vars["book_rate"].set(f"{float(rec.get('book_rate') or 0):.4f}")
        self.vars["settle_rate"].set(f"{float(rec.get('settle_rate') or 0):.4f}")
        self.vars["to_currency"].set(
            config.currency_label(rec["to_currency"]) or rec["to_currency"])
        self.vars["to_amount"].set(f"{float(rec.get('to_amount') or 0):.2f}")
        self.vars["notes"].set(rec["notes"] or "")
        self._last_to = f"{float(rec.get('to_amount') or 0):.2f}"
        self._loading = False
        self._recompute(force=False)
        self.status.config(
            text=f"正在编辑：{rec.get('date') or ''}（改完点「保存」）",
            foreground="#1f6feb")

    def _collect(self) -> dict:
        return {
            "id": self.current_id,
            "date": self.vars["date"].get().strip() or date_iso(datetime.date.today()),
            "from_currency": config.normalize_currency(self.vars["from_currency"].get()),
            "from_amount": parse_amount(self.vars["from_amount"].get()),
            "book_rate": parse_amount(self.vars["book_rate"].get()),
            "settle_rate": parse_amount(self.vars["settle_rate"].get()),
            "to_currency": config.normalize_currency(self.vars["to_currency"].get()),
            "to_amount": parse_amount(self.vars["to_amount"].get()),
            "notes": self.vars["notes"].get(),
        }

    def _save(self):
        try:
            rec = self._collect()
            if not rec["from_amount"]:
                messagebox.showwarning("提示", "请输入汇出原币金额。", parent=self.frame)
                return
            if not rec["to_amount"]:
                messagebox.showwarning("提示", "请输入换入原币金额。", parent=self.frame)
                return
            if rec["from_currency"] == rec["to_currency"]:
                messagebox.showwarning("提示", "换出与换入币种不能相同。", parent=self.frame)
                return
            database.save_fx_order(rec)
            self.status.config(text="已保存兑换单", foreground="green")
            self.refresh()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        self.current_id = None
        self._loading = True
        self.vars["from_amount"].set("0")
        self.vars["to_amount"].set("0")
        self.vars["book_rate"].set("")
        self.vars["settle_rate"].set("")
        self.vars["notes"].set("")
        self._last_to = ""
        self._loading = False
        self._refill_rates()
        self.status.config(text="已清空，可录入新单", foreground="gray")

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中要删除的单据。", parent=self.frame)
            return
        if not messagebox.askyesno("删除", "确定删除选中的兑换单？", parent=self.frame):
            return
        database.delete_fx_order(int(sel[0]))
        self.current_id = None
        self.status.config(text="已删除", foreground="gray")
        self.refresh()

    def _show_voucher(self):
        rec = self._collect() if not self.current_id else database.get_fx_order(self.current_id)
        if not rec or (not rec.get("id") and not rec.get("from_amount")):
            messagebox.showinfo("凭证", "请先保存或选中一笔兑换单。", parent=self.frame)
            return
        if not self.current_id:
            rec = self._collect()
        voucher = fx_mod.build_voucher(rec)
        win = tk.Toplevel(self.frame)
        win.title("兑换单凭证")
        win.transient(self.frame)
        ttk.Label(win, text=f"日期：{rec.get('date') or ''}　"
                  f"换出 {config.currency_label(rec.get('from_currency'))} → "
                  f"换入 {config.currency_label(rec.get('to_currency'))}",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(padx=12, pady=8)
        tree = ttk.Treeview(win, columns=("acc", "name", "debit", "credit"),
                            show="headings", height=len(voucher["entries"]) + 1)
        tree.heading("acc", text="科目编码")
        tree.heading("name", text="科目名称")
        tree.heading("debit", text="借方")
        tree.heading("credit", text="贷方")
        for e in voucher["entries"]:
            tree.insert("", "end", values=(
                e["account"], e["account_name"],
                format_amount(e["debit"], symbols=False),
                format_amount(e["credit"], symbols=False)))
        tree.pack(padx=12, pady=6, fill="both", expand=True)
        ttk.Label(win, text=f"本位币到账：{format_amount(voucher['home_amount'], symbols=False)}"
                  f"　汇兑损益：{format_amount(voucher['gain_loss'], symbols=False)}",
                  foreground="#1f6feb").pack(padx=12, pady=(0, 10))
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 12))
