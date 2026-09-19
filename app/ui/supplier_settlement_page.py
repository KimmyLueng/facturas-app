"""供应商往来结算明细表：供货金额、支付金额（银行转账/现金委币/现金美元）。"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from app import config
from app.db import database
from app.settings import add_store, load_settings
from app.utils import format_amount, parse_amount, date_iso


class SupplierSettlementPage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.vars = {}
        self.current_id = None

    def build(self):
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # -------------------------------------------------------- 列表
        list_frame = ttk.LabelFrame(f, text="供应商往来结算明细表", padding=10)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        cols = (
            ("date", "日期", 90),
            ("store", "入库分店", 90),
            ("partner_name", "供应商名称", 140),
            ("summary", "摘要", 120),
            ("doc_number", "单号", 100),
            ("supply_amount_ves", "供货金额(委币)", 100),
            ("pay_method", "方式", 70),
            ("pay_currency", "币种", 90),
            ("pay_bank", "银行转账", 90),
            ("pay_cash_ves", "现金(委币)", 90),
            ("pay_cash_usd", "现金(美元)", 90),
            ("pay_cash_cny", "现金(人民币)", 95),
            ("notes", "备注", 120),
        )
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols],
                                 show="headings", height=10)
        for key, text, width in cols:
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="e")
        self.tree.column("date", anchor="w")
        self.tree.column("partner_name", anchor="w")
        self.tree.column("summary", anchor="w")
        self.tree.column("doc_number", anchor="w")
        self.tree.column("pay_method", anchor="w")
        self.tree.column("pay_currency", anchor="w")
        self.tree.column("notes", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # -------------------------------------------------------- 编辑表单
        form = ttk.LabelFrame(f, text="录入 / 编辑", padding=10)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        # 第一行：日期、供应商、单号
        ttk.Label(form, text="日期").grid(row=0, column=0, sticky="w", pady=3)
        self.vars["date"] = tk.StringVar(value=date_iso(datetime.date.today()))
        ttk.Entry(form, textvariable=self.vars["date"], width=14).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="供应商名称").grid(row=0, column=2, sticky="w", pady=3, padx=(16, 0))
        self.vars["partner_name"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["partner_name"], width=28).grid(
            row=0, column=3, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="单号").grid(row=0, column=4, sticky="w", pady=3, padx=(16, 0))
        self.vars["doc_number"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["doc_number"], width=16).grid(
            row=0, column=5, sticky="w", padx=8, pady=3)

        # 第二行：入库分店
        ttk.Label(form, text="入库分店").grid(row=1, column=0, sticky="w", pady=3)
        self.vars["store"] = tk.StringVar(
            value=self._store_default())
        self.store_cb = ttk.Combobox(form, textvariable=self.vars["store"],
                                     width=12, values=[""] + self._store_options())
        self.store_cb.grid(row=1, column=1, sticky="w", padx=8, pady=3)
        ttk.Button(form, text="＋ 添加分店", width=10,
                   command=self._add_store_dialog).grid(
            row=1, column=2, sticky="w", pady=3)
        self._store_prompt = ttk.Label(
            form, text="（该笔供货结算对应的入库分店）", foreground="gray")
        self._store_prompt.grid(row=1, column=3, columnspan=3, sticky="w", padx=(12, 0))

        # 第三行：摘要、供货金额
        ttk.Label(form, text="摘要").grid(row=2, column=0, sticky="w", pady=3)
        self.vars["summary"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["summary"], width=40).grid(
            row=2, column=1, columnspan=3, sticky="we", padx=8, pady=3)

        ttk.Label(form, text="供货金额(委币)").grid(row=2, column=4, sticky="w", pady=3, padx=(16, 0))
        self.vars["supply_amount_ves"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["supply_amount_ves"], width=16).grid(
            row=2, column=5, sticky="w", padx=8, pady=3)

        # 第四行：付款方式、币种、支付金额
        ttk.Label(form, text="付款方式").grid(row=3, column=0, sticky="w", pady=3)
        self.vars["pay_method"] = tk.StringVar(value=config.PAY_METHOD_CARD)
        ttk.Combobox(form, textvariable=self.vars["pay_method"],
                     values=config.PAY_METHODS, width=12, state="readonly").grid(
            row=3, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="币种").grid(row=3, column=2, sticky="w", pady=3, padx=(16, 0))
        self.vars["pay_currency"] = tk.StringVar(value=config.PAY_CURRENCY_BS)
        ttk.Combobox(form, textvariable=self.vars["pay_currency"],
                     values=config.PAY_CURRENCIES, width=14, state="readonly").grid(
            row=3, column=3, sticky="w", padx=8, pady=3)

        ttk.Label(form, text="支付金额").grid(row=3, column=4, sticky="w", pady=3, padx=(16, 0))
        self.vars["pay_amount"] = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.vars["pay_amount"], width=16).grid(
            row=3, column=5, sticky="w", padx=8, pady=3)

        # 第五行：备注
        ttk.Label(form, text="备注").grid(row=4, column=0, sticky="w", pady=3)
        self.vars["notes"] = tk.StringVar()
        ttk.Entry(form, textvariable=self.vars["notes"], width=70).grid(
            row=4, column=1, columnspan=5, sticky="we", padx=8, pady=3)

        # 按钮
        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=5, column=0, columnspan=6, sticky="w", pady=8)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="删除选中", command=self._delete).pack(side="left", padx=4)

        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=6, column=0, columnspan=6, sticky="w")

        self.refresh()

    def _store_options(self) -> list:
        """分店选项 = 设置中的分店列表 + 结算记录中出现过的分店（去重）。"""
        stores = list(load_settings().get("stores") or config.DEFAULT_STORES)
        try:
            for r in database.list_supplier_settlements():
                st = (r.get("store") or "").strip()
                if st and st not in stores:
                    stores.append(st)
        except Exception:  # noqa: BLE001
            pass
        return stores

    def _store_default(self) -> str:
        opts = self._store_options()
        return opts[0] if opts else ""

    def _reload_store_options(self, select=None):
        opts = [""] + self._store_options()
        if self.store_cb:
            self.store_cb["values"] = opts
        if select in opts:
            self.vars["store"].set(select)

    def _add_store_dialog(self):
        name = simpledialog.askstring(
            "添加分店", "输入新分店名称（如 C店）：", parent=self.frame) if self.frame else None
        name = (name or "").strip()
        if not name:
            return
        added = add_store(name)
        self.app.state.settings = load_settings()
        self._reload_store_options(select=name)
        self.status.config(
            text=f"✔ 分店“{name}”已添加。" if added else f"分店“{name}”已存在。",
            foreground="green")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._reload_store_options()
        for r in database.list_supplier_settlements():
            self.tree.insert(
                "", "end", iid=str(r["id"]),
                values=(
                    r["date"],
                    r.get("store") or "-",
                    r["partner_name"],
                    r["summary"],
                    r["doc_number"],
                    format_amount(r["supply_amount_ves"]),
                    r["pay_method"],
                    r["pay_currency"],
                    format_amount(r["pay_bank"]),
                    format_amount(r["pay_cash_ves"]),
                    format_amount(r["pay_cash_usd"]),
                    format_amount(r["pay_cash_cny"]),
                    r["notes"],
                ))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        rec = database.get_supplier_settlement(int(sel[0]))
        if not rec:
            return
        self.current_id = rec["id"]
        self.vars["date"].set(rec["date"] or "")
        self.vars["partner_name"].set(rec["partner_name"] or "")
        self.vars["store"].set(rec.get("store") or self._store_default())
        self.vars["summary"].set(rec["summary"] or "")
        self.vars["doc_number"].set(rec["doc_number"] or "")
        self.vars["supply_amount_ves"].set(self._fmt_num(rec["supply_amount_ves"]))
        self.vars["pay_method"].set(rec["pay_method"] or config.PAY_METHOD_CARD)
        self.vars["pay_currency"].set(rec["pay_currency"] or config.PAY_CURRENCY_BS)
        self.vars["notes"].set(rec["notes"] or "")
        # 支付金额回填：根据已保存的列反推（只有一列非零）
        total = (rec["pay_bank"] + rec["pay_cash_ves"]
                 + rec["pay_cash_usd"] + rec["pay_cash_cny"])
        self.vars["pay_amount"].set(self._fmt_num(total))

    def _fmt_num(self, v):
        return f"{v:.2f}" if v else "0"

    def _collect(self) -> dict:
        rec = {
            "id": self.current_id,
            "partner_name": self.vars["partner_name"].get().strip(),
            "store": self.vars["store"].get().strip(),
            "summary": self.vars["summary"].get().strip(),
            "doc_number": self.vars["doc_number"].get().strip(),
            "notes": self.vars["notes"].get().strip(),
        }
        d = self.vars["date"].get().strip()
        rec["date"] = d if d else date_iso(datetime.date.today())
        rec["supply_amount_ves"] = parse_amount(self.vars["supply_amount_ves"].get())
        rec["pay_method"] = self.vars["pay_method"].get()
        rec["pay_currency"] = self.vars["pay_currency"].get()
        rec["pay_amount"] = parse_amount(self.vars["pay_amount"].get())
        return rec

    def _save(self):
        try:
            rec = self._collect()
            if not rec.get("date"):
                raise ValueError("日期不能为空")
            database.save_supplier_settlement(rec)
            self.status.config(text="保存成功", foreground="green")
            self.refresh()
            self._new()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        self.current_id = None
        self.vars["date"].set(date_iso(datetime.date.today()))
        for k in ("partner_name", "summary", "doc_number", "notes"):
            self.vars[k].set("")
        self.vars["supply_amount_ves"].set("0")
        self.vars["pay_amount"].set("0")
        self.vars["pay_method"].set(config.PAY_METHOD_CARD)
        self.vars["pay_currency"].set(config.PAY_CURRENCY_BS)
        self.vars["store"].set(self._store_default())
        self.tree.selection_remove(self.tree.selection())
        self.status.config(text="", foreground="gray")

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一行", parent=self.frame)
            return
        if messagebox.askyesno("确认删除", "确定删除选中的记录？", parent=self.frame):
            database.delete_supplier_settlement(int(sel[0]))
            self.refresh()
            self._new()
