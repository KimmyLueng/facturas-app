"""同步管理器：本机账套 ⇄ WebDAV 云端。

同步内容：
    <remote_dir>/facturas.db      数据库（SQLite 一致性快照，避免写到一半的文件）
    <remote_dir>/settings.json    设置（分店、汇率、期初资本等）
    <remote_dir>/sync_meta.json   云端元信息（更新时间、哈希、设备名）

冲突判定（以上次同步时的本地/云端哈希为基线）：
    只有本地改  → 上传
    只有云端改  → 下载
    两边都改    → 冲突，需手动选择方向（强制上传 / 强制恢复）
    都没改      → 已是最新
    首次同步 + 本机空账套 → 下载（重新安装的 App 直接「从云端恢复」即可）
    首次同步 + 本机有数据 → 冲突，需手动选择方向
"""
import base64
import datetime
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import tempfile

from app import config, settings
from app.sync.webdav import WebDAVClient, WebDAVError

DB_NAME = "facturas.db"
SETTINGS_NAME = "settings.json"
META_NAME = "sync_meta.json"
SQLITE_MAGIC = b"SQLite format 3\x00"
BACKUP_KEEP = 10
MAX_LOG = 200

DEFAULT_WEBDAV = {
    "enabled": False,      # 启用同步
    "url": "",             # 服务器地址，如 https://dav.jianguoyun.com/dav/
    "user": "",
    "password": "",        # 混淆后存储（非加密，仅避免明文直读）
    "remote_dir": "GestionFacturas",
    "verify_ssl": True,
    "auto_sync": False,    # 自动同步
    "interval_min": 30,    # 自动同步间隔（分钟）
}


# ------------------------------------------------------------------ 配置
def _encode_pwd(p: str) -> str:
    return base64.b64encode((p or "")[::-1].encode("utf-8")).decode("ascii")


def _decode_pwd(s: str) -> str:
    try:
        return base64.b64decode((s or "").encode("ascii")).decode("utf-8")[::-1]
    except Exception:  # noqa: BLE001
        return ""


def get_config() -> dict:
    """当前同步配置（密码为明文，供界面显示）。"""
    s = settings.load_settings()
    cfg = dict(DEFAULT_WEBDAV)
    cfg.update(s.get("webdav") or {})
    cfg["password"] = _decode_pwd(cfg.get("password", ""))
    return cfg


def save_config(cfg: dict):
    """保存同步配置（密码混淆后落盘）。"""
    s = settings.load_settings()
    data = dict(DEFAULT_WEBDAV)
    data.update({k: v for k, v in (cfg or {}).items() if k in DEFAULT_WEBDAV})
    data["password"] = _encode_pwd(cfg.get("password", ""))
    s["webdav"] = data
    settings.save_settings(s)


def get_state() -> dict:
    """同步基线状态。"""
    return dict(settings.load_settings().get("sync_state") or {})


def _set_state(**kw) -> dict:
    s = settings.load_settings()
    st = dict(s.get("sync_state") or {})
    st.update(kw)
    s["sync_state"] = st
    settings.save_settings(s)
    return st


# ------------------------------------------------------------------ 客户端
def get_client(cfg: dict = None) -> WebDAVClient:
    cfg = cfg or get_config()
    if not (cfg.get("url") or "").strip():
        raise WebDAVError("尚未配置 WebDAV 服务器地址")
    return WebDAVClient(cfg["url"].strip(), cfg.get("user", ""),
                        cfg.get("password", ""),
                        verify_ssl=bool(cfg.get("verify_ssl", True)))


def _remote(cfg: dict, name: str) -> str:
    d = (cfg.get("remote_dir") or "GestionFacturas").strip("/")
    return f"{d}/{name}" if d else name


def _remote_dir(cfg: dict) -> str:
    return (cfg.get("remote_dir") or "GestionFacturas").strip("/")


# ------------------------------------------------------------------ 工具
def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_hash() -> str:
    if not os.path.exists(config.DB_PATH):
        return ""
    try:
        return file_md5(config.DB_PATH)
    except OSError:
        return ""


