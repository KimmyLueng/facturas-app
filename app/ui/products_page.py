"""商品库存管理页：商品主档 CRUD、库存预警、手动盘点和从单据重建库存。"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app import config
from app.db import database
from app.utils import (format_amount, format_base_amount, parse_amount,
                       date_iso)


class ProductsPage:
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
        list_frame = ttk.LabelFrame(f, text="商品库存", padding=10)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        cols = (
            ("code", "编码", 90),
            ("barcode", "条码", 100),
            ("name", "名称", 180),
            ("category", "分类", 90),
            ("unit", "单位", 50),
            ("cost_price", "成本", 80),
            ("sale_price", "售价", 80),
            ("stock_qty", "库存", 80),
            ("min_stock", "下限", 70),
            ("supplier", "供应商", 100),
        )
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols],
                                 show="headings", height=12)
        self.tree.tag_configure("low", foreground="#c0392b")
        for key, text, width in cols:
            anchor = "e" if key in ("cost_price", "sale_price", "stock_qty",
                                    "min_stock") else "w"
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # 列表工具条
        tool = ttk.Frame(list_frame)
        tool.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(tool, text="盘点/调整库存", command=self._adjust).pack(
            side="left", padx=4)
        ttk.Button(tool, text="从单据重建库存", command=self._rebuild).pack(
            side="left", padx=4)
        ttk.Button(tool, text="只看预警", command=self._only_low).pack(
            side="left", padx=4)

        # -------------------------------------------------------- 编辑表单
        form = ttk.LabelFrame(f, text="录入 / 编辑商品", padding=10)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        layout = [
            ("code", "编码 SKU*"), ("barcode", "条码"), ("name", "名称*"),
            ("category", "分类"), ("unit", "单位"), ("supplier", "供应商"),
            ("cost_price", "成本价"), ("sale_price", "售价"),
            ("stock_qty", "当前库存"), ("min_stock", "库存下限"),
        ]
        for i, (key, label) in enumerate(layout):
            r, c = divmod(i, 2)
            r = r * 2
            ttk.Label(form, text=label).grid(row=r, column=c * 3, sticky="w",
                                             pady=3, padx=(0 if c == 0 else 16, 0))
            self.vars[key] = tk.StringVar()
            ttk.Entry(form, textvariable=self.vars[key], width=22).grid(
                row=r, column=c * 3 + 1, columnspan=2, sticky="we", padx=8, pady=3)

        self.vars["notes"] = tk.StringVar()
        ttk.Label(form, text="备注").grid(row=10, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.vars["notes"], width=22).grid(
            row=10, column=1, columnspan=2, sticky="we", padx=8, pady=3)

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=11, column=0, columnspan=6, sticky="w", pady=8)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="新增", command=self._new).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="删除选中", command=self._delete).pack(
            side="left", padx=4)

        self.status = ttk.Label(form, text="", foreground="gray")
        self.status.grid(row=12, column=0, columnspan=6, sticky="w")

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for p in database.list_products():
            low = p["min_stock"] > 0 and p["stock_qty"] < p["min_stock"]
            self.tree.insert("", "end", iid=str(p["id"]),
                             tags=("low",) if low else (),
                             values=(
                                 p["code"] or "-", p["barcode"] or "-",
                                 p["name"], p["category"] or "-",
                                 p["unit"] or "-",
                                 format_base_amount(p["cost_price"]),
                                 format_base_amount(p["sale_price"]),
                                 format_amount(p["stock_qty"], symbols=False),
                                 format_amount(p["min_stock"], symbols=False),
                                 p["supplier"] or "-",
                             ))

    def _only_low(self):
        self.tree.delete(*self.tree.get_children())
        for p in database.low_stock_products():
            self.tree.insert("", "end", iid=str(p["id"]), tags=("low",),
                             values=(
                                 p["code"] or "-", p["barcode"] or "-",
                                 p["name"], p["category"] or "-",
                                 p["unit"] or "-",
                                 format_base_amount(p["cost_price"]),
                                 format_base_amount(p["sale_price"]),
                                 format_amount(p["stock_qty"], symbols=False),
                                 format_amount(p["min_stock"], symbols=False),
                                 p["supplier"] or "-",
                             ))
        self.status.config(text=f"低库存商品 {len(database.low_stock_products())} 件",
                           foreground="#c0392b")

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        p = database.get_product(int(sel[0]))
        if not p:
            return
        self.current_id = p["id"]
        for key in ("code", "barcode", "name", "category", "unit", "supplier",
                    "notes"):
            self.vars[key].set(p.get(key) or "")
        for key in ("cost_price", "sale_price", "stock_qty", "min_stock"):
            self.vars[key].set(self._fmt_num(p.get(key)))
        self.status.config(text="", foreground="gray")

    @staticmethod
    def _fmt_num(v):
        return f"{float(v or 0):.2f}" if v not in (None, "", 0, 0.0) else "0"

    def _collect(self) -> dict:
        rec = {"id": self.current_id}
        for key in ("code", "barcode", "name", "category", "unit", "supplier",
                    "notes"):
            rec[key] = self.vars[key].get().strip()
        for key in ("cost_price", "sale_price", "stock_qty", "min_stock"):
            rec[key] = parse_amount(self.vars[key].get())
        return rec

    def _save(self):
        try:
            rec = self._collect()
            if not rec.get("name"):
                raise ValueError("名称不能为空")
            if not rec.get("code"):
                raise ValueError("商品编码 SKU 不能为空（用于匹配进货/出货单据）")
            database.save_product(rec)
            self.status.config(text="保存成功", foreground="green")
            self.refresh()
            self._new()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    def _new(self):
        self.current_id = None
        for key in ("code", "barcode", "name", "category", "unit", "supplier",
                    "notes"):
            self.vars[key].set("")
        for key in ("cost_price", "sale_price", "stock_qty", "min_stock"):
            self.vars[key].set("0")
        self.tree.selection_remove(self.tree.selection())
        self.status.config(text="", foreground="gray")

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一行", parent=self.frame)
            return
        if messagebox.askyesno("确认删除", "确定删除选中的商品？\n"
                               "（其库存流水将一并删除，已关联单据不回溯）",
                               parent=self.frame):
            database.delete_product(int(sel[0]))
            self.refresh()
            self._new()

    def _adjust(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先在列表选择要调整的商品",
                                    parent=self.frame)
            return
        pid = int(sel[0])
        p = database.get_product(pid)
        if not p:
            return
        win = tk.Toplevel(self.frame)
        win.title(f"盘点调整：{p['name']}")
        win.geometry("360x200")
        win.transient(self.frame)
        win.grab_set()

        ttk.Label(win, text=f"当前库存："
                            f"{format_amount(p['stock_qty'], symbols=False)}").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        ttk.Label(win, text="变动量（正=入库，负=出库）：").grid(
            row=1, column=0, sticky="w", padx=12, pady=4)
        delta_var = tk.StringVar(value="0")
        ttk.Entry(win, textvariable=delta_var, width=16).grid(
            row=1, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(win, text="说明：").grid(row=2, column=0, sticky="w",
                                         padx=12, pady=4)
        note_var = tk.StringVar()
        ttk.Entry(win, textvariable=note_var, width=28).grid(
            row=2, column=1, sticky="w", padx=8, pady=4)

        def confirm():
            try:
                qty = parse_amount(delta_var.get())
                if qty == 0:
                    raise ValueError("变动量不能为 0")
                database.apply_stock_change(pid, qty, "ajuste", note=note_var.get(),
                                            date=date_iso(datetime.date.today()))
                self.refresh()
                win.destroy()
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("调整失败", str(e), parent=win)

        ttk.Button(win, text="确定", command=confirm).grid(
            row=3, column=0, columnspan=2, pady=12)

    def _rebuild(self):
        if not messagebox.askyesno(
                "从单据重建库存",
                "将清空全部库存流水，并依据所有进货(入库)/出货(出库)单据按商品编码"
                "重新计算库存。\n确定继续？", parent=self.frame):
            return
        try:
            res = database.rebuild_stock_from_documents()
            self.status.config(
                text=f"重建完成：命中 {res['products']} 个商品，"
                     f"重记 {res['moves']} 条流水", foreground="green")
            self.refresh()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("重建失败", str(e), parent=self.frame)
