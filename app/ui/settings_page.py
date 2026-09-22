"""设置页：期初资本、币种与汇率（委内瑞拉官方汇率）、OCR 状态、数据目录。"""
import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app import config
from app.rates import (fetch_usd_ves, fetch_usd_eur, fetch_usd_cny,
                       CURRENCY_NAMES)
from app.settings import load_settings, save_settings
from app.utils import parse_amount, format_amount, frame_bg as _frame_bg


class SettingsPage:
    def __init__(self, app):
        self.app = app
        self.frame = None

    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}
        s = self.app.state.settings

        # ---------------- 财务参数
        top = ttk.LabelFrame(f, text="财务参数")
        top.pack(fill="x", **pad)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Label(row, text="期初资本（Capital inicial）：").pack(side="left")
        self.capital_var = tk.StringVar(value=str(s.get("capital_inicial", 0)))
        ttk.Entry(row, textvariable=self.capital_var, width=14).pack(side="left", padx=8)
        ttk.Label(row, text="（用于资产负债表“实收资本”项）",
                  foreground="gray").pack(side="left", padx=8)

        row2 = ttk.Frame(top)
        row2.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(row2, text="分店列表（Sucursales，逗号分隔）：").pack(side="left")
        self.stores_var = tk.StringVar(value=", ".join(s.get("stores") or config.DEFAULT_STORES))
        ttk.Entry(row2, textvariable=self.stores_var, width=34).pack(side="left", padx=8)
        ttk.Label(row2, text="用于单据录入时选择入库分店",
                  foreground="gray").pack(side="left", padx=8)

        # ---------------- 币种与汇率
        fx = ttk.LabelFrame(f, text="币种与汇率（含委内瑞拉官方汇率）")
        fx.pack(fill="x", **pad)

        r0 = ttk.Frame(fx)
        r0.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(r0, text="本位币（记账币种 Base）：").pack(side="left")
        self.base_cur_var = tk.StringVar(value=config.currency_label(
            s.get("base_currency") or config.DEFAULT_BASE_CURRENCY))
        ttk.Combobox(r0, textvariable=self.base_cur_var, width=18,
                     values=[v for v in CURRENCY_NAMES.values()]).pack(
            side="left", padx=8)
        ttk.Label(r0, text="所有单据金额将换算为本位币后入账。",
                  foreground="gray").pack(side="left", padx=8)

        r1 = ttk.Frame(fx)
        r1.pack(fill="x", padx=10, pady=4)
        ttk.Label(r1, text="美元兑本位币（1 USD = X 本位币）：").pack(side="left")
        self.usd_to_base_var = tk.StringVar(value=str(s.get("usd_to_base", 1.0)))
        ttk.Entry(r1, textvariable=self.usd_to_base_var, width=10).pack(side="left", padx=8)
        ttk.Label(r1, text="（本位币为 USD 时填 1；本位币为 EUR 时可在线更新）",
                  foreground="gray").pack(side="left")

        r2 = ttk.Frame(fx)
        r2.pack(fill="x", padx=10, pady=4)
        ttk.Label(r2, text="委内瑞拉官方汇率（1 USD = X Bs，BCV）：").pack(side="left")
        self.usd_ves_var = tk.StringVar(
            value=str(s.get("usd_ves_official", 0.0) or 0.0))
        ttk.Entry(r2, textvariable=self.usd_ves_var, width=10).pack(side="left", padx=8)
        upd = s.get("usd_ves_date", "")
        self.rate_date_var = tk.StringVar(
            value=f"（更新时间：{upd[:10]}）" if upd else "（未获取）")
        ttk.Label(r2, textvariable=self.rate_date_var, foreground="gray").pack(side="left")

        rc = ttk.Frame(fx)
        rc.pack(fill="x", padx=10, pady=4)
        ttk.Label(rc, text="美元兑人民币（1 USD = X CNY）：").pack(side="left")
        self.usd_cny_var = tk.StringVar(value=str(s.get("usd_cny", 0.0) or 0.0))
        ttk.Entry(rc, textvariable=self.usd_cny_var, width=10).pack(side="left", padx=8)
        ttk.Label(rc, text="（人民币单据换算用；本位币为 CNY 时即 USD→CNY，可在线更新）",
                  foreground="gray").pack(side="left")

        r3 = ttk.Frame(fx)
        r3.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Button(r3, text="🌐 在线获取官方汇率",
                   command=self._fetch_rates).pack(side="left")
        self.rate_status = tk.StringVar(value="")
        ttk.Label(r3, textvariable=self.rate_status, foreground="#1f6feb").pack(
            side="left", padx=10)

        # ---------------- 保存
        sav = ttk.Frame(f)
        sav.pack(fill="x", **pad)
        ttk.Button(sav, text="保存全部设置", command=self._save).pack(side="left")
        ttk.Label(sav, text="（含期初资本、本位币、汇率）",
                  foreground="gray").pack(side="left", padx=8)

        # ---------------- OCR 引擎
        mid = ttk.LabelFrame(f, text="OCR 引擎")
        mid.pack(fill="x", **pad)
        r4 = ttk.Frame(mid)
        r4.pack(fill="x", padx=10, pady=10)
        self.ocr_status = tk.StringVar(value="尚未加载（首次识别时自动加载）")
        ttk.Label(r4, textvariable=self.ocr_status).pack(side="left")
        ttk.Button(r4, text="测试加载", command=self._test_ocr).pack(side="left", padx=10)

        # ---------------- 数据
        bot = ttk.LabelFrame(f, text="数据")
        bot.pack(fill="x", **pad)
        r5 = ttk.Frame(bot)
        r5.pack(fill="x", padx=10, pady=10)
        ttk.Label(r5, text=f"数据库：{config.DB_PATH}").pack(side="left")
        ttk.Button(r5, text="打开数据目录", command=self._open_dir).pack(side="left", padx=10)

        note = tk.Text(f, height=5, wrap="word", font=("Microsoft YaHei UI", 9),
                       foreground="#333", relief="flat", bg=_frame_bg(self.frame))
        note.insert("1.0",
                    "说明：\n"
                    "· 扫描单据时自动识别币种（EUR/USD/Bs 玻利瓦尔/CNY 人民币等）与单据汇率；\n"
                    "· 报表按本位币统一换算：Bs → USD（官方汇率）→ 本位币；"
                    "CNY → USD（美元兑人民币汇率）→ 本位币；\n"
                    "· 官方汇率来源为委内瑞拉央行（BCV，经 dolarapi 接口），可手动填写兜底。")
        note.config(state="disabled")
        note.pack(anchor="w", fill="x", padx=14, pady=8)

    # ------------------------------------------------------------ 保存
    def _save(self):
        try:
            cap = parse_amount(self.capital_var.get())
            usd_to_base = parse_amount(self.usd_to_base_var.get())
            usd_ves = parse_amount(self.usd_ves_var.get())
            usd_cny = parse_amount(self.usd_cny_var.get())
        except ValueError:
            messagebox.showwarning("提示", "金额/汇率格式无效，请检查输入。", parent=self.frame)
            return
        # 下拉里是「中文名称（简称）」，存库仍用代码
        base_cur = config.currency_code(self.base_cur_var.get())
        if not base_cur:
            base_cur = config.DEFAULT_BASE_CURRENCY

        settings = load_settings()
        settings["capital_inicial"] = cap
        settings["base_currency"] = base_cur
        settings["usd_to_base"] = usd_to_base
        settings["usd_ves_official"] = usd_ves
        settings["usd_cny"] = usd_cny
        if usd_ves > 0 and not settings.get("usd_ves_date"):
            settings["usd_ves_date"] = datetime.date.today().isoformat()
        # 分店列表：按中文/西语逗号分隔，去空白
        stores = [x.strip() for x in
                  self.stores_var.get().replace("，", ",").split(",") if x.strip()]
        settings["stores"] = stores or list(config.DEFAULT_STORES)
        save_settings(settings)
        self.app.state.settings = settings
        messagebox.showinfo(
            "已保存",
            f"期初资本 {format_amount(cap, symbols=False)}；本位币 {base_cur}；"
            f"1 USD = {usd_to_base} {base_cur}；官方汇率 1 USD = {usd_ves} Bs；"
            f"1 USD = {usd_cny} CNY；"
            f"分店 {len(settings['stores'])} 个。",
            parent=self.frame)

    # ------------------------------------------------------------ 在线汇率
    def _fetch_rates(self):
        self.rate_status.set("正在获取委内瑞拉官方汇率（BCV）…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            res = fetch_usd_ves()
            eur = cny = None
            try:
                eur = fetch_usd_eur()
            except Exception:  # noqa: BLE001  （可选源，失败不阻断）
                eur = None
            try:
                cny = fetch_usd_cny()
            except Exception:  # noqa: BLE001
                cny = None
            self.app.after(0, lambda: self._fetch_done(res, eur, cny))
        except Exception as e:  # noqa: BLE001
            self.app.after(0, lambda: self._fetch_fail(str(e)))

    def _fetch_done(self, res, eur, cny=None):
        self.usd_ves_var.set(str(res["usd_ves"]))
        d = (res.get("date") or "")[:10]
        self.rate_date_var.set(f"（更新时间：{d}）")
        base = self.base_cur_var.get().strip().upper()
        if eur and base == "EUR":
            self.usd_to_base_var.set(str(eur["usd_eur"]))
        if cny:
            self.usd_cny_var.set(str(cny["usd_cny"]))
            if base == "CNY":      # 本位币为人民币时，1 USD = X CNY 即 usd_to_base
                self.usd_to_base_var.set(str(cny["usd_cny"]))
        self.rate_status.set(
            f"✔ 已获取：1 USD = {res['usd_ves']} Bs"
            + (f"，1 USD = {eur['usd_eur']} EUR" if eur else "")
            + (f"，1 USD = {cny['usd_cny']} CNY" if cny else "")
            + "。请点击“保存全部设置”生效。")

    def _fetch_fail(self, err):
        self.rate_status.set("✗ " + err)

    # ------------------------------------------------------------ OCR / 目录
    def _test_ocr(self):
        self.ocr_status.set("正在加载 OCR 模型（首次需要下载模型，请耐心等待）…")
        try:
            engine = self.app.state.get_ocr_engine()
            ok = engine.load()
            if ok:
                self.ocr_status.set(
                    f"✔ 已加载（后端：{engine.backend}，语言：{engine.lang}）")
            else:
                self.ocr_status.set("✗ 加载失败：" + (engine.error or "未知错误"))
        except Exception as e:  # noqa: BLE001
            self.ocr_status.set("✗ 加载失败：" + str(e))

    def _open_dir(self):
        import os
        config.ensure_data_dir()
        os.startfile(config.DATA_DIR)

    def refresh(self):
        s = load_settings()
        self.capital_var.set(str(s.get("capital_inicial", 0)))
        self.base_cur_var.set(config.currency_label(
            s.get("base_currency") or config.DEFAULT_BASE_CURRENCY))
        self.usd_to_base_var.set(str(s.get("usd_to_base", 1.0)))
        self.usd_ves_var.set(str(s.get("usd_ves_official", 0.0) or 0.0))
        self.usd_cny_var.set(str(s.get("usd_cny", 0.0) or 0.0))
        self.stores_var.set(", ".join(s.get("stores") or config.DEFAULT_STORES))
        upd = s.get("usd_ves_date", "")
        self.rate_date_var.set(f"（更新时间：{upd[:10]}）" if upd else "（未获取）")
