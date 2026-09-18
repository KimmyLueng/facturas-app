"""财务报表页：资产负债表/利润表展示与导出。"""
import datetime
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from app import config
from app.accounting import get_report, export_pdf
from app.utils import format_amount


class ReportsPage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.report = None
        self.docs = []

    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}

        top = ttk.LabelFrame(f, text="报表条件")
        top.pack(fill="x", **pad)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=10, pady=8)

        ttk.Label(row, text="报表类型：").pack(side="left")
        self.type_var = tk.StringVar(value="balance")
        ttk.Radiobutton(row, text="资产负债表", value="balance",
                        variable=self.type_var).pack(side="left", padx=6)
        ttk.Radiobutton(row, text="利润表", value="income",
                        variable=self.type_var).pack(side="left", padx=6)

        today = datetime.date.today()
        year_start = datetime.date(today.year, 1, 1)
        ttk.Label(row, text="从：").pack(side="left", padx=(18, 2))
        self.from_var = tk.StringVar(value=year_start.strftime("%Y-%m-%d"))
        ttk.Entry(row, textvariable=self.from_var, width=11).pack(side="left")
        ttk.Label(row, text="至：").pack(side="left", padx=(6, 2))
        self.to_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        ttk.Entry(row, textvariable=self.to_var, width=11).pack(side="left")

        ttk.Button(row, text="生成报表", command=self._generate).pack(side="left", padx=14)
        self.pdf_btn = ttk.Button(row, text="导出 PDF", command=self._export,
                                  state="disabled")
        self.pdf_btn.pack(side="left")

        # 摘要
        self.summary_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.summary_var, foreground="#1f6feb",
                  font=("Microsoft YaHei UI", 10)).pack(fill="x", padx=14, pady=4)

        # 报表表格
        base_cur = self.app.state.settings.get("base_currency", "USD")
        cols = ("name", "amount")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=22)
        self.tree.heading("name", text="项目")
        self.tree.heading("amount", text=f"金额（本位币 {base_cur}）")
        self.tree.column("name", width=560, anchor="w")
        self.tree.column("amount", width=200, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=14, pady=8)

        self.src_var = tk.StringVar(
            value="期初来源：—（生成报表后显示，取自科目表期初余额）")
        ttk.Label(f, textvariable=self.src_var,
                  foreground="gray").pack(fill="x", padx=14, pady=(0, 10))

    # ------------------------------------------------------------ 生成
    def _parse_range(self):
        d_from, d_to = None, None
        for var in (self.from_var, self.to_var):
            s = var.get().strip()
            if s:
                try:
                    dt = datetime.date.fromisoformat(s)
                except ValueError:
                    try:
                        from app.utils import parse_date
                        dt = parse_date(s)
                    except Exception:  # noqa: BLE001
                        dt = None
                if dt is None:
                    return None, None
                if var is self.from_var:
                    d_from = dt
                else:
                    d_to = dt
        if d_from and d_to and d_from > d_to:
            d_from, d_to = d_to, d_from
        return d_from, d_to

    def _generate(self):
        d_from, d_to = self._parse_range()
        if self.from_var.get().strip() and d_from is None:
            messagebox.showwarning("提示", "起始日期格式无效（应为 YYYY-MM-DD）。",
                                   parent=self.frame)
            return
        if self.to_var.get().strip() and d_to is None:
            messagebox.showwarning("提示", "截止日期格式无效（应为 YYYY-MM-DD）。",
                                   parent=self.frame)
            return
        doc_type = self.type_var.get()
        capital = self.app.state.capital()
        self.report, self.docs = get_report(doc_type, d_from, d_to, capital)
        self.pdf_btn.state(["!disabled"])
        self._render()
        year = self.report.get("year")
        self.src_var.set(
            f"期初来源：{self.report.get('opening_source') or '—'}"
            + (f" · 会计年度 {year}" if year else ""))
        note = self.report.get("currency_note") or ""
        if note:
            messagebox.showinfo("币种提示", note, parent=self.frame)

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        doc_type = self.type_var.get()
        if doc_type == "balance":
            r = self.report
            self._section("ACTIVO · 资产", r["activo"])
            self._section("PASIVO · 负债", r["pasivo"])
            self._section("PATRIMONIO NETO · 净资产", r["patrimonio"])
            self.tree.insert("", "end", values=(
                "──────────────────────────────────────", ""))
            self.tree.insert("", "end", values=(
                "TOTAL ACTIVO · 资产合计", format_amount(r["total_activo"])))
            self.tree.insert("", "end", values=(
                "TOTAL PASIVO + PN · 负债与净资产合计",
                format_amount(r["total_pasivo_pat"])))
            ok = r["balanced"]
            note = r.get("currency_note") or ""
            self.summary_var.set(
                ("✔ 资产负债表平衡" if ok else
                 f"✗ 资产负债表不平衡，差额 {format_amount(r['diff'])}") +
                f" · 资产合计 {format_amount(r['total_activo'])} · " +
                f"含 {len(self.docs)} 张单据" +
                (f"\n{note}" if note else ""))
        else:
            r = self.report
            for row in r["rows"]:
                tag = "bold" if row.get("bold") else ""
                self.tree.insert("", "end", values=(
                    (" " * (row.get("indent", 0) * 2)) + row["name"],
                    format_amount(row["amount"])), tags=(tag,))
            self.tree.insert("", "end", values=(
                "IVA neto（负=应交，正=可抵/退）", format_amount(r["iva_neto"])))
            self.tree.tag_configure("bold", font=("Microsoft YaHei UI", 10, "bold"))
            note = r.get("currency_note") or ""
            self.summary_var.set(
                f"收入 {format_amount(r['ventas'])} · 成本 {format_amount(r['coste'])} · "
                f"净利润 {format_amount(r['resultado'])} · "
                f"出货 {r['num_venta']} 张 / 进货 {r['num_compra']} 张" +
                (f"\n{note}" if note else ""))

    def _section(self, title, rows):
        self.tree.insert("", "end", values=(title, ""))
        total = sum(x["amount"] for x in rows)
        for x in rows:
            self.tree.insert("", "end", values=(
                "    " + x["name"], format_amount(x["amount"])))
        self.tree.insert("", "end", values=(
            "    小计", format_amount(total)), tags=("sub",))
        self.tree.tag_configure("sub", foreground="#1f6feb")

    # ------------------------------------------------------------ 导出
    def _export(self):
        if self.report is None:
            return
        d_from, d_to = self._parse_range()
        doc_type = self.type_var.get()
        name = {"balance": "balance", "income": "resultados"}[doc_type]
        default = os.path.join(config.DATA_DIR,
                               f"informe_{name}_{datetime.date.today().isoformat()}.pdf")
        path = filedialog.asksaveasfilename(
            parent=self.frame, initialfile=os.path.basename(default),
            defaultextension=".pdf",
            filetypes=[("PDF 文件", "*.pdf")])
        if not path:
            return
        try:
            out = export_pdf(doc_type, d_from, d_to,
                             self.app.state.capital(), out_path=path)
            messagebox.showinfo("导出成功", f"报表已导出：\n{out}", parent=self.frame)
            os.startfile(out)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e), parent=self.frame)

    def refresh(self):
        pass
