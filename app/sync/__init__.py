"""数据同步模块：通过 WebDAV 在多台电脑之间同步账套数据。

同步内容：
    <remote_dir>/facturas.db     数据库（SQLite 一致性快照）
    <remote_dir>/settings.json   设置（分店、汇率、期初资本等）
    <remote_dir>/sync_meta.json  云端元信息（更新时间、哈希、设备名）
"""
from app.sync.manager import (DEFAULT_WEBDAV, get_config, save_config,
                              get_state, plan, upload, download, auto_sync,
                              auto_sync_due, mark_auto_synced, test_connection,
                              remote_info, read_log, backup_local)
from app.sync.webdav import WebDAVClient, WebDAVError

__all__ = [
    "DEFAULT_WEBDAV", "get_config", "save_config", "get_state", "plan",
    "upload", "download", "auto_sync", "auto_sync_due", "mark_auto_synced",
    "test_connection", "remote_info", "read_log", "backup_local",
    "WebDAVClient", "WebDAVError",
]