# 业务数据表（不含内置的科目表 chart_of_accounts）
_DATA_TABLES = ("documents", "daily_income", "daily_income_rows",
                "daily_expense", "daily_expense_items",
                "supplier_settlements", "opening_balances",
                "products", "stock_moves")


def has_local_data() -> bool:
    """本机库是否已有业务数据（全新安装 / 空账套返回 False）。

    重新安装的 App 库里只有表结构，此时应从云端恢复而不是报“冲突”。
    """
    if not os.path.exists(config.DB_PATH):
        return False
    try:
        conn = sqlite3.connect(config.DB_PATH)
    except sqlite3.Error:
        return True          # 打不开就当“有数据”，避免误判后覆盖本机
    try:
        for t in _DATA_TABLES:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                continue     # 旧库可能没有该表
            if n:
                return True
    finally:
        conn.close()
    return False


def make_snapshot() -> str:
    """用 SQLite backup 生成一致性快照，返回临时文件路径（调用方负责删除）。"""
    config.ensure_data_dir()
    fd, tmp = tempfile.mkstemp(prefix="sync_", suffix=".db")
    os.close(fd)
    os.remove(tmp)
    src = sqlite3.connect(config.DB_PATH)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tmp


def backup_local() -> str:
    """把当前数据库备份到 data/backups/，保留最近 BACKUP_KEEP 个。"""
    config.ensure_data_dir()
    d = os.path.join(config.DATA_DIR, "backups")
    os.makedirs(d, exist_ok=True)
    name = "facturas-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    dst = os.path.join(d, name)
    if os.path.exists(config.DB_PATH):
        shutil.copy2(config.DB_PATH, dst)
        _prune_backups(d)
    return dst


def _prune_backups(d: str):
    try:
        files = sorted(
            (f for f in os.listdir(d) if f.startswith("facturas-")),
            reverse=True)
        for f in files[BACKUP_KEEP:]:
            os.remove(os.path.join(d, f))
    except OSError:
        pass


# ------------------------------------------------------------------ 日志
def _log_path() -> str:
    return os.path.join(config.DATA_DIR, "sync_log.json")


