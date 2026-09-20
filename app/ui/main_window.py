"""主窗口：左侧导航 + 右侧内容页。"""
import datetime
import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

from app import config, settings
from app.db import database
from app.settings import load_settings, save_settings
from app.ui.scan_page import ScanPage
from app.ui.documents_page import DocumentsPage
from app.ui.reports_page import ReportsPage
from app.ui.daily_income_page import DailyIncomePage
from app.ui.daily_expense_page import DailyExpensePage
from app.ui.supplier_settlement_page import SupplierSettlementPage
from app.ui.opening_balance_page import OpeningBalancePage
from app.ui.settings_page import SettingsPage
from app.ui.products_page import ProductsPage
from app.ui.dashboard_page import DashboardPage
from app.ui.sync_page import SyncPage


class AppState:
    """跨页面共享状态。"""

    def __init__(self):
        self.settings = load_settings()
        self.ocr_engine = None  # 懒加载

    def get_ocr_engine(self):
        from app.ocr import OCREngine
        if self.ocr_engine is None:
            self.ocr_engine = OCREngine(lang=config.OCR_LANG)
        return self.ocr_engine

    def capital(self):
        return float(self.settings.get("capital_inicial", 0.0) or 0.0)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gestion de Facturas · 西班牙语单据财务管理系统")
        self.geometry("1180x760")
        self.minsize(980, 620)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Nav.TButton", font=("Microsoft YaHei UI", 11),
                        padding=(16, 10), anchor="w")
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

        self.state = AppState()

        # Tk 回调里的异常默认只打到 stderr（打包成窗口程序时看不到），
        # 这里统一记录到 error.log 并弹窗，避免界面「闪退」且查不到原因
        self.report_callback_exception = self._on_callback_error

        # 必须先建表，再构建 UI（各页面首屏会立即查询数据库）
        self._init_db()
        self._build_ui()

    def _on_callback_error(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        log_path = os.path.join(config.DATA_DIR, "error.log")
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:  # noqa: BLE001
            log_path = "(无法写入日志)"
        print(text, file=sys.stderr)
        try:
            messagebox.showerror(
                "程序错误", f"{val}\n\n详情请查看：\n{log_path}", parent=self)
        except Exception:  # noqa: BLE001
            pass

    def _init_db(self):
        try:
            database.init_db()
        except Exception as e:  # noqa: BLE001
            self.after_idle(lambda: messagebox.showerror(
                "错误", f"数据库初始化失败：{e}", parent=self))

    def _build_ui(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        # 左侧导航
        nav = ttk.Frame(container, width=210)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        ttk.Label(nav, text="GESTIÓN\nDE FACTURAS",
                  font=("Microsoft YaHei UI", 13, "bold"),
                  foreground="#1f6feb").pack(pady=(24, 18))

        self.pages = {}
        self.nav_btns = {}

        def make_nav(text, page_cls):
            btn = ttk.Button(nav, text=text, style="Nav.TButton",
                             command=lambda: self.show_page(text))
            btn.pack(fill="x", padx=8, pady=3)
            self.nav_btns[text] = btn
            self.pages[text] = page_cls(self)

        make_nav("🏠 经营概览", DashboardPage)
        make_nav("📦 商品库存", ProductsPage)
        make_nav("📥 扫描导入单据", ScanPage)
        make_nav("📄 单据管理", DocumentsPage)
        make_nav("📊 财务报表", ReportsPage)
        make_nav("💰 店铺收入日报", DailyIncomePage)
        make_nav("💸 店铺支出日报", DailyExpensePage)
        make_nav("🏭 供应商结算", SupplierSettlementPage)
        make_nav("📒 财务期初余额", OpeningBalancePage)
        make_nav("☁️ 数据同步", SyncPage)
        make_nav("⚙️ 设置", SettingsPage)

        ttk.Label(nav, text="OCR: PaddleOCR · 西班牙语",
                  font=("Microsoft YaHei UI", 8),
                  foreground="gray").pack(side="bottom", pady=12)

        # 右侧内容
        self.content = ttk.Frame(container)
        self.content.pack(side="left", fill="both", expand=True)

        self.current_page = None
        self.show_page("🏠 经营概览")

        # 后台自动同步（WebDAV）：每 60 秒检查一次是否到了同步间隔
        self.after(5000, self._auto_sync_tick)

    def show_page(self, name):
        page = self.pages[name]
        for w in self.content.winfo_children():
            w.destroy()
        page.frame = ttk.Frame(self.content)
        page.frame.pack(fill="both", expand=True)
        page.build()
        self.current_page = page

        for n, b in self.nav_btns.items():
            b.state(["!pressed"])
        self.nav_btns[name].state(["pressed"])

    def refresh_current(self):
        if self.current_page:
            self.current_page.refresh()

    # -------------------------------------------------- 自动同步（WebDAV）
    def _auto_sync_tick(self):
        """定时检查自动同步（实际网络操作在后台线程）。"""
        threading.Thread(target=self._auto_sync_worker, daemon=True).start()
        self.after(60_000, self._auto_sync_tick)

    def _auto_sync_worker(self):
        try:
            from app.sync import manager
            if not manager.auto_sync_due():
                return
            manager.mark_auto_synced()
            res = manager.auto_sync() or {}
            if res.get("ok") and res.get("action") == "download":
                # 数据库已被云端替换：重载设置并刷新当前页
                self.after(0, self._after_sync_download)
        except Exception:  # noqa: BLE001  自动同步失败不打断使用，可在同步页查看记录
            pass

    def _after_sync_download(self):
        self.state.settings = settings.load_settings()
        try:
            self.refresh_current()
        except Exception:  # noqa: BLE001
            pass
