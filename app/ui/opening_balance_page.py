"""财务期初余额页：按《财务初始余额.xlsx》模板维护科目体系与期初余额。

科目按编码前缀自动建树（1002 → 100201），汇总科目（明细科目=否）以浅蓝底加粗显示；
树中每个科目均可直接录入期初数（上级科目不做自动汇总）。
"""
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from app.db import database
from app.utils import parse_amount

HEADERS = ["*科目编码", "*科目名称", "明细科目(是/否)", "借贷", "年初余额",
           "本年累计借方发生额", "本年累计贷方发生额", "期初余额",
           "本年累计损益发生额"]

# (字段, 表头, 类型, 宽度, 对齐)
COLS = (
    ("name", "科目名称", "text", 200, "w"),
    ("is_leaf", "明细科目", "bool", 70, "center"),
    ("direction", "借贷", "dir", 56, "center"),
    ("opening_balance", "年初余额", "money", 110, "e"),
    ("cum_debit", "本年累计借方发生额", "money", 145, "e"),
    ("cum_credit", "本年累计贷方发生额", "money", 145, "e"),
    ("period_balance", "期初余额", "money", 110, "e"),
    ("pnl_cum", "本年累计损益发生额", "money", 145, "e"),
)

MONEY_KEYS = ("opening_balance", "cum_debit", "cum_credit",
              "period_balance", "pnl_cum")


def fmt_money(v) -> str:
    try:
        return f"{float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


