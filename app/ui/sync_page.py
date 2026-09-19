"""数据同步页：WebDAV 配置、上传 / 恢复、自动同步与同步记录。"""
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app import config, settings
from app.sync import manager


class SyncPage:
    def __init__(self, app):
        self.app = app
        self.frame = None
        self.busy = False

    # ------------------------------------------------------------ 界面
    def build(self):
        f = self.frame
        pad = {"padx": 14, "pady": 8}
        cfg = manager.get_config()

        # ---------------- 服务器配置
        srv = ttk.LabelFrame(f, text="WebDAV 服务器")
        srv.pack(fill="x", **pad)

        r0 = ttk.Frame(srv)
        r0.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(r0, text="服务器地址：").pack(side="left")
        self.url_var = tk.StringVar(value=cfg.get("url", ""))
        ttk.Entry(r0, textvariable=self.url_var, width=54).pack(side="left", padx=8)

        r1 = ttk.Frame(srv)
        r1.pack(fill="x", padx=10, pady=4)
        ttk.Label(r1, text="用户名：").pack(side="left")
        self.user_var = tk.StringVar(value=cfg.get("user", ""))
        ttk.Entry(r1, textvariable=self.user_var, width=22).pack(side="left", padx=8)
        ttk.Label(r1, text="密码：").pack(side="left", padx=(14, 0))
        self.pwd_var = tk.StringVar(value=cfg.get("password", ""))
        ttk.Entry(r1, textvariable=self.pwd_var, width=22, show="*").pack(side="left", padx=8)
        ttk.Label(r1, text="（坚果云需填「应用密码」，不是登录密码）",
                  foreground="gray").pack(side="left", padx=8)

        r2 = ttk.Frame(srv)
        r2.pack(fill="x", padx=10, pady=4)
        ttk.Label(r2, text="云端目录：").pack(side="left")
        self.dir_var = tk.StringVar(value=cfg.get("remote_dir", "GestionFacturas"))
        ttk.Entry(r2, textvariable=self.dir_var, width=28).pack(side="left", padx=8)
        self.ssl_var = tk.BooleanVar(value=bool(cfg.get("verify_ssl", True)))
        ttk.Checkbutton(r2, text="校验 SSL 证书（自签证书可取消勾选）",
                        variable=self.ssl_var).pack(side="left", padx=14)

        r3 = ttk.Frame(srv)
        r3.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Button(r3, text="测试连接", command=self._test).pack(side="left")
        ttk.Button(r3, text="保存配置", command=self._save_config).pack(side="left", padx=8)
        self.conn_var = tk.StringVar(value="")
        ttk.Label(r3, textvariable=self.conn_var, foreground="#1f6feb").pack(
            side="left", padx=10)

        # ---------------- 同步操作
        syn = ttk.LabelFrame(f, text="同步")
        syn.pack(fill="x", **pad)

        r4 = ttk.Frame(syn)
        r4.pack(fill="x", padx=10, pady=(10, 6))
        self.enabled_var = tk.BooleanVar(value=bool(cfg.get("enabled")))
        ttk.Checkbutton(r4, text="启用同步", variable=self.enabled_var).pack(side="left")
        self.auto_var = tk.BooleanVar(value=bool(cfg.get("auto_sync")))
        ttk.Checkbutton(r4, text="自动同步（每",
                        variable=self.auto_var).pack(side="left", padx=(16, 0))
        self.interval_var = tk.StringVar(value=str(cfg.get("interval_min", 30)))
        ttk.Combobox(r4, textvariable=self.interval_var, width=5, state="readonly",
                     values=["15", "30", "60", "120"]).pack(side="left")
        ttk.Label(r4, text="分钟检查一次）").pack(side="left")
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r4, text="忽略冲突提示（强制覆盖）",
                        variable=self.force_var).pack(side="left", padx=(16, 0))

        r5 = ttk.Frame(syn)
        r5.pack(fill="x", padx=10, pady=4)
        ttk.Button(r5, text="上传到云端", command=self._upload).pack(side="left")
        ttk.Button(r5, text="从云端恢复", command=self._download).pack(side="left", padx=8)
        ttk.Button(r5, text="立即同步（智能判断方向）",
                   command=self._auto).pack(side="left", padx=8)
        ttk.Button(r5, text="刷新状态", command=self.refresh).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="")
        ttk.Label(r5, textvariable=self.status_var).pack(side="left", padx=10)

        self.info_var = tk.StringVar(value="")
        ttk.Label(syn, textvariable=self.info_var, foreground="#333",
                  justify="left", wraplength=920).pack(anchor="w", padx=12, pady=(0, 10))

        # ---------------- 同步记录
        lg = ttk.LabelFrame(f, text="同步记录（最近 200 条）")
        lg.pack(fill="both", expand=True, **pad)
        lg.columnconfigure(0, weight=1)
        lg.rowconfigure(0, weight=1)
        cols = (("time", "时间", 150), ("action", "操作", 70),
                ("result", "结果", 60), ("message", "说明", 520))
        self.log_tree = ttk.Treeview(lg, columns=[c[0] for c in cols],
                                     show="headings", height=8)
        for key, text, width in cols:
            self.log_tree.heading(key, text=text)
            self.log_tree.column(key, width=width, anchor="w")
        self.log_tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(lg, orient="vertical", command=self.log_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.log_tree.configure(yscrollcommand=vsb.set)

        note = tk.Text(f, height=4, wrap="word", font=("Microsoft YaHei UI", 9),
                       foreground="#333", relief="flat", bg=self.frame.cget("bg"))
        note.insert("1.0",
                    "说明：\n"
                    "· 同步内容为本机账套：数据库 + 设置（分店、汇率、期初资本）；"
                    "恢复时会自动备份本机数据库到 data/backups/；\n"
                    "· 两台电脑不要同时录入同一天数据，先同步再录入，避免冲突；"
                    "出现冲突时请手动选择「上传」或「从云端恢复」；\n"
                    "· 重新安装的 App（本机无数据）首次同步会提示「从云端恢复」，"
                    "直接点该按钮即可，无需勾选强制覆盖；\n"
                    f"· 本机数据库：{config.DB_PATH}")
        note.config(state="disabled")
        note.pack(anchor="w", fill="x", padx=14, pady=(0, 10))

        self.refresh()

    # ------------------------------------------------------------ 配置
    def _form_config(self) -> dict:
        return {
            "enabled": bool(self.enabled_var.get()),
            "url": self.url_var.get().strip(),
            "user": self.user_var.get().strip(),
            "password": self.pwd_var.get(),
            "remote_dir": self.dir_var.get().strip() or "GestionFacturas",
            "verify_ssl": bool(self.ssl_var.get()),
            "auto_sync": bool(self.auto_var.get()),
            "interval_min": int(self.interval_var.get() or 30),
        }

    def _persist_config(self) -> dict:
        """把表单配置落盘并返回。"""
        cfg = self._form_config()
        manager.save_config(cfg)
        self.app.state.settings = settings.load_settings()
        return cfg

    def _save_config(self):
        try:
            self._persist_config()
            self.conn_var.set("✔ 配置已保存")
            messagebox.showinfo("已保存", "WebDAV 配置已保存。", parent=self.frame)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self.frame)

    # ------------------------------------------------------------ 异步任务
    def _run_async(self, label, fn):
        if self.busy:
            return
        self.busy = True
        self.status_var.set(label)
        self.frame.update_idletasks()

        def worker():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "message": f"{type(e).__name__}: {e}"}
            self.app.after(0, lambda: self._done(res))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, res):
        self.busy = False
        res = res or {}
        ok = bool(res.get("ok"))
        self.status_var.set(("✔ " if ok else "✗ ") + (res.get("message") or ""))
        if not ok and res.get("action") in ("conflict", "download", "upload"):
            self.conn_var.set("")
        self.refresh()
        if ok and res.get("action") == "download":
            # 数据库已被替换：重新加载设置并刷新当前页
            self.app.state.settings = settings.load_settings()
            try:
                self.app.refresh_current()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 操作
    def _test(self):
        cfg = self._persist_config()
        self._run_async("正在测试连接…", lambda: _as_result(manager.test_connection(cfg)))

    def _upload(self):
        self._persist_config()
        force = bool(self.force_var.get())
        self._run_async("正在上传到云端…", lambda: manager.upload(force=force))

    def _download(self):
        self._persist_config()
        force = bool(self.force_var.get())
        self._run_async("正在从云端恢复…", lambda: manager.download(force=force))

    def _auto(self):
        self._persist_config()
        self._run_async("正在同步…", lambda: manager.auto_sync())

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        cfg = manager.get_config()
        self.url_var.set(cfg.get("url", ""))
        self.user_var.set(cfg.get("user", ""))
        self.pwd_var.set(cfg.get("password", ""))
        self.dir_var.set(cfg.get("remote_dir", "GestionFacturas"))
        self.ssl_var.set(bool(cfg.get("verify_ssl", True)))
        self.enabled_var.set(bool(cfg.get("enabled")))
        self.auto_var.set(bool(cfg.get("auto_sync")))
        self.interval_var.set(str(cfg.get("interval_min", 30)))

        st = manager.get_state()
        last = st.get("last_sync_at", "")
        direction = {"upload": "上传", "download": "恢复"}.get(
            st.get("last_direction", ""), "-")
        info = manager.remote_info()
        if info:
            cloud = (f"云端：更新于 {info.get('updated_at', '未知')}"
                     f"，{int(info.get('db_size', 0)) / 1024:.0f} KB"
                     f"，设备 {info.get('device', '未知')}")
        else:
            cloud = "云端：暂无备份（或不可用）"
        plan_msg = ""
        if cfg.get("url"):
            try:
                p = manager.plan()
                plan_msg = "建议：" + (p.get("message") or "")
            except Exception:  # noqa: BLE001
                plan_msg = ""
        self.info_var.set(
            f"上次同步：{last or '从未同步'}（{direction}）    {cloud}\n"
            f"本机数据库：{int(_db_size()) / 1024:.0f} KB"
            f"    自动同步：{'开启' if cfg.get('auto_sync') else '关闭'}"
            f"（每 {cfg.get('interval_min', 30)} 分钟）"
            + (f"\n{plan_msg}" if plan_msg else ""))

        self.log_tree.delete(*self.log_tree.get_children())
        for r in manager.read_log():
            self.log_tree.insert("", "end", values=(
                r.get("time", ""), r.get("action", ""),
                "成功" if r.get("ok") else "失败", r.get("message", "")))


def _db_size() -> int:
    try:
        return os.path.getsize(config.DB_PATH)
    except OSError:
        return 0


def _as_result(pair) -> dict:
    """test_connection 的 (ok, msg) 元组 → 统一结果字典。"""
    ok, msg = pair
    return {"ok": ok, "message": msg}
