"""单据管理页：列出/筛选/删除单据。"""
import tkinter as tk
from tkinter import ttk, messagebox

from app import config
from app.db import database
from app.settings import load_settings
from app.utils import format_amount


class DocumentsPage:
    def __init__(self, app):
        self.app = app
        self.frame = None

    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}

        top = ttk.Frame(f)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="方向：").pack(side="left")
        self.dir_var = tk.StringVar(value="")
        cb = ttk.Combobox(top, textvariable=self.dir_var, state="readonly", width=12,
                          values=["", "compra 进货", "venta 出货"])
        cb.pack(side="left", padx=4)
        ttk.Label(top, text="分店：").pack(side="left", padx=(12, 2))
        self.store_var = tk.StringVar(value="")
        self.store_cb = ttk.Combobox(top, textvariable=self.store_var, state="readonly",
                                     width=10, values=[""])
        self.store_cb.pack(side="left")
        ttk.Label(top, text="从日期：").pack(side="left", padx=(12, 2))
        self.from_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.from_var, width=11).pack(side="left")
        ttk.Label(top, text="至日期：").pack(side="left", padx=(8, 2))
        self.to_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.to_var, width=11).pack(side="left")
        ttk.Button(top, text="查询", command=self.refresh).pack(side="left", padx=10)
        ttk.Button(top, text="刷新", command=self.refresh).pack(side="left")

        # 第二行：编辑 / 审核操作
        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Button(bar, text="✎ 编辑选中", command=self._edit).pack(side="left")
        ttk.Button(bar, text="✔ 审核（确认出入库）",
                   command=self._review).pack(side="left", padx=6)
        ttk.Button(bar, text="↩ 取消审核",
                   command=self._unreview).pack(side="left")
        ttk.Button(bar, text="删除选中", command=self._delete).pack(side="left", padx=6)
        self.pending_var = tk.IntVar(value=0)
        ttk.Checkbutton(bar, text="仅看待审核", variable=self.pending_var,
                        command=self.refresh).pack(side="left", padx=12)

        cols = ("id", "reviewed", "direction", "doc_number", "date", "store",
                "partner", "currency", "base", "iva", "total")
        heads = {"id": "ID", "reviewed": "状态", "direction": "方向",
                 "doc_number": "单据号", "date": "日期", "store": "分店",
                 "partner": "供应商/客户", "currency": "币种", "base": "Base",
                 "iva": "IVA", "total": "Total"}
        widths = {"id": 50, "reviewed": 70, "direction": 60, "doc_number": 110,
                  "date": 90, "store": 70, "partner": 180, "currency": 110,
                  "base": 100, "iva": 90, "total": 110}
        self.tree = ttk.Treeview(f, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="e" if c in (
                "base", "iva", "total") else "w")
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("pending", foreground="#b3541e")
        self.tree.pack(fill="both", expand=True, padx=14, pady=8)
        self.tree.bind("<Double-1>", self._show_detail)

        self.status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.status_var, foreground="#1f6feb",
                  font=("Microsoft YaHei UI", 9)).pack(fill="x", padx=14, pady=(0, 10))
        self.refresh()

    def _direction(self):
        raw = self.dir_var.get()
        if "compra" in raw:
            return "compra"
        if "venta" in raw:
            return "venta"
        return ""

    def refresh(self):
        if not hasattr(self, "tree"):
            return
        direction = self._direction()
        d_from = self.from_var.get().strip() or None
        d_to = self.to_var.get().strip() or None
        store = self.store_var.get().strip() or None
        # 刷新分店下拉：设置默认 + 数据库已出现分店
        stores = list((load_settings().get("stores") or config.DEFAULT_STORES))
        for st in database.list_stores():
            if st and st not in stores:
                stores.append(st)
        cur_store = self.store_var.get()
        self.store_cb["values"] = [""] + stores
        self.store_var.set(cur_store if cur_store in stores else "")

        docs = database.list_documents(direction=direction, date_from=d_from,
                                       date_to=d_to, store=store)
        pending_cnt = sum(1 for d in docs if not d.get("reviewed"))
        only_pending = bool(getattr(self, "pending_var", None)
                            and self.pending_var.get())
        if only_pending:
            docs = [d for d in docs if not d.get("reviewed")]
        self.tree.delete(*self.tree.get_children())
        for d in docs:
            direction_txt = "进货" if d["direction"] == "compra" else "出货"
            ok = bool(d.get("reviewed"))
            self.tree.insert("", "end", values=(
                d["id"], "已审核" if ok else "待审核", direction_txt,
                d["doc_number"] or "-", d["date"] or "-",
                d.get("store") or "-", d["partner_name"] or "-",
                config.currency_label(d.get("currency")) or d.get("currency") or "-",
                format_amount(d["base"], symbols=False),
                format_amount(d["iva_amount"], symbols=False),
                format_amount(d["total"], symbols=False)),
                tags=("ok" if ok else "pending",))
        self.status_var.set(f"共 {len(docs)} 张单据    待审核 {pending_cnt} 张")

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的单据。", parent=self.frame)
            return
        if not messagebox.askyesno("确认", "确定删除选中的单据吗？此操作不可撤销。",
                                   parent=self.frame):
            return
        for item in sel:
            doc_id = self.tree.item(item, "values")[0]
            database.delete_document(int(doc_id))
        self.refresh()

    # ------------------------------------------------------------ 编辑 / 审核

    @staticmethod
    def _num(v, default=0.0) -> float:
        """把界面输入（允许逗号小数点）安全转为 float。"""
        try:
            s = str(v).strip().replace(",", ".")
            return float(s) if s else default
        except (TypeError, ValueError):
            return default

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

    def _edit(self):
        doc_id = self._selected_id()
        if not doc_id:
            messagebox.showwarning("提示", "请先选择要编辑的单据。", parent=self.frame)
            return
        doc = database.get_document(doc_id)
        if not doc:
            messagebox.showerror("错误", "单据不存在或已被删除。", parent=self.frame)
            return
        self._open_editor(doc_id, doc)

    def _review(self):
        doc_id = self._selected_id()
        if not doc_id:
            messagebox.showwarning("提示", "请先选择要审核的单据。", parent=self.frame)
            return
        if not messagebox.askyesno(
                "审核确认",
                f"确认单据 #{doc_id} 已完成出入库吗？\n"
                "审核后该单据的库存将按行项目记账（已记账的不会重复计入）。",
                parent=self.frame):
            return
        if database.set_document_reviewed(doc_id, True):
            self.refresh()
            messagebox.showinfo("完成", f"单据 #{doc_id} 已审核，出入库已确认。",
                                parent=self.frame)
        else:
            messagebox.showerror("错误", "审核失败，单据可能已被删除。", parent=self.frame)

    def _unreview(self):
        doc_id = self._selected_id()
        if not doc_id:
            messagebox.showwarning("提示", "请先选择要取消审核的单据。", parent=self.frame)
            return
        if not messagebox.askyesno(
                "取消审核",
                f"取消单据 #{doc_id} 的审核？\n该单据产生的库存变动将被撤销。",
                parent=self.frame):
            return
        if database.set_document_reviewed(doc_id, False):
            self.refresh()
            messagebox.showinfo("完成", f"单据 #{doc_id} 已取消审核，库存变动已撤销。",
                                parent=self.frame)
        else:
            messagebox.showerror("错误", "操作失败，单据可能已被删除。", parent=self.frame)

    def _item_dialog(self, parent, it: dict, on_ok):
        """单行项目编辑对话框：直接修改传入的 it 字典。"""
        win = tk.Toplevel(parent)
        win.title("编辑行项目")
        win.geometry("430x320")
        win.transient(parent)
        win.grab_set()

        fields = [
            ("商品编码 (SKU)", "code"), ("描述", "desc"), ("数量", "qty"),
            ("单位", "um"), ("单价", "unit_price"), ("折扣 %", "discount"),
            ("Importe 金额", "amount"), ("单位成本", "cost_unit"),
        ]
        vars_ = {}
        for r, (label, key) in enumerate(fields):
            ttk.Label(win, text=label + "：").grid(row=r, column=0, sticky="w",
                                                   padx=12, pady=5)
            sv = tk.StringVar(value=str(it.get(key) if it.get(key) is not None else ""))
            ttk.Entry(win, textvariable=sv, width=28).grid(row=r, column=1, sticky="w")
            vars_[key] = sv

        def ok():
            qty = self._num(vars_["qty"].get(), 1)
            price = self._num(vars_["unit_price"].get())
            disc = self._num(vars_["discount"].get())
            raw_amount = vars_["amount"].get().strip()
            amount = self._num(raw_amount) if raw_amount else qty * price
            it["code"] = vars_["code"].get().strip()
            it["desc"] = vars_["desc"].get().strip()
            it["qty"] = qty
            it["um"] = vars_["um"].get().strip()
            it["unit_price"] = price
            it["discount"] = disc
            it["amount"] = round(amount, 2)
            it["neto"] = round(amount * (1 - disc / 100.0) if disc else amount, 2)
            it["cost_unit"] = self._num(vars_["cost_unit"].get())
            win.destroy()
            on_ok()

        ttk.Button(win, text="取消", command=win.destroy).grid(
            row=len(fields), column=0, sticky="e", pady=12)
        ttk.Button(win, text="确定", command=ok).grid(
            row=len(fields), column=1, sticky="e", pady=12)

    def _open_editor(self, doc_id: int, doc: dict):
        """单据再编辑窗口：修改表头字段与行项目，保存后重算库存。"""
        win = tk.Toplevel(self.frame)
        win.title(f"编辑单据 #{doc_id}")
        win.geometry("920x660")
        win.transient(self.frame)
        win.grab_set()

        v = {
            "doc_type": tk.StringVar(value=doc.get("doc_type") or "FACTURA"),
            "direction": tk.StringVar(value=doc.get("direction") or "compra"),
            "doc_number": tk.StringVar(value=doc.get("doc_number") or ""),
            "date": tk.StringVar(value=doc.get("date") or ""),
            "store": tk.StringVar(value=doc.get("store") or ""),
            "partner": tk.StringVar(value=doc.get("partner_name") or ""),
            "tax_id": tk.StringVar(value=doc.get("tax_id") or ""),
            "currency": tk.StringVar(
                value=config.currency_label(doc.get("currency"))),
            "exchange_rate": tk.StringVar(value=str(doc.get("exchange_rate") or "")),
            "iva_rate": tk.StringVar(value=str(doc.get("iva_rate") or 0)),
            "base": tk.StringVar(value=str(doc.get("base") or 0)),
            "iva_amount": tk.StringVar(value=str(doc.get("iva_amount") or 0)),
            "total": tk.StringVar(value=str(doc.get("total") or 0)),
        }

        form = ttk.Frame(win)
        form.pack(fill="x", padx=12, pady=10)
        stores = list((load_settings().get("stores") or config.DEFAULT_STORES))
        for st in database.list_stores():
            if st and st not in stores:
                stores.append(st)

        ttk.Label(form, text="方向：").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(form, textvariable=v["direction"], state="readonly", width=9,
                     values=["compra", "venta"]).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text=" 类型：").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=v["doc_type"], width=12).grid(row=0, column=3, sticky="w")
        ttk.Label(form, text=" 单据号：").grid(row=0, column=4, sticky="w")
        ttk.Entry(form, textvariable=v["doc_number"], width=16).grid(row=0, column=5, sticky="w")

        ttk.Label(form, text="日期：").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=v["date"], width=12).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text=" 分店：").grid(row=1, column=2, sticky="w")
        ttk.Combobox(form, textvariable=v["store"], width=9,
                     values=[""] + stores).grid(row=1, column=3, sticky="w")
        ttk.Label(form, text=" 币种：").grid(row=1, column=4, sticky="w")
        ttk.Combobox(form, textvariable=v["currency"], width=16,
                     values=[""] + [config.currency_label(c)
                                    for c in config.CURRENCY_CODES]).grid(
            row=1, column=5, sticky="w")

        ttk.Label(form, text="往来单位：").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=v["partner"], width=30).grid(
            row=2, column=1, columnspan=3, sticky="w")
        ttk.Label(form, text=" NIF：").grid(row=2, column=4, sticky="w")
        ttk.Entry(form, textvariable=v["tax_id"], width=16).grid(row=2, column=5, sticky="w")

        ttk.Label(form, text="汇率：").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=v["exchange_rate"], width=12).grid(row=3, column=1, sticky="w")
        ttk.Label(form, text=" IVA%：").grid(row=3, column=2, sticky="w")
        ttk.Entry(form, textvariable=v["iva_rate"], width=8).grid(row=3, column=3, sticky="w")
        ttk.Label(form, text=" Base：").grid(row=3, column=4, sticky="w")
        ttk.Entry(form, textvariable=v["base"], width=13).grid(row=3, column=5, sticky="w")

        ttk.Label(form, text="IVA 额：").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=v["iva_amount"], width=12).grid(row=4, column=1, sticky="w")
        ttk.Label(form, text=" Total：").grid(row=4, column=2, sticky="w")
        ttk.Entry(form, textvariable=v["total"], width=13).grid(row=4, column=3, sticky="w")

        ttk.Label(win, text="行项目（双击行编辑）",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=12)
        icols = ("code", "desc", "qty", "um", "price", "disc", "amount", "neto")
        iheads = {"code": "编码", "desc": "描述", "qty": "数量", "um": "单位",
                  "price": "单价", "disc": "折扣%", "amount": "Importe", "neto": "Neto"}
        iwidths = {"code": 90, "desc": 230, "qty": 65, "um": 50,
                   "price": 85, "disc": 60, "amount": 95, "neto": 95}
        itree = ttk.Treeview(win, columns=icols, show="headings", height=10)
        for c in icols:
            itree.heading(c, text=iheads[c])
            itree.column(c, width=iwidths[c],
                         anchor="e" if c in ("qty", "price", "disc", "amount", "neto") else "w")
        itree.pack(fill="both", expand=True, padx=12, pady=4)

        items = [dict(it) for it in (doc.get("items") or [])]

        def fill_items():
            itree.delete(*itree.get_children())
            for it in items:
                itree.insert("", "end", values=(
                    it.get("code", ""), it.get("desc", ""), it.get("qty", 1),
                    it.get("um", ""),
                    format_amount(it.get("unit_price", 0), symbols=False),
                    it.get("discount", 0) or 0,
                    format_amount(it.get("amount", 0), symbols=False),
                    format_amount(it.get("neto", 0) or 0, symbols=False)))
        fill_items()

        def edit_row(event=None):
            sel = itree.selection()
            if not sel:
                return
            self._item_dialog(win, items[itree.index(sel[0])], fill_items)
        itree.bind("<Double-1>", edit_row)

        def add_row():
            items.append({"code": "", "desc": "", "qty": 1, "um": "",
                          "unit_price": 0, "amount": 0, "discount": 0,
                          "neto": 0, "cost_unit": 0})
            fill_items()
            self._item_dialog(win, items[-1], fill_items)

        def del_row():
            sel = itree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选择要删除的行。", parent=win)
                return
            items.pop(itree.index(sel[0]))
            fill_items()

        def recalc():
            base = 0.0
            for it in items:
                qty = self._num(it.get("qty"), 1)
                price = self._num(it.get("unit_price"))
                disc = self._num(it.get("discount"))
                amount = qty * price
                neto = amount * (1 - disc / 100.0) if disc else amount
                it["amount"] = round(amount, 2)
                it["neto"] = round(neto, 2)
                base += neto
            rate = self._num(v["iva_rate"].get())
            iva = base * rate / 100.0
            v["base"].set(f"{base:.2f}")
            v["iva_amount"].set(f"{iva:.2f}")
            v["total"].set(f"{base + iva:.2f}")
            fill_items()

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=12, pady=4)
        ttk.Button(bar, text="+ 添加行", command=add_row).pack(side="left")
        ttk.Button(bar, text="- 删除行", command=del_row).pack(side="left", padx=6)
        ttk.Button(bar, text="编辑选中行", command=edit_row).pack(side="left")
        ttk.Button(bar, text="按行项目重算合计", command=recalc).pack(side="left", padx=12)

        def save():
            for it in items:
                it["qty"] = self._num(it.get("qty"), 1)
                it["unit_price"] = self._num(it.get("unit_price"))
                it["discount"] = self._num(it.get("discount"))
                it["amount"] = self._num(it.get("amount"))
                it["neto"] = self._num(it.get("neto")) or it["amount"]
                it["cost_unit"] = self._num(it.get("cost_unit"))
            payload = {
                "doc_type": v["doc_type"].get().strip(),
                "direction": v["direction"].get().strip(),
                "doc_number": v["doc_number"].get().strip(),
                "date": v["date"].get().strip(),
                "store": v["store"].get().strip(),
                "partner": v["partner"].get().strip(),
                "tax_id": v["tax_id"].get().strip(),
                "currency": config.currency_code(v["currency"].get()),
                "exchange_rate": self._num(v["exchange_rate"].get()),
                "iva_rate": self._num(v["iva_rate"].get()),
                "base": self._num(v["base"].get()),
                "iva_amount": self._num(v["iva_amount"].get()),
                "total": self._num(v["total"].get()),
                "items": items,
            }
            if not payload["date"]:
                messagebox.showwarning("提示", "请填写日期（YYYY-MM-DD）。", parent=win)
                return
            if database.update_document(doc_id, payload):
                win.destroy()
                self.refresh()
                messagebox.showinfo("完成", f"单据 #{doc_id} 已保存，库存已按新内容重算。",
                                    parent=self.frame)
            else:
                messagebox.showerror("错误", "保存失败，单据可能已被删除。", parent=win)

        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=12, pady=10)
        ttk.Button(bottom, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bottom, text="保存", command=save).pack(side="right", padx=8)

    @staticmethod
    def _doc_type_label(t):
        return {"Compra": "进货单 Compra", "Venta": "出库单 Venta"}.get(t, t)

    def _show_detail(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        doc_id = int(self.tree.item(sel[0], "values")[0])
        doc = database.get_document(doc_id)
        if not doc:
            return
        win = tk.Toplevel(self.frame)
        win.title(f"单据 #{doc_id} 详情")
        win.geometry("720x560")
        txt = tk.Text(win, font=("Microsoft YaHei UI", 10))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        cur = doc.get("currency") or "-"
        er = doc.get("exchange_rate") or 0.0
        info = [
            f"方向: {'进货 Compra' if doc['direction']=='compra' else '出货 Venta'}",
            f"类型: {self._doc_type_label(doc['doc_type'])}    单据号: {doc['doc_number']}"
            + (f"    分店: {doc.get('store') or '-'}" if doc.get("store") else ""),
            f"日期: {doc['date']}",
            f"供应商/客户: {doc['partner_name']}    NIF: {doc['tax_id']}",
            f"币种: {config.currency_label(cur) or cur}" + (
                f"    单据汇率(1 USD = X): {format_amount(er, symbols=False)}"
                if er else ""),
            f"Base: {format_amount(doc['base'], symbols=False)}"
            f"    IVA {doc['iva_rate']}%: "
            f"{format_amount(doc['iva_amount'], symbols=False)}",
            f"Total: {format_amount(doc['total'], symbols=False)}",
            "",
            "---- 行项目 ----",
        ]
        for it in doc["items"]:
            code = it.get("code", "")
            um = it.get("um", "")
            neto = it.get("neto", 0) or 0
            line = f"{code + ' ' if code else ''}{it['description']}  x{it['qty']}"
            if um:
                line += f" {um}"
            line += (f"  单价 {format_amount(it['unit_price'], symbols=False)}  "
                     f"Importe {format_amount(it['amount'], symbols=False)}")
            if neto:
                line += f"  Neto {format_amount(neto, symbols=False)}"
            info.append(line)
        info += ["", "---- OCR 原文 ----", doc["raw_text"] or "(无)"]
        txt.insert("1.0", "\n".join(info))
        txt.config(state="disabled")
