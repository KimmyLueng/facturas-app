"""扫描导入页：选择图片/PDF → OCR → 编辑字段 → 入库。"""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from app import config
from app.ocr import OCREngine, pdf_to_images, parse_document
from app.db import database
from app.settings import add_store, load_settings
from app.utils import parse_amount, parse_date, date_iso


class ScanPage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.files = []            # 待处理文件
        self.current_doc = None    # 解析结果
        self.items = []            # 行项目 list[dict]
        self._busy = False
        self._edit_index = None    # 正在编辑的行索引（None 表示新增模式）
        self._amount_manual = False  # 金额是否被手动修改过
        self._neto_manual = False    # 净额是否被手动修改过
        self._edit_entry = None    # 表格内联编辑输入框
        self._edit_row = None
        self._edit_col = None
        self._edit_old = ""

    # ------------------------------------------------------------ 构建
    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}

        # 顶部：文件选择
        top = ttk.LabelFrame(f, text="1. 选择扫描文件（图片 JPG/PNG 或 PDF）")
        top.pack(fill="x", **pad)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Button(row, text="选择文件…", command=self._pick_files).pack(side="left")
        ttk.Button(row, text="清空", command=self._clear_files).pack(side="left", padx=6)
        self.file_var = tk.StringVar(value="未选择文件")
        ttk.Label(row, textvariable=self.file_var, foreground="#444").pack(side="left", padx=8)

        # 方向 + 识别
        dirrow = ttk.Frame(top)
        dirrow.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(dirrow, text="单据方向：").pack(side="left")
        self.dir_var = tk.StringVar(value="auto")
        ttk.Radiobutton(dirrow, text="自动识别", value="auto",
                        variable=self.dir_var).pack(side="left", padx=4)
        ttk.Radiobutton(dirrow, text="进货（Compra）", value="compra",
                        variable=self.dir_var).pack(side="left", padx=4)
        ttk.Radiobutton(dirrow, text="出货（Venta）", value="venta",
                        variable=self.dir_var).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(dirrow, text="🔍 扫描识别", command=self._run_ocr)
        self.scan_btn.pack(side="left", padx=(20, 0))

        # 中部：字段 + 行项目 + 原文
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, **pad)

        # 左：字段表单
        left = ttk.LabelFrame(mid, text="2. 识别结果（可修改后入库）")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        form = ttk.Frame(left)
        form.pack(fill="x", padx=10, pady=10)
        self.vars = {}
        labels = [
            ("doc_number", "Factura No. / 单据号"),
            ("date", "Fecha / 日期"),
            ("partner", "Proveedor / 供应商"),
            ("tax_id", "RIF / 税号"),
        ]
        for i, (key, label) in enumerate(labels):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3)
            v = tk.StringVar()
            e = ttk.Entry(form, textvariable=v, width=30)
            e.grid(row=i, column=1, sticky="we", padx=8, pady=3)
            self.vars[key] = v

        # 单据类型：下拉选择进货单/出库单（选择时自动同步单据方向）
        i = len(labels)
        ttk.Label(form, text="单据类型").grid(row=i, column=0, sticky="w", pady=3)
        self.vars["doc_type"] = tk.StringVar()
        self.doc_type_cb = ttk.Combobox(
            form, textvariable=self.vars["doc_type"], width=28,
            values=["", "进货单 Compra", "出库单 Venta"])
        self.doc_type_cb.grid(row=i, column=1, sticky="we", padx=8, pady=3)
        self.doc_type_cb.bind("<<ComboboxSelected>>", self._on_doc_type_selected)

        # 金额行
        money_keys = [("base", "Base Imponible\n不含税基数"), ("iva_rate", "IVA %\n税率"),
                      ("iva_amount", "IVA Amount\n税额"), ("total", "Total USD\n合计")]
        for i, (key, label) in enumerate(money_keys):
            r = i + len(labels)
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar()
            e = ttk.Entry(form, textvariable=v, width=14)
            e.grid(row=r, column=1, sticky="we", padx=8, pady=3)
            self.vars[key] = v

        # 币种 + 单据汇率行
        r = len(labels) + len(money_keys)
        ttk.Label(form, text="Moneda / 币种").grid(row=r, column=0, sticky="w", pady=3)
        self.vars["currency"] = tk.StringVar()
        cb = ttk.Combobox(form, textvariable=self.vars["currency"], width=16,
                          values=[""] + [config.currency_label(c)
                                         for c in ("USD", "Bs", "CNY", "USDT")])
        cb.grid(row=r, column=1, sticky="we", padx=8, pady=3)

        r2 = r + 1
        ttk.Label(form, text="Tipo de Cambio BCV\n汇率（1 USD = X Bs）").grid(
            row=r2, column=0, sticky="w", pady=3)
        self.vars["exchange_rate"] = tk.StringVar()
        e2 = ttk.Entry(form, textvariable=self.vars["exchange_rate"], width=14)
        e2.grid(row=r2, column=1, sticky="we", padx=8, pady=3)

        # 入库分店（Sucursal）：默认取设置里的分店列表 + 单据中已出现过的分店
        r3 = r2 + 1
        ttk.Label(form, text="Sucursal\n入库分店").grid(
            row=r3, column=0, sticky="w", pady=3)
        self._stores = self._collect_store_options()
        self.vars["store"] = tk.StringVar(value=self._stores[0] if self._stores else "")
        cb3 = ttk.Combobox(form, textvariable=self.vars["store"], width=14,
                           values=[""] + self._stores)
        cb3.grid(row=r3, column=1, sticky="we", padx=8, pady=3)
        self.store_cb = cb3
        ttk.Button(form, text="＋ 添加分店", width=10,
                   command=self._add_store_dialog).grid(
            row=r3, column=2, sticky="w", padx=(0, 4), pady=3)

        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(left)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="💾 确认入库", command=self._save).pack(side="left")
        ttk.Button(btns, text="自动推算金额",
                   command=self._auto_fill).pack(side="left", padx=6)
        ttk.Button(btns, text="汇总行项目金额", command=self._sum_items).pack(side="left", padx=6)

        # 中：行项目（Excel 式表格）
        center = ttk.LabelFrame(mid, text="3. 行项目（Artículos）")
        center.pack(side="left", fill="both", expand=True, padx=8)
        cols = ("code", "desc", "price", "qty", "um", "amount", "discount", "neto")
        heads = {
            "code": "Código\n商品编码",
            "desc": "Descripción / 商品名称",
            "price": "Precio Unitario\n单价",
            "qty": "Cantidad\n数量",
            "um": "U/M\n单位",
            "amount": "Importe\n金额",
            "discount": "Dscto %\n折扣%",
            "neto": "Neto\n净额",
        }
        widths = {"code": 75, "desc": 180, "price": 90, "qty": 60,
                  "um": 55, "amount": 85, "discount": 70, "neto": 85}
        anchors = {"code": "w", "desc": "w", "price": "e", "qty": "e",
                   "um": "center", "amount": "e", "discount": "e", "neto": "e"}
        self.tree = ttk.Treeview(center, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # 行项目编辑输入框（与表格同列序）
        self.it_cols = cols
        self.it_heads = heads
        itrow = ttk.Frame(center)
        itrow.pack(fill="x", padx=8, pady=4)
        self.it_vars = {}
        self.it_entries = {}
        fields = (("code", "编码", 8), ("desc", "商品名称", 18),
                  ("price", "单价", 9), ("qty", "数量", 7),
                  ("um", "单位", 6), ("amount", "金额", 9),
                  ("discount", "折扣%", 7), ("neto", "净额", 9))
        for key, label, w in fields:
            ttk.Label(itrow, text=label).pack(side="left", padx=(4, 2))
            v = tk.StringVar()
            e = ttk.Entry(itrow, textvariable=v, width=w)
            e.pack(side="left", padx=(0, 6))
            self.it_vars[key] = v
            self.it_entries[key] = e
        # 数量/单价/折扣变化时自动重算金额、净额（净额 = 金额 × (1 - 折扣%)）
        self.it_entries["qty"].bind("<KeyRelease>", self._on_qty_price_change)
        self.it_entries["price"].bind("<KeyRelease>", self._on_qty_price_change)
        self.it_entries["discount"].bind("<KeyRelease>", self._on_discount_change)
        self.it_entries["amount"].bind("<KeyRelease>", self._on_amount_typed)
        self.it_entries["neto"].bind("<KeyRelease>", self._on_neto_typed)
        self.it_add_btn = ttk.Button(itrow, text="保存", command=self._add_item)
        self.it_add_btn.pack(side="left", padx=(8, 0))
        ttk.Button(itrow, text="删除选中", command=self._del_item).pack(side="left", padx=6)
        ttk.Button(itrow, text="取消编辑", command=self._cancel_edit).pack(side="left", padx=6)

        # 右：OCR 原文
        right = ttk.LabelFrame(mid, text="OCR 原文")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.raw_text = tk.Text(right, height=12, width=38, font=("Consolas", 9))
        self.raw_text.pack(fill="both", expand=True, padx=8, pady=8)

        # 底部：状态
        self.status_var = tk.StringVar(value="就绪。请选择扫描文件。")
        ttk.Label(f, textvariable=self.status_var, foreground="#1f6feb",
                  font=("Microsoft YaHei UI", 9)).pack(fill="x", padx=14, pady=(0, 10))

    # ------------------------------------------------------------ 文件
    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="选择单据扫描件",
            filetypes=[("图片/PDF", "*.png *.jpg *.jpeg *.bmp *.pdf"),
                       ("图片", "*.png *.jpg *.jpeg *.bmp"),
                       ("PDF", "*.pdf")])
        if files:
            self.files = list(files)
            self.file_var.set("；".join(os.path.basename(x) for x in self.files[:3]) +
                              (f" 等 {len(self.files)} 个文件" if len(self.files) > 3 else ""))

    def _clear_files(self):
        self.files = []
        self.file_var.set("未选择文件")
        self.status_var.set("已清空文件列表。")

    # ------------------------------------------------------------ OCR
    def _run_ocr(self):
        if self._busy:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先选择扫描文件。", parent=self.frame)
            return
        self._busy = True
        self.scan_btn.state(["disabled"])
        self.status_var.set("正在 OCR 识别（首次运行需加载模型，请稍候）…")
        threading.Thread(target=self._ocr_worker, daemon=True).start()

    def _ocr_worker(self):
        try:
            engine = self.app.state.get_ocr_engine()
            all_lines = []
            for f in self.files:
                if f.lower().endswith(".pdf"):
                    imgs = pdf_to_images(f)
                    for img in imgs:
                        all_lines.extend(engine.recognize(img))
                else:
                    all_lines.extend(engine.recognize(f))
            doc = parse_document(all_lines)
            # 强制方向
            direction = self.dir_var.get()
            if direction != "auto":
                doc["direction"] = direction
            self.app.after(0, lambda: self._show_result(doc, all_lines))
        except Exception as e:  # noqa: BLE001
            self.app.after(0, lambda: self._show_ocr_error(str(e)))

    def _show_ocr_error(self, err):
        self._busy = False
        self.scan_btn.state(["!disabled"])
        self.status_var.set("OCR 失败。")
        messagebox.showerror("OCR 错误", err + "\n\n请检查是否已安装依赖（见 README）。",
                             parent=self.frame)

    def _show_result(self, doc, lines):
        self._busy = False
        self.scan_btn.state(["!disabled"])
        self.current_doc = doc
        self.items = list(doc.get("items", [])) or []

        self.vars["doc_number"].set(doc.get("doc_number", ""))
        self.vars["date"].set(date_iso(doc.get("date")))
        self.vars["partner"].set(doc.get("partner", ""))
        self.vars["tax_id"].set(doc.get("tax_id", ""))
        d_dir = doc.get("direction")
        if d_dir == "compra":
            self.vars["doc_type"].set("进货单 Compra")
        elif d_dir == "venta":
            self.vars["doc_type"].set("出库单 Venta")
        else:
            self.vars["doc_type"].set(doc.get("doc_type", ""))
        self.vars["base"].set(str(doc.get("base", 0.0) or 0.0))
        self.vars["iva_rate"].set(str(doc.get("iva_rate", 0.0) or 0.0))
        self.vars["iva_amount"].set(str(doc.get("iva_amount", 0.0) or 0.0))
        self.vars["total"].set(str(doc.get("total", 0.0) or 0.0))
        # 根据图片识别结果默认币种：USD
        self.vars["currency"].set(
            config.currency_label(doc.get("currency") or "USD"))
        er = doc.get("exchange_rate") or 0.0
        self.vars["exchange_rate"].set(str(er) if er else "")

        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", "\n".join(lines))

        direction_txt = {"compra": "进货", "venta": "出货"}.get(doc.get("direction"), "未识别")
        self.status_var.set(
            f"识别完成：{direction_txt} · 共 {len(lines)} 行文本 · 识别出 {len(self.items)} 个商品。"
            f"若未识别可在下方手工录入编码/名称/单价/数量/折扣%，点“保存”加入；也可双击表格单元格修改。")

        # 滚动到表单
        self._reload_items()

    # ------------------------------------------------------------ 单据类型
    def _on_doc_type_selected(self, event=None):
        t = self.vars["doc_type"].get()
        if t == "进货单 Compra":
            self.dir_var.set("compra")
        elif t == "出库单 Venta":
            self.dir_var.set("venta")
        self.status_var.set("已设置单据类型，核对后可直接入库。")

    # ------------------------------------------------------------ 行项目
    def _reload_items(self):
        self._close_cell_editor()
        self.tree.delete(*self.tree.get_children())
        for it in self.items:
            self.tree.insert("", "end", values=(
                it.get("code", ""), it.get("desc", ""),
                it.get("unit_price", 0), it.get("qty", 1),
                it.get("um", ""), it.get("amount", 0),
                it.get("discount", 0), it.get("neto", 0)))

    # ------------------------------------------------------------ 单元格内联编辑（Excel 式）
    def _on_tree_double_click(self, event):
        """双击：单元格 → 直接修改；行空白 → 加载到下方输入框。"""
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        if self.tree.identify("region", event.x, event.y) == "cell":
            col = self.tree.identify_column(event.x)
            col_idx = int(col.replace("#", "")) - 1
            self._start_cell_edit(row_id, col_idx)
        else:
            self._load_item(event)

    def _start_cell_edit(self, row_id, col_idx):
        self._close_cell_editor()
        bbox = self.tree.bbox(row_id, f"#{col_idx + 1}")
        if not bbox:
            return
        x, y, w, h = bbox
        old = self.tree.set(row_id, f"#{col_idx + 1}")
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, old)
        entry.select_range(0, "end")
        entry.focus_set()
        self._edit_entry = entry
        self._edit_row = row_id
        self._edit_col = col_idx
        self._edit_old = old
        entry.bind("<Return>", lambda e: self._commit_cell_edit())
        entry.bind("<FocusOut>", lambda e: self._commit_cell_edit())
        entry.bind("<Escape>", lambda e: self._cancel_cell_edit())

    def _commit_cell_edit(self):
        entry = self._edit_entry
        if entry is None:
            return
        row_id, col_idx, old_val = self._edit_row, self._edit_col, self._edit_old
        new_val = entry.get().strip()
        self._close_cell_editor()
        if row_id is None or new_val == old_val:
            return
        idx = self.tree.index(row_id)
        if not (0 <= idx < len(self.items)):
            return
        it = self.items[idx]
        labels = {
            "code": "商品编码", "desc": "商品名称", "price": "单价",
            "qty": "数量", "um": "单位", "amount": "金额",
            "discount": "折扣%", "neto": "净额"}
        key = self.it_cols[col_idx]
        if key in ("code", "desc", "um"):
            it[key] = new_val
        else:
            num = parse_amount(new_val)
            if key == "qty":
                it["qty"] = num
            elif key == "unit_price":
                it["unit_price"] = num
            elif key == "amount":
                it["amount"] = num
            elif key == "discount":
                it["discount"] = num
            elif key == "neto":
                it["neto"] = num
            # 数量/单价变化 → 重算金额；净额同步为 金额×(1-折扣%)（净额为空或改折扣时总是同步）
            if key in ("qty", "unit_price"):
                it["amount"] = round(it.get("qty", 0) * it.get("unit_price", 0), 2)
            if key in ("qty", "unit_price", "amount", "discount"):
                if not it.get("neto") or key == "discount":
                    dsc = it.get("discount", 0) or 0
                    it["neto"] = round(max(it.get("amount", 0) * (1 - dsc / 100), 0), 2)
        self._reload_items()
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self.status_var.set(
            f"✔ 已修改第 {idx + 1} 项“{labels[key]}”：{new_val}")

    def _cancel_cell_edit(self):
        self._close_cell_editor()
        self.status_var.set("已取消单元格编辑。")

    def _close_cell_editor(self):
        entry = self._edit_entry
        self._edit_entry = None
        self._edit_row = None
        self._edit_col = None
        self._edit_old = ""
        if entry is not None:
            try:
                entry.destroy()
            except tk.TclError:
                pass

    def _load_item(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        vals = self.tree.item(sel[0], "values")
        for key, val in zip(self.it_cols, vals):
            self.it_vars[key].set(val)
        self._edit_index = idx
        self._amount_manual = False
        self._neto_manual = False
        self.it_add_btn.config(text="保存修改")
        self.status_var.set(
            f"正在编辑第 {idx + 1} 项：修改下方输入框后点“保存修改”，或双击表格单元格直接改。")

    def _cancel_edit(self):
        self._edit_index = None
        self._amount_manual = False
        self._neto_manual = False
        self.it_add_btn.config(text="保存")
        for k in self.it_vars:
            self.it_vars[k].set("")
        self.status_var.set("已取消编辑，回到手工录入模式：填写编码/名称/单价/数量/折扣%后点“保存”。")

    def _on_qty_price_change(self, event=None):
        if self._amount_manual:
            return
        qty = parse_amount(self.it_vars["qty"].get())
        price = parse_amount(self.it_vars["price"].get())
        if qty > 0 and price > 0:
            amount = round(qty * price, 2)
            self.it_vars["amount"].set(str(amount))
            if not self._neto_manual:
                dsc = parse_amount(self.it_vars["discount"].get())
                neto = round(max(amount * (1 - dsc / 100), 0.0), 2)
                self.it_vars["neto"].set(str(neto))

    def _on_discount_change(self, event=None):
        """折扣%变化：净额 = 金额 × (1 - 折扣%)（金额为空时先按 数量×单价 推算）"""
        if self._neto_manual:
            return
        amount = parse_amount(self.it_vars["amount"].get())
        if amount <= 0:
            qty = parse_amount(self.it_vars["qty"].get())
            price = parse_amount(self.it_vars["price"].get())
            if qty > 0 and price > 0:
                amount = round(qty * price, 2)
        dsc = parse_amount(self.it_vars["discount"].get())
        neto = round(max(amount * (1 - dsc / 100), 0.0), 2)
        self.it_vars["neto"].set(str(neto))

    def _on_amount_typed(self, event=None):
        if self.it_vars["amount"].get().strip():
            self._amount_manual = True

    def _on_neto_typed(self, event=None):
        if self.it_vars["neto"].get().strip():
            self._neto_manual = True

    def _add_item(self):
        code = self.it_vars["code"].get().strip()
        desc = self.it_vars["desc"].get().strip()
        qty = parse_amount(self.it_vars["qty"].get())
        price = parse_amount(self.it_vars["price"].get())
        amount = parse_amount(self.it_vars["amount"].get())
        um = self.it_vars["um"].get().strip()
        discount = parse_amount(self.it_vars["discount"].get())
        neto = parse_amount(self.it_vars["neto"].get())
        if not desc:
            messagebox.showwarning("提示", "请输入商品名称。", parent=self.frame)
            return
        if amount <= 0 and qty > 0 and price > 0:
            amount = qty * price
        if neto <= 0:
            neto = max(amount * (1 - discount / 100), 0.0)
        item = {
            "code": code, "desc": desc, "qty": qty,
            "unit_price": price, "amount": amount,
            "um": um, "discount": discount, "neto": neto,
        }
        if self._edit_index is not None and 0 <= self._edit_index < len(self.items):
            self.items[self._edit_index] = item
            self.status_var.set(f"✔ 已更新第 {self._edit_index + 1} 项：{desc}。")
        else:
            self.items.append(item)
            self.status_var.set(f"✔ 已保存：{desc}。")
        self._edit_index = None
        self._amount_manual = False
        self._neto_manual = False
        self.it_add_btn.config(text="保存")
        self._reload_items()
        for k in self.it_vars:
            self.it_vars[k].set("")

    def _del_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        self.items.pop(idx)
        if self._edit_index is not None:
            self._edit_index = None
            self._amount_manual = False
            self._neto_manual = False
            self.it_add_btn.config(text="保存")
            for k in self.it_vars:
                self.it_vars[k].set("")
        self._reload_items()

    # ------------------------------------------------------------ 金额推算
    def _auto_fill(self):
        base = parse_amount(self.vars["base"].get())
        rate = parse_amount(self.vars["iva_rate"].get())
        iva = parse_amount(self.vars["iva_amount"].get())
        total = parse_amount(self.vars["total"].get())
        if base and rate and not iva:
            iva = round(base * rate / 100, 2)
            self.vars["iva_amount"].set(str(iva))
        if base and rate and not total:
            total = round(base + iva, 2)
            self.vars["total"].set(str(total))
        if total and not base:
            if rate:
                base = round(total / (1 + rate / 100), 2)
                iva = round(total - base, 2)
                self.vars["base"].set(str(base))
                self.vars["iva_amount"].set(str(iva))
        self.status_var.set("已按 IVA 税率推算缺失金额，请核对。")

    def _sum_items(self):
        s = sum(it.get("amount", 0) for it in self.items)
        net = sum(it.get("neto", 0) for it in self.items if it.get("neto", 0))
        self.vars["base"].set(str(round(s, 2)))
        self.vars["total"].set(str(round(net if net else s, 2)))
        self.status_var.set(
            f"已将行项目金额合计 {round(s, 2)} 填入 Base，净额合计 {round(net if net else s, 2)} 填入 Total。")

    # ------------------------------------------------------------ 保存
    def _save(self):
        self._commit_cell_edit()   # 先提交表格中未保存的单元格编辑
        dt_raw = self.vars["doc_type"].get().strip()
        dt_map = {"进货单 Compra": "Compra", "出库单 Venta": "Venta"}
        doc_type = dt_map.get(dt_raw, dt_raw or "FACTURA")
        direction = self.dir_var.get()
        if direction == "auto":
            if dt_raw == "进货单 Compra":
                direction = "compra"
            elif dt_raw == "出库单 Venta":
                direction = "venta"
            else:
                direction = (self.current_doc or {}).get("direction", "")
        doc = {
            "direction": direction,
            "doc_type": doc_type,
            "doc_number": self.vars["doc_number"].get().strip(),
            "date": parse_date(self.vars["date"].get()) or
                    (self.current_doc or {}).get("date"),
            "partner": self.vars["partner"].get().strip(),
            "tax_id": self.vars["tax_id"].get().strip(),
            "base": parse_amount(self.vars["base"].get()),
            "iva_rate": parse_amount(self.vars["iva_rate"].get()),
            "iva_amount": parse_amount(self.vars["iva_amount"].get()),
            "total": parse_amount(self.vars["total"].get()),
            "currency": config.currency_code(self.vars["currency"].get()),
            "exchange_rate": parse_amount(self.vars["exchange_rate"].get()),
            "store": self.vars["store"].get().strip(),
            "items": self.items,
            "raw_text": self.raw_text.get("1.0", "end").strip(),
            "source_file": "；".join(os.path.basename(x) for x in self.files),
        }
        if doc["direction"] not in ("compra", "venta"):
            messagebox.showwarning("提示", "无法确定单据方向，请选择“进货”或“出货”。",
                                   parent=self.frame)
            return
        if not doc["date"]:
            messagebox.showwarning("提示", "请填写日期（格式 2026-08-25 或 25/08/2026）。",
                                   parent=self.frame)
            return
        # 显示友好日期提示
        self.vars["date"].set(date_iso(doc["date"]))
        if doc["total"] <= 0 and doc["base"] <= 0:
            messagebox.showwarning("提示", "金额为 0，请核对 Base/Total 字段，或点击“汇总行项目金额”。",
                                   parent=self.frame)
            return
        try:
            doc_id = database.save_document(doc)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)
            return
        self.status_var.set(f"✔ 已入库（单据 #{doc_id}）。可继续扫描下一张。")
        self.current_doc = None
        self._clear_form_keep_files()

    def _clear_form_keep_files(self):
        self._close_cell_editor()
        keep_store = self.vars.get("store") and self.vars["store"].get()
        for v in self.vars.values():
            v.set("")
        if "store" in self.vars:   # 清空后恢复默认分店，便于连续入库
            default = (getattr(self, "_stores", None) or ["A店", "B店"])
            self.vars["store"].set(keep_store if keep_store else default[0])
        self.items = []
        self._reload_items()
        self.raw_text.delete("1.0", "end")
        self._edit_index = None
        self._amount_manual = False
        self._neto_manual = False
        self.it_add_btn.config(text="保存")
        for k in self.it_vars:
            self.it_vars[k].set("")

    def _collect_store_options(self) -> list:
        """分店选项 = 设置中的分店列表 + 单据/结算中出现过的分店（去重）。"""
        stores = list(load_settings().get("stores") or config.DEFAULT_STORES)
        try:   # 首次启动数据库可能尚未建表
            for st in database.list_stores():
                if st and st not in stores:
                    stores.append(st)
        except Exception:  # noqa: BLE001
            pass
        return stores

    def _reload_store_options(self, select=None):
        """重新加载分店下拉选项（新增分店后调用）。"""
        self._stores = self._collect_store_options()
        if self.store_cb:
            self.store_cb["values"] = [""] + self._stores
        if select and select in self._stores:
            self.vars["store"].set(select)

    def _add_store_dialog(self):
        name = simpledialog.askstring(
            "添加分店", "输入新分店名称（如 C店）：",
            parent=self.frame) if self.frame else None
        name = (name or "").strip()
        if not name:
            return
        added = add_store(name)
        self.app.state.settings = load_settings()
        self._reload_store_options(select=name)
        self.status_var.set(
            f"✔ 分店“{name}”已添加。" if added else f"分店“{name}”已存在。")

    def refresh(self):
        pass
