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
        ttk.Radiobutton(row, text="科目余额表", value="trial",
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

        # 报表表格（列随报表类型切换：资产负债表/利润表两列，科目余额表多列）
        self.tree = ttk.Treeview(f, columns=("name", "amount"),
                                 show="headings", height=22)
        self._setup_cols(self._two_cols())
        self.tree.pack(fill="both", expand=True, padx=14, pady=8)
        self.tree.tag_configure("bold", font=("Microsoft YaHei UI", 10, "bold"))
        self.tree.tag_configure("sub", foreground="#1f6feb")

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
        try:
            self.report, self.docs = get_report(doc_type, d_from, d_to, capital)
            self.pdf_btn.state(["!disabled"])
            self._render()
        except Exception as e:  # noqa: BLE001  生成失败不应让界面崩溃
            import traceback
            traceback.print_exc()
            self.report, self.docs = None, []
            messagebox.showerror("生成报表失败", str(e), parent=self.frame)
            return
        year = self.report.get("year")
        self.src_var.set(
            f"期初来源：{self.report.get('opening_source') or '—'}"
            + (f" · 会计年度 {year}" if year else "")
            + " · 金额为原币（按科目币种明细入账，不换算、不带货币符号）")
        note = self.report.get("currency_note") or ""
        if note:
            messagebox.showinfo("币种提示", note, parent=self.frame)

    # ------------------------------------------------------------ 金额与本位币
    def _base_code(self) -> str:
        """本位币代码（报表尚未生成时取设置里的本位币）。"""
        rep = self.report or {}
        return (rep.get("base_currency")
                or (self.app.state.settings.get("base_currency")
                    if self.app and self.app.state else "")
                or config.DEFAULT_BASE_CURRENCY)

    def _fmt(self, value) -> str:
        """报表金额只显示数字，不跟货币符号。"""
        return format_amount(value, symbols=False)

    def _base_cur(self) -> str:
        """本位币显示名，如「玻利瓦尔（Bs）」。"""
        return config.currency_label(self._base_code())

    def _src_text(self) -> str:
        """数据来源说明：单据 + 店铺收入/支出日报（模块关联）。"""
        s = (self.report or {}).get("sources") or {}
        parts = [f"{s.get('docs', len(self.docs))} 张单据"]
        if s.get("income_rows"):
            parts.append(f"收入日报 {s['income_rows']} 笔"
                         f" {self._fmt(s.get('income_amount', 0.0))}")
        if s.get("expense_rows"):
            parts.append(f"支出日报 {s['expense_rows']} 笔"
                         f" {self._fmt(s.get('expense_amount', 0.0))}")
        return " · ".join(parts)

    def _two_cols(self) -> list:
        """资产负债表 / 利润表：项目 + 金额两列（金额不跟货币符号）。"""
        return [("name", "项目", 560, "w"),
                ("amount", "金额", 200, "e")]

    def _trial_cols(self) -> list:
        """科目余额表：科目 + 期初/本期/期末 借贷六列（金额不跟货币符号）。"""
        return [("code", "科目编码", 100, "w"),
                ("name", "科目名称", 300, "w"),
                ("opening_debit", "期初借方", 120, "e"),
                ("opening_credit", "期初贷方", 120, "e"),
                ("debit", "本期借方", 120, "e"),
                ("credit", "本期贷方", 120, "e"),
                ("ending_debit", "期末借方", 120, "e"),
                ("ending_credit", "期末贷方", 120, "e")]

    def _setup_cols(self, cols):
        ids = [c[0] for c in cols]
        # 先恢复「显示全部列」再换列：残留的旧 displaycolumns（如 amount）
        # 会让 Tk 在列数变化时抛 TclError「Invalid column index」，导致界面崩溃
        self.tree["displaycolumns"] = "#all"
        self.tree["columns"] = ids
        self.tree["displaycolumns"] = ids
        for cid, title, width, anchor in cols:
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor=anchor)

    def _render_trial(self):
        """科目余额表：全部科目（层级缩进，父科目汇总其明细）。"""
        self._setup_cols(self._trial_cols())
        keys = ("opening_debit", "opening_credit", "debit", "credit",
                "ending_debit", "ending_credit")
        for row in self.report.get("rows", []):
            tag = "bold" if row.get("is_parent") else ""
            self.tree.insert("", "end", values=(
                row.get("code") or "", row.get("name") or "",
                *[self._fmt(row.get(k, 0.0)) for k in keys]), tags=(tag,))
        t = self.report.get("totals") or {}
        self.tree.insert("", "end", values=(
            "合计", "（末级科目合计）", *[self._fmt(t.get(k, 0.0)) for k in keys]),
            tags=("sub",))
        n = len(self.report.get("rows", []))
        self.summary_var.set(
            f"科目余额表：{n} 个科目 · 本期借方 {self._fmt(t.get('debit', 0.0))} "
            f"/ 贷方 {self._fmt(t.get('credit', 0.0))} · "
            f"期末借方 {self._fmt(t.get('ending_debit', 0.0))} "
            f"/ 贷方 {self._fmt(t.get('ending_credit', 0.0))} · "
            f"{self._src_text()}" +
            (f"\n{self.report.get('currency_note') or ''}"
             if self.report.get("currency_note") else ""))

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        doc_type = self.type_var.get()
        if doc_type == "trial":
            self._render_trial()
        elif doc_type == "balance":
            self._setup_cols(self._two_cols())
            r = self.report
            self._section("ACTIVO · 资产", r["activo"])
            self._section("PASIVO · 负债", r["pasivo"])
            self._section("PATRIMONIO NETO · 净资产", r["patrimonio"])
            self.tree.insert("", "end", values=(
                "──────────────────────────────────────", ""))
            self.tree.insert("", "end", values=(
                "TOTAL ACTIVO · 资产合计", self._fmt(r["total_activo"])))
            self.tree.insert("", "end", values=(
                "TOTAL PASIVO + PN · 负债与净资产合计",
                self._fmt(r["total_pasivo_pat"])))
            ok = r["balanced"]
            note = r.get("currency_note") or ""
            self.summary_var.set(
                ("✔ 资产负债表平衡" if ok else
                 f"✗ 资产负债表不平衡，差额 {self._fmt(r['diff'])}") +
                f" · 资产合计 {self._fmt(r['total_activo'])} · " +
                f"{self._src_text()}" +
                (f"\n{note}" if note else ""))
        else:
            self._setup_cols(self._two_cols())
            r = self.report
            for row in r["rows"]:
                tag = "bold" if row.get("bold") else ""
                self.tree.insert("", "end", values=(
                    (" " * (row.get("indent", 0) * 2)) + row["name"],
                    self._fmt(row["amount"])), tags=(tag,))
            self.tree.insert("", "end", values=(
                "IVA neto（负=应交，正=可抵/退）", self._fmt(r["iva_neto"])))
            self.tree.tag_configure("bold", font=("Microsoft YaHei UI", 10, "bold"))
            note = r.get("currency_note") or ""
            self.summary_var.set(
                f"收入 {self._fmt(r['ventas'])} · 成本 {self._fmt(r['coste'])} · "
                f"净利润 {self._fmt(r['resultado'])} · "
                f"出货 {r['num_venta']} 张 / 进货 {r['num_compra']} 张 · "
                f"{self._src_text()}" +
                (f"\n{note}" if note else ""))

    def _section(self, title, rows):
        self.tree.insert("", "end", values=(title, ""))
        total = sum(x["amount"] for x in rows)
        for x in rows:
            self.tree.insert("", "end", values=(
                "    " + x["name"], self._fmt(x["amount"])))
        self.tree.insert("", "end", values=(
            "    小计", self._fmt(total)), tags=("sub",))
        self.tree.tag_configure("sub", foreground="#1f6feb")

    # ------------------------------------------------------------ 导出
    def _export(self):
        if self.report is None:
            return
        d_from, d_to = self._parse_range()
        doc_type = self.type_var.get()
        name = {"balance": "balance", "income": "resultados",
                "trial": "balance_comprobacion"}[doc_type]
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