class OpeningBalancePage:
    """科目体系（树形）+ 期初余额管理。"""

    def __init__(self, app):
        self.app = app
        self.frame = None
        self.rows = []          # list[dict] 当前编辑中的全部科目
        self.by_code = {}       # code -> dict
        self._edit_widget = None
        self._edit_item = None
        self._edit_key = None
        self._edit_old = ""

    # ------------------------------------------------------------ 构建
    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}

        top = ttk.LabelFrame(f, text="1. 会计年度与《财务初始余额.xlsx》")
        top.pack(fill="x", **pad)

        r1 = ttk.Frame(top)
        r1.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(r1, text="会计年度：").pack(side="left")
        self.year_var = tk.StringVar(value=str(datetime.date.today().year))
        self.year_box = ttk.Combobox(r1, textvariable=self.year_var, width=8,
                                     values=self._year_options())
        self.year_box.pack(side="left", padx=4)
        self.year_box.bind("<<ComboboxSelected>>", lambda e: self._load_from_db())
        self.year_box.bind("<Return>", lambda e: self._load_from_db())
        ttk.Button(r1, text="📂 导入模板", command=self._import_xlsx).pack(
            side="left", padx=(14, 4))
        ttk.Button(r1, text="📤 导出模板", command=self._export_xlsx).pack(side="left", padx=4)
        self.replace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r1, text="清空现有科目后重建",
                        variable=self.replace_var).pack(side="left", padx=(14, 4))
        ttk.Button(r1, text="全部展开", command=self._expand_all).pack(side="left", padx=(14, 3))
        ttk.Button(r1, text="全部折叠", command=self._collapse_all).pack(side="left", padx=3)
        ttk.Button(r1, text="刷新", command=self._load_from_db).pack(side="left", padx=3)

        self.status_var = tk.StringVar(
            value="就绪。导入模板后可直接编辑下表（浅蓝底加粗行为汇总科目）。")
        ttk.Label(top, textvariable=self.status_var, foreground="#1f6feb",
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=10, pady=(2, 8))

        mid = ttk.LabelFrame(f, text="2. 科目体系与期初余额（双击单元格可修改，科目编码只读）")
        mid.pack(fill="both", expand=True, **pad)
        wrap = ttk.Frame(mid)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)

        cols = tuple(c[0] for c in COLS)
        self.tree = ttk.Treeview(wrap, columns=cols, show="tree headings")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.heading("#0", text="科目编码")
        self.tree.column("#0", width=120, anchor="w")
        for key, head, _typ, width, anchor in COLS:
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.tag_configure("sum", background="#eaf1fb",
                               font=("Microsoft YaHei UI", 10, "bold"))
        self.tree.bind("<Double-1>", self._on_double_click)

        bot = ttk.LabelFrame(f, text="3. 维护与平衡校验")
        bot.pack(fill="x", **pad)
        inner = ttk.Frame(bot)
        inner.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(inner, text="新增科目：").pack(side="left")
        self.new_code_var = tk.StringVar()
        self.new_name_var = tk.StringVar()
        self.new_leaf_var = tk.StringVar(value="是")
        self.new_dir_var = tk.StringVar(value="借")
        ttk.Entry(inner, textvariable=self.new_code_var, width=11).pack(side="left", padx=2)
        ttk.Entry(inner, textvariable=self.new_name_var, width=16).pack(side="left", padx=2)
        ttk.Combobox(inner, textvariable=self.new_leaf_var, width=4,
                     values=["是", "否"]).pack(side="left", padx=2)
        ttk.Combobox(inner, textvariable=self.new_dir_var, width=4,
                     values=["借", "贷"]).pack(side="left", padx=2)
        ttk.Button(inner, text="添加", command=self._add_account).pack(side="left", padx=6)
        ttk.Button(inner, text="删除选中", command=self._del_selected).pack(side="left", padx=3)
        ttk.Button(inner, text="💾 保存全部", command=self._save_all).pack(side="left", padx=(18, 3))

        self.bal_leaf_var = tk.StringVar(value="")
        self.bal_all_var = tk.StringVar(value="")
        self.bal_leaf_label = ttk.Label(bot, textvariable=self.bal_leaf_var,
                                        font=("Microsoft YaHei UI", 9))
        self.bal_leaf_label.pack(anchor="w", padx=10, pady=(4, 0))
        ttk.Label(bot, textvariable=self.bal_all_var, foreground="#666666",
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=10, pady=(0, 8))

        self._load_from_db()

    # ------------------------------------------------------------ 数据加载
    def _year_options(self):
        try:
            years = list(database.list_opening_balance_years())
        except Exception:  # noqa: BLE001
            years = []
        this_year = str(datetime.date.today().year)
        if this_year not in years:
            years.append(this_year)
        return sorted(set(years), reverse=True)

    def _load_from_db(self):
        # 年度为空时按当前年度查询，避免跨年度期初重复成行
        year = self.year_var.get().strip() or str(datetime.date.today().year)
        try:
            self.rows = database.list_opening_balances(year=year)
        except Exception as e:  # noqa: BLE001
            self.rows = []
            self.status_var.set(f"读取失败：{e}")
        self._rebuild_tree()
        self._update_balance()

    def _rebuild_tree(self):
        """按 parent 构建树形；parent 缺失时按编码前缀回退。"""
        self._close_cell_editor()
        if not hasattr(self, "tree"):
            return
        self.by_code = {r["code"]: r for r in self.rows}
        codes = set(self.by_code)
        for r in self.rows:
            parent = r.get("parent") or ""
            if parent and parent not in codes:
                parent = database.infer_parent(r["code"], codes)
            r["parent"] = parent

        self.tree.delete(*self.tree.get_children())
        pending = sorted(self.rows, key=lambda x: (len(x["code"]), x["code"]))
        inserted = set()
        while pending:
            rest = []
            for r in pending:
                p = r["parent"]
                if p and p not in inserted:
                    rest.append(r)
                    continue
                self._insert_row(r, p)
                inserted.add(r["code"])
            if len(rest) == len(pending):      # 环/缺失父级：全部挂到根
                for r in rest:
                    self._insert_row(r, "")
                break
            pending = rest
        self._expand_all()

    def _insert_row(self, r, parent):
        tags = ("sum",) if not int(r.get("is_leaf", 1) or 0) else ()
        self.tree.insert(parent or "", "end", iid=r["code"],
                         text=r.get("code", ""), values=self._values(r), tags=tags)

    def _values(self, r):
        return (r.get("name", ""),
                "是" if int(r.get("is_leaf", 1) or 0) else "否",
                r.get("direction", "借") or "借",
                *[fmt_money(r.get(k, 0)) for k in MONEY_KEYS])

    # ------------------------------------------------------------ 平衡校验
    def _update_balance(self):
        # 与 _load_from_db 保持一致：年度为空时按当前年度统计
        year = self.year_var.get().strip() or str(datetime.date.today().year)
        try:
            t_leaf = database.get_opening_balance_total(year=year, only_leaf=True)
            t_all = database.get_opening_balance_total(year=year)
        except Exception:  # noqa: BLE001
            return
        if t_all["debit"] == 0 and t_all["credit"] == 0:
            self.bal_leaf_var.set("期初余额尚未录入（导入模板或直接编辑）。")
            self.bal_all_var.set("")
            self.bal_leaf_label.configure(foreground="#333333")
            return
        self.bal_leaf_var.set(self._balance_text("明细科目口径", t_leaf))
        self.bal_all_var.set(self._balance_text("全部科目口径", t_all))
        ok = abs(t_leaf["diff"]) < 0.005
        self.bal_leaf_label.configure(foreground="#0a7d33" if ok else "#c0392b")

    @staticmethod
    def _balance_text(label, t):
        diff = t["diff"]
        if abs(diff) < 0.005:
            return (f"{label}：借方合计 {fmt_money(t['debit'])} = "
                    f"贷方合计 {fmt_money(t['credit'])}   ✔ 借贷平衡")
        return (f"{label}：借方合计 {fmt_money(t['debit'])} ≠ "
                f"贷方合计 {fmt_money(t['credit'])}   ✗ 差额 {fmt_money(diff)}")

    # ------------------------------------------------------------ 导入 / 导出
    def _import_xlsx(self):
        path = filedialog.askopenfilename(
            title="选择《财务初始余额.xlsx》模板",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("所有文件", "*.*")])
        if not path:
            return
        year = self.year_var.get().strip() or None
        replace = bool(self.replace_var.get())
        if replace and not messagebox.askyesno(
                "确认重建",
                "将清空现有科目表与该年度期初余额，并以模板完全重建。是否继续？",
                parent=self.frame):
            return
        try:
            res = database.import_opening_balances_from_xlsx(
                path, year=year, replace=replace)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导入失败", str(e), parent=self.frame)
            return
        self.year_var.set(res["year"])
        self.year_box["values"] = self._year_options()
        mode = "清空重建" if res["replaced"] else "合并更新"
        self.status_var.set(
            f"✔ 已{mode}：科目 {res['accounts']} 个（其中明细科目 {res['leaf']} 个），"
            f"期初余额 {res['balances']} 条，年度 {res['year']}。")
        self._load_from_db()

    def _export_xlsx(self):
        if not self.rows:
            messagebox.showinfo("提示", "当前没有可导出的科目。", parent=self.frame)
            return
        year = self.year_var.get().strip() or str(datetime.date.today().year)
        path = filedialog.asksaveasfilename(
            title="导出财务初始余额", defaultextension=".xlsx",
            initialfile=f"财务初始余额_{year}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "财务初始余额模板_RMB"
            ws.append(HEADERS)
            for r in sorted(self.rows, key=lambda x: x.get("code", "")):
                ws.append([r.get("code", ""), r.get("name", ""),
                           "是" if int(r.get("is_leaf", 1) or 0) else "否",
                           r.get("direction", "借") or "借",
                           float(r.get("opening_balance", 0) or 0),
                           float(r.get("cum_debit", 0) or 0),
                           float(r.get("cum_credit", 0) or 0),
                           float(r.get("period_balance", 0) or 0),
                           float(r.get("pnl_cum", 0) or 0)])
            wb.save(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e), parent=self.frame)
            return
        self.status_var.set(f"✔ 已导出 {len(self.rows)} 个科目到 {path}")

    # ------------------------------------------------------------ 展开 / 折叠
    def _expand_all(self):
        for item in self.tree.get_children(""):
            self._expand(item)

    def _expand(self, item):
        self.tree.item(item, open=True)
        for ch in self.tree.get_children(item):
            self._expand(ch)

    def _collapse_all(self):
        for item in self.tree.get_children(""):
            self._collapse(item)

    def _collapse(self, item):
        for ch in self.tree.get_children(item):
            self._collapse(ch)
        self.tree.item(item, open=False)

    # ------------------------------------------------------------ 内联编辑
    def _on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col == "#0":                       # 科目编码只读
            self.status_var.set("科目编码不可修改（层级依据），如需变更请删除后新增。")
            return
        idx = int(col.replace("#", "")) - 1
        if not (0 <= idx < len(COLS)):
            return
        self._start_cell_edit(item, COLS[idx])

    def _start_cell_edit(self, item, col_def):
        self._close_cell_editor()
        key, _head, typ = col_def[0], col_def[1], col_def[2]
        bbox = self.tree.bbox(item, key)
        if not bbox:
            return
        x, y, w, h = bbox
        old = self.tree.set(item, key)
        if typ in ("bool", "dir"):
            values = ["是", "否"] if typ == "bool" else ["借", "贷"]
            wd = ttk.Combobox(self.tree, values=values, width=8, state="readonly")
            wd.set(old)
        else:
            wd = ttk.Entry(self.tree)
            wd.insert(0, old)
            wd.select_range(0, "end")
        wd.place(x=x, y=y, width=w, height=h)
        wd.focus_set()
        self._edit_widget, self._edit_item = wd, item
        self._edit_key, self._edit_old = key, old
        wd.bind("<Return>", lambda e: self._commit_cell_edit())
        wd.bind("<Escape>", lambda e: self._cancel_cell_edit())
        wd.bind("<FocusOut>", lambda e: self._commit_cell_edit())

    def _commit_cell_edit(self):
        wd = self._edit_widget
        if wd is None:
            return
        item, key, old = self._edit_item, self._edit_key, self._edit_old
        try:
            new_val = str(wd.get()).strip()
        except tk.TclError:
            new_val = old
        self._close_cell_editor()
        row = self.by_code.get(item)
        if row is None or new_val == old:
            return
        typ = next((c[2] for c in COLS if c[0] == key), "text")
        head = next((c[1] for c in COLS if c[0] == key), key)
        if typ == "money":
            row[key] = parse_amount(new_val)
        elif typ == "bool":
            row[key] = 1 if new_val in ("是", "1", "Y", "y") else 0
        else:
            row[key] = new_val or "借"
        self.tree.set(item, key, self._display(row, key))
        if key == "is_leaf":
            self.tree.item(item, tags=("sum",) if not int(row[key]) else ())
            self._update_balance()
        if key in MONEY_KEYS:
            self._update_balance()
        self.status_var.set(
            f"✔ 已修改 {row.get('code')} {row.get('name')} 的{head}"
            f"（点击“保存全部”写入数据库）")

    def _cancel_cell_edit(self):
        self._close_cell_editor()
        self.status_var.set("已取消单元格编辑。")

    def _close_cell_editor(self):
        wd = self._edit_widget
        self._edit_widget = None
        self._edit_item = None
        self._edit_key = None
        self._edit_old = ""
        if wd is not None:
            try:
                wd.destroy()
            except tk.TclError:
                pass

    @staticmethod
    def _display(row, key):
        if key in MONEY_KEYS:
            return fmt_money(row.get(key, 0))
        if key == "is_leaf":
            return "是" if int(row.get(key, 1) or 0) else "否"
        return str(row.get(key, "") or "")

    # ------------------------------------------------------------ 新增 / 删除 / 保存
    def _add_account(self):
        code = self.new_code_var.get().strip()
        name = self.new_name_var.get().strip()
        if not code or not name:
            messagebox.showwarning("提示", "请填写科目编码与科目名称。", parent=self.frame)
            return
        if code in self.by_code:
            messagebox.showwarning("提示", f"科目编码 {code} 已存在。", parent=self.frame)
            return
        leaf_raw = self.new_leaf_var.get().strip() or "是"
        row = {
            "code": code, "name": name,
            "direction": self.new_dir_var.get().strip() or "借",
            "is_leaf": 1 if leaf_raw in ("是", "1", "Y", "y") else 0,
            "parent": database.infer_parent(code, set(self.by_code) | {code}),
            "opening_balance": 0, "cum_debit": 0, "cum_credit": 0,
            "period_balance": 0, "pnl_cum": 0,
        }
        self.rows.append(row)
        self.new_code_var.set("")
        self.new_name_var.set("")
        self._rebuild_tree()
        self.tree.see(code)
        self.tree.selection_set(code)
        self.status_var.set(
            f"✔ 已添加科目 {code} {name}"
            f"（上级：{row['parent'] or '—'}，点击“保存全部”写入数据库）")

    def _del_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要删除的科目。", parent=self.frame)
            return
        code = sel[0]
        row = self.by_code.get(code)
        if row is None:
            return
        subs = [r for r in self.rows
                if r["code"] != code and str(r["code"]).startswith(code)]
        msg = f"确定删除科目 {code} {row.get('name', '')}？"
        if subs:
            msg += f"\n其下 {len(subs)} 个下级科目及期初余额将一并删除。"
        if not messagebox.askyesno("确认删除", msg, parent=self.frame):
            return
        try:
            n = database.delete_chart_of_account(code, cascade=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("删除失败", str(e), parent=self.frame)
            return
        self.rows = [r for r in self.rows if not str(r["code"]).startswith(code)]
        self._rebuild_tree()
        self._update_balance()
        self.status_var.set(f"已删除 {n} 个科目（含下级）及其期初余额。")

    def _save_all(self):
        self._commit_cell_edit()
        if not self.rows:
            messagebox.showinfo("提示", "没有可保存的科目。", parent=self.frame)
            return
        year = self.year_var.get().strip() or str(datetime.date.today().year)
        try:
            for r in self.rows:
                database.save_chart_of_account({
                    "code": r["code"], "name": r["name"],
                    "direction": r.get("direction") or "借",
                    "is_leaf": int(r.get("is_leaf", 1) or 0),
                    "parent": r.get("parent") or ""})
            database.save_opening_balances(self.rows, year=year)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)
            return
        self.year_var.set(year)
        self.year_box["values"] = self._year_options()
        self._load_from_db()
        self.status_var.set(f"✔ 已保存 {len(self.rows)} 个科目的期初余额（{year} 年度）。")

    def refresh(self):
        self._load_from_db()
