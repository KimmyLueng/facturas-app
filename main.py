"""程序入口：Gestion de Facturas - 西班牙语单据财务管理系统。"""
import sys
import os

# 确保能以 python main.py 从任意目录运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.main_window import MainWindow  # noqa: E402


def _log_dir() -> str:
    """日志目录：打包后为 exe 所在目录，否则为项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        app = MainWindow()
        app.mainloop()
    except Exception:
        # 窗口模式（-w）下无控制台，将异常写入日志并弹窗提示
        import traceback
        log_path = os.path.join(_log_dir(), "error.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            log_path = "(无法写入日志)"
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "程序错误",
                f"程序启动失败。\n详情请查看：\n{log_path}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
