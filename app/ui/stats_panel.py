"""时段统计面板：今天 / 昨天 / 本月 / 上月 / 自定义区间。

供「店铺收入统计」「店铺支出统计」页面复用：
fetcher(date_from, date_to) 返回 [(币种代码, 金额), ...]，
面板负责维度切换、区间解析与汇总显示（合计 + 按币种小计）。
统计失败只在面板内提示，不影响页面其他功能。
"""
import datetime
import tkinter as tk
from tkinter import ttk

from app import config
from app.utils import format_amount


class PeriodStatsPanel(ttk.LabelFrame):
    """带维度切换的时段统计区。"""

    def __init__(self, master, title, fetcher, **kw):
        super().__init__(master, text=title, padding=10, **kw)
        self._fetcher = fetcher

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.mode = tk.StringVar(value="today")
        for value, text in (("today", "今天"), ("yesterday", "昨天"),
                            ("month", "本月"), ("last_month", "上月"),
                            ("custom", "自定义")):
            ttk.Radiobutton(row, text=text, value=value, variable=self.mode,
                            command=self.refresh).pack(side="left", padx=4)
        today = datetime.date.today()
        ttk.Label(row, text="从：").pack(side="left", padx=(14, 2))
        self.from_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        ttk.Entry(row, textvariable=self.from_var, width=11).pack(side="left")
        ttk.Label(row, text="至：").pack(side="left", padx=(6, 2))
        self.to_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        ttk.Entry(row, textvariable=self.to_var, width=11).pack(side="left")
        ttk.Button(row, text="查询", command=self._on_query).pack(
            side="left", padx=8)

        self.stat_var = tk.StringVar(value="统计：—")
        ttk.Label(self, textvariable=self.stat_var, justify="left",
                  font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", pady=(6, 0))
        self.refresh()

    # ------------------------------------------------------------ 交互
    def _on_query(self):
        self.mode.set("custom")
        self.refresh()

    @staticmethod
    def _parse_date(var):
        """解析日期（支持 YYYY-MM-DD 与常用分隔格式）。"""
        s = (var.get() or "").strip()
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            try:
                from app.utils import parse_date
                return parse_date(s)
            except Exception:  # noqa: BLE001
                return None

    # ------------------------------------------------------------ 统计
    def refresh(self):
        """按当前维度统计并显示（原币口径：合计 + 按币种小计）。"""
        mode = self.mode.get()
        today = datetime.date.today()
        f = t = None
        try:
            if mode == "today":
                f = t = today
            elif mode == "yesterday":
                f = t = today - datetime.timedelta(days=1)
            elif mode == "month":
                f = today.replace(day=1)
                t = ((f + datetime.timedelta(days=32)).replace(day=1)
                     - datetime.timedelta(days=1))
            elif mode == "last_month":
                t = today.replace(day=1) - datetime.timedelta(days=1)
                f = t.replace(day=1)
            else:  # custom
                f = self._parse_date(self.from_var)
                t = self._parse_date(self.to_var)
                if f is None or t is None:
                    self.stat_var.set(
                        "自定义区间：请输入有效日期（YYYY-MM-DD 或 DD/MM/YYYY）")
                    return
                if f > t:
                    f, t = t, f
            rows = self._fetcher(f, t) or []
            total = sum(float(a or 0) for _c, a in rows)
            by_cur = {}
            for c, a in rows:
                s, n = by_cur.get(c, (0.0, 0))
                by_cur[c] = (s + float(a or 0), n + 1)
            cur_txt = "  ·  ".join(
                f"{config.currency_label(c) or c} "
                f"{format_amount(s, symbols=False)}（{n} 笔）"
                for c, (s, n) in sorted(by_cur.items()))
            text = (f"统计区间（{f.isoformat()} ~ {t.isoformat()}）："
                    f"合计 {format_amount(total, symbols=False)}"
                    f"（{len(rows)} 笔）")
            if cur_txt:
                text += f"\n按币种：{cur_txt}"
            self.stat_var.set(text)
        except Exception as e:  # noqa: BLE001  统计失败不影响页面
            self.stat_var.set(f"统计失败：{e}")
