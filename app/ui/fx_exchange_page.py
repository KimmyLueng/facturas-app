"""结汇 / 兑换单：外币原币 ↔ 各币种库存现金互相兑换，并生成会计凭证。

凭证结构（见 app.accounting.fx）：
    借  库存现金（换入币种）  换入原币
    贷  库存现金（换出币种）  换出原币
    借/贷 汇兑损益            本位币到账 − 换出原币×账面汇率
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from app import config
from app.accounting import fx as fx_mod
from app.db import database
from app.utils import format_amount, parse_amount, date_iso


class FxExchangePage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.current_id = None
        self.vars = {}

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
            ("from_amount", "换出原币", 110),
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

        ttk.Label(form, text="日期").grid(row=0, column=0, sticky="w", pady=3)
        self.vars["date"] = tk.StringVar(value=date_iso(datetime.date.today()))
        ttk.Entry(form, textvariable=self.vars["date"], width=14).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="换出币种").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.vars["from_currency"] = tk.StringVar(value=cur_labels[0])
        ttk.Combobox(form, textvariable=self.vars["from_currency"], state="readonly",
                     width=12, values=cur_labels).grid(
            row=0, column=3, sticky="w", padx=8)

        ttk.Label(form, text="换出原币金额").grid(row=0, column=4, sticky="w", padx=(14, 0))
        self.vars["from_amount"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["from_amount"], width=14).grid(
            row=0, column=5, sticky="w", padx=8)

        ttk.Label(form, text="账面汇率").grid(row=1, column=0, sticky="w", pady=3)
        self.vars["book_rate"] = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.vars["book_rate"], width=12).grid(
            row=1, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="结汇汇率").grid(row=1, column=2, sticky="w", padx=(14, 0))
        self.vars["settle_rate"] = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.vars["settle_rate"], width=12).grid(
            row=1, column=3, sticky="w", padx=8)
        ttk.Label(form, text="（本位币 / 1 单位换出币种）").grid(
            row=1, column=4, sticky="w")

        ttk.Label(form, text="换入币种").grid(row=2, column=0, sticky="w", pady=3)
        self.vars["to_currency"] = tk.StringVar(
            value=cur_labels[1] if len(cur_labels) > 1 else cur_labels[0])
        ttk.Combobox(form, textvariable=self.vars["to_currency"], state="readonly",
                     width=12, values=cur_labels).grid(
            row=2, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="换入原币金额").grid(row=2, column=2, sticky="w", padx=(14, 0))
        self.vars["to_amount"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["to_amount"], width=14).grid(
            row=2, column=3, sticky="w", padx=8)

        ttk.Label(form, text="备注").grid(row=2, column=4, sticky="w", padx=(14, 0))
        self.vars["notes"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["notes"], width=30).grid(
            row=2, column=5, columnspan=3, sticky="w", padx=8)

        btn = ttk.Frame(form)
        btn.grid(row=3, column=0, columnspan=8, sticky="w", pady=8)
        ttk.Button(btn, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn, text="删除选中", command=self._delete).pack(side="left", padx=4)
        ttk.Button(btn, text="查看凭证", command=self._show_voucher).pack(side="left", padx=4)
        ttk.Label(btn, text="（点击列表中的一行即可再编辑）",
                  foreground="gray").pack(side="left", padx=8)

        # 自动计算结果显示
        self.result = ttk.Label(form, text="", foreground="#1f6feb")
        self.result.grid(row=4, column=0, columnspan=8, sticky="w")
        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=5, column=0, columnspan=8, sticky="w")

        self.refresh()

    # ------------------------------------------------------------ 计算预览
    def _preview(self):
        try:
            from_amt = parse_amount(self.vars["from_amount"].get())
            book = parse_amount(self.vars["book_rate"].get())
            settle = parse_amount(self.vars["settle_rate"].get())
        except Exception:  # noqa: BLE001
            return
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
        self._preview()

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        rec = database.get_fx_order(int(sel[0]))
        if not rec:
            return
        self.current_id = rec["id"]
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
        self._preview()
        self.status.config(
            text=f"正在编辑：{rec.get('date') or ''}（改完点「保存」）",
            foreground="#1f6feb")

    def _collect(self) -> dict:
        from_code = config.normalize_currency(self.vars["from_currency"].get())
        to_code = config.normalize_currency(self.vars["to_currency"].get())
        return {
            "id": self.current_id,
            "date": self.vars["date"].get().strip() or date_iso(datetime.date.today()),
            "from_currency": from_code,
            "from_amount": parse_amount(self.vars["from_amount"].get()),
            "book_rate": parse_amount(self.vars["book_rate"].get()),
            "settle_rate": parse_amount(self.vars["settle_rate"].get()),
            "to_currency": to_code,
            "to_amount": parse_amount(self.vars["to_amount"].get()),
            "notes": self.vars["notes"].get(),
        }

    def _save(self):
        try:
            rec = self._collect()
            if not rec["from_amount"]:
                messagebox.showwarning("提示", "请输入换出原币金额。", parent=self.frame)
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
        for k in ("from_amount", "to_amount"):
            self.vars[k].set("0")
        self.vars["book_rate"].set("1")
        self.vars["settle_rate"].set("1")
        self.vars["notes"].set("")
        self.status.config(text="已清空，可录入新单", foreground="gray")
        self._preview()

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
        try:
            rec = database.get_fx_order(self.current_id) if self.current_id else rec
        except Exception:  # noqa: BLE001
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
