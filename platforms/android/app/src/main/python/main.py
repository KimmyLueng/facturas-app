"""Android（Chaquopy）入口：启动内嵌 Web 服务，供 WebView 加载。

由 MainActivity 调用： main.start(data_dir, port) -> 访问地址
"""
import os
import sys
import threading
import time
import urllib.request


def start(data_dir: str, port: int = 8080) -> str:
    """设置数据目录 → 后台启动 Flask → 等待就绪后返回 http://127.0.0.1:port/"""
    os.environ["FACTURAS_DATA_DIR"] = str(data_dir)
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        pass

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from app.web.server import main as web_main

    threading.Thread(
        target=lambda: web_main(["--host", "127.0.0.1", "-p", str(port)]),
        daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    for _ in range(20):                      # 最多等 10 秒
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return url