def log(action: str, ok: bool, message: str):
    """写入同步日志（最新在前，最多 MAX_LOG 条）。"""
    try:
        config.ensure_data_dir()
        logs = read_log()
    except Exception:  # noqa: BLE001
        logs = []
    logs.insert(0, {
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "ok": bool(ok),
        "message": message,
    })
    logs = logs[:MAX_LOG]
    try:
        with open(_log_path(), "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return logs


def read_log() -> list:
    try:
        with open(_log_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


# ------------------------------------------------------------------ 云端信息
def remote_info(cfg: dict = None) -> dict:
    """云端元信息；不存在或失败返回 {}。"""
    cfg = cfg or get_config()
    try:
        data = get_client(cfg).get(_remote(cfg, META_NAME))
        return json.loads(data.decode("utf-8"))
    except (WebDAVError, ValueError, UnicodeDecodeError):
        return {}


def plan() -> dict:
    """判断当前应执行的同步动作。"""
    cfg = get_config()
    if not (cfg.get("url") or "").strip():
        return {"action": "no-config", "message": "尚未配置 WebDAV 服务器"}
    st = get_state()
    local_hash = _local_hash()
    base_local = st.get("local_hash", "")
    base_remote = st.get("remote_hash", "")
    try:
        info = remote_info(cfg)
    except WebDAVError as e:
        return {"action": "error", "message": str(e),
                "local_hash": local_hash}
    remote_hash = info.get("db_hash", "")
    base = {"local_hash": local_hash, "remote_hash": remote_hash,
            "remote_info": info, "local_changed": local_hash != base_local,
            "remote_changed": remote_hash != base_remote}

    if not remote_hash:
        if not local_hash:
            return {**base, "action": "in-sync", "message": "本地与云端均无数据"}
        return {**base, "action": "upload",
                "message": "云端尚无备份，建议上传本地数据"}
    if not base_local and not base_remote:
        # 全新安装（本机空账套）+ 云端已有备份 → 直接建议恢复，不算冲突
        if not has_local_data():
            return {**base, "action": "download",
                    "message": "本机是空账套（未录入数据），云端已有备份"
                               f"（{info.get('updated_at', '未知时间')}，"
                               f"设备 {info.get('device', '未知')}），"
                               "建议点击「从云端恢复」"}
        return {**base, "action": "conflict",
                "message": "云端已有数据且本机未同步过，请手动选择「上传」或「从云端恢复」"}
    if base["local_changed"] and base["remote_changed"]:
        return {**base, "action": "conflict",
                "message": "本地与云端都有新改动（冲突），请手动选择方向"}
    if base["local_changed"]:
        return {**base, "action": "upload", "message": "本地有新改动，建议上传"}
    if base["remote_changed"]:
        return {**base, "action": "download",
                "message": f"云端有新数据（{info.get('updated_at', '未知时间')}），建议恢复到本地"}
    return {**base, "action": "in-sync", "message": "本地与云端一致"}


# ------------------------------------------------------------------ 上传
def upload(force: bool = False) -> dict:
    """上传本地数据库与设置到云端。"""
    cfg = get_config()
    if not (cfg.get("url") or "").strip():
        return {"ok": False, "action": "no-config", "message": "尚未配置 WebDAV 服务器"}
    p = plan()
    if not force and p["action"] == "conflict":
        return {"ok": False, "action": "conflict",
                "message": f"{p['message']}；确认覆盖请点击「强制上传」"}
    if not force and p["action"] == "download":
        return {"ok": False, "action": "download",
                "message": f"{p['message']}；确认覆盖请点击「强制上传」"}
    if not os.path.exists(config.DB_PATH):
        return {"ok": False, "message": "本地数据库不存在，无法上传"}

    snap = None
    try:
        snap = make_snapshot()
        h = file_md5(snap)
        size = os.path.getsize(snap)
        client = get_client(cfg)
        client.mkdirs(_remote_dir(cfg))
        with open(snap, "rb") as f:
            client.put(_remote(cfg, DB_NAME), f.read())
        s = settings.load_settings()
        client.put(_remote(cfg, SETTINGS_NAME),
                   json.dumps(s, ensure_ascii=False, indent=2).encode("utf-8"))
        meta = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "db_hash": h,
            "db_size": size,
            "device": socket.gethostname(),
            "app": "GestionFacturas",
        }
        client.put(_remote(cfg, META_NAME),
                   json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    except WebDAVError as e:
        log("上传", False, str(e))
        _set_state(last_result="error", last_message=str(e))
        return {"ok": False, "action": "upload", "message": str(e)}
    except OSError as e:
        log("上传", False, f"读取本地数据库失败：{e}")
        return {"ok": False, "action": "upload", "message": f"读取本地数据库失败：{e}"}
    finally:
        if snap and os.path.exists(snap):
            try:
                os.remove(snap)
            except OSError:
                pass

    now = datetime.datetime.now().isoformat(timespec="seconds")
    # 注意：云端保存的是快照（hash=h），本机基线取当前库文件 hash
    # （快照与源文件字节可能不同，不能互为基线，否则会误判“本地已改动”）
    _set_state(last_sync_at=now, last_direction="upload",
               local_hash=_local_hash(), remote_hash=h,
               last_result="ok", last_message="已上传到云端")
    log("上传", True, f"已上传数据库（{size} 字节）")
    return {"ok": True, "action": "upload", "size": size,
            "message": f"已上传到云端（{size / 1024:.0f} KB）"}


# ------------------------------------------------------------------ 下载
def download(force: bool = False) -> dict:
    """从云端恢复数据库到本地（自动备份当前库）。"""
    cfg = get_config()
    if not (cfg.get("url") or "").strip():
        return {"ok": False, "action": "no-config", "message": "尚未配置 WebDAV 服务器"}
    p = plan()
    if not force and p["action"] in ("upload", "conflict"):
        return {"ok": False, "action": "conflict",
                "message": f"{p['message']}；确认覆盖本地请点击「强制恢复」"}

    client = get_client(cfg)
    try:
        data = client.get(_remote(cfg, DB_NAME))
    except WebDAVError as e:
        log("恢复", False, str(e))
        _set_state(last_result="error", last_message=str(e))
        return {"ok": False, "action": "download", "message": str(e)}
    if not data.startswith(SQLITE_MAGIC):
        msg = "云端文件不是有效的 SQLite 数据库，已取消恢复"
        log("恢复", False, msg)
        return {"ok": False, "action": "download", "message": msg}

    try:
        backup_local()
        tmp = config.DB_PATH + ".download"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, config.DB_PATH)
    except OSError as e:
        msg = f"写入本地数据库失败：{e}"
        log("恢复", False, msg)
        return {"ok": False, "action": "download", "message": msg}

    # 设置：合并云端内容，但保留本机的 WebDAV 配置与同步状态
    try:
        remote_settings = json.loads(
            client.get(_remote(cfg, SETTINGS_NAME)).decode("utf-8"))
        _merge_remote_settings(remote_settings)
    except (WebDAVError, ValueError, UnicodeDecodeError):
        pass

    h = hashlib.md5(data).hexdigest()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    _set_state(last_sync_at=now, last_direction="download", local_hash=h,
               remote_hash=h, last_result="ok", last_message="已从云端恢复")
    log("恢复", True, f"已从云端恢复（{len(data) / 1024:.0f} KB）")
    return {"ok": True, "action": "download", "size": len(data),
            "message": f"已从云端恢复（{len(data) / 1024:.0f} KB），本地旧库已备份"}


def _merge_remote_settings(remote: dict):
    """合并云端设置：同步业务字段，保留本机的 WebDAV 配置与同步状态。"""
    if not isinstance(remote, dict):
        return
    local = settings.load_settings()
    merged = dict(remote)
    merged["webdav"] = local.get("webdav", {})
    merged["sync_state"] = local.get("sync_state", {})
    settings.save_settings(merged)


# ------------------------------------------------------------------ 自动同步
def auto_sync_due() -> bool:
    """是否到了自动同步的时间。"""
    cfg = get_config()
    if not (cfg.get("enabled") and cfg.get("auto_sync")):
        return False
    if not (cfg.get("url") or "").strip():
        return False
    st = get_state()
    last = st.get("last_auto_at", "")
    if not last:
        return True
    try:
        t0 = datetime.datetime.fromisoformat(last)
    except ValueError:
        return True
    interval = int(cfg.get("interval_min") or 30)
    return (datetime.datetime.now() - t0).total_seconds() >= interval * 60


def mark_auto_synced():
    return _set_state(
        last_auto_at=datetime.datetime.now().isoformat(timespec="seconds"))


def auto_sync() -> dict:
    """智能同步：无冲突时自动上传/下载，冲突则不动作并返回提示。"""
    p = plan()
    if p["action"] == "upload":
        return upload()
    if p["action"] == "download":
        return download()
    return {"ok": True, "action": p["action"], "message": p.get("message", "")}


# ------------------------------------------------------------------ 连接测试
def test_connection(cfg: dict = None) -> tuple:
    """返回 (是否成功, 提示信息)。"""
    cfg = cfg or get_config()
    if not (cfg.get("url") or "").strip():
        return False, "请先填写 WebDAV 服务器地址"
    try:
        client = get_client(cfg)
        client.stat("")
    except WebDAVError as e:
        return False, str(e)
    try:
        client.mkdirs(_remote_dir(cfg))
        info = remote_info(cfg)
        if info:
            return True, (f"✔ 连接成功；云端数据更新于 "
                          f"{info.get('updated_at', '未知')}"
                          f"（设备：{info.get('device', '未知')}）")
        return True, "✔ 连接成功；云端尚无备份，可直接点击「上传到云端」"
    except WebDAVError:
        # 目录不可创建但根目录可访问时，仍视为连通
        return True, "✔ 服务器连通（远端目录不可自动创建，请确认目录已存在）"
