"""极简 WebDAV 客户端（仅依赖标准库 urllib，无需额外安装 requests）。

兼容常见服务：坚果云、Nextcloud / ownCloud、群晖 WebDAV Server、Box 等。
用到的方法：PROPFIND（查文件信息）、GET、PUT、MKCOL、DELETE。
"""
import base64
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote
from xml.etree import ElementTree as ET

DAV = "{DAV:}"


class WebDAVError(Exception):
    """WebDAV 请求失败。"""


class WebDAVClient:
    def __init__(self, base_url, username="", password="", timeout=20,
                 verify_ssl=True):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    # ------------------------------------------------------------ 基础
    def _url(self, path="") -> str:
        if not self.base_url:
            raise WebDAVError("未配置 WebDAV 服务器地址")
        rel = (path or "").strip("/")
        if not rel:
            return self.base_url + "/"
        parts = [quote(p, safe="") for p in rel.split("/") if p]
        return self.base_url + "/" + "/".join(parts)

    def _open(self, req):
        ctx = None
        if self.base_url.lower().startswith("https"):
            ctx = ssl.create_default_context()
            if not self.verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=self.timeout, context=ctx)

    def _request(self, method, path="", data=None, headers=None,
                 allow=(200, 201, 204, 207)):
        url = self._url(path)
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode("utf-8")).decode()
            req.add_header("Authorization", "Basic " + token)
        try:
            with self._open(req) as resp:
                body = resp.read()
                if resp.status not in allow:
                    raise WebDAVError(f"{method} 失败：HTTP {resp.status}")
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise WebDAVError("认证失败（401）：请检查用户名/密码（坚果云需填「应用密码」）") from e
            if e.code == 404:
                raise WebDAVError(f"路径不存在（404）：{url}") from e
            raise WebDAVError(f"{method} 失败：HTTP {e.code} {e.reason}（{url}）") from e
        except urllib.error.URLError as e:
            raise WebDAVError(f"无法连接服务器：{e.reason}（{url}）") from e

    # ------------------------------------------------------------ 操作
    def exists(self, path="") -> bool:
        try:
            self.stat(path)
            return True
        except WebDAVError:
            return False

    def stat(self, path="") -> dict:
        """返回 {size, mtime, etag}；不存在时抛 WebDAVError。"""
        _st, body, _h = self._request("PROPFIND", path, headers={"Depth": "0"})
        return _parse_propfind(body)

    def mkdirs(self, path=""):
        """逐级创建目录，已存在则跳过。"""
        parts = [p for p in (path or "").strip("/").split("/") if p]
        cur = ""
        for p in parts:
            cur = f"{cur}/{p}" if cur else p
            try:
                self._request("MKCOL", cur, allow=(200, 201, 204, 207, 405))
            except WebDAVError:
                if not self.exists(cur):
                    raise

    def put(self, path, data: bytes):
        self._request("PUT", path, data=data,
                      headers={"Content-Type": "application/octet-stream"})

    def get(self, path) -> bytes:
        _st, body, _h = self._request("GET", path)
        return body

    def delete(self, path):
        self._request("DELETE", path, allow=(200, 201, 204, 207, 404))


def _parse_propfind(body: bytes) -> dict:
    """解析 PROPFIND 响应，提取文件大小/修改时间/ETag。"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise WebDAVError(f"无法解析服务器响应：{e}") from e
    resp = root.find(f"{DAV}response")
    if resp is None:
        raise WebDAVError("服务器响应中未找到文件信息")

    def prop(name, default=""):
        node = resp.find(f".//{DAV}{name}")
        return (node.text or default) if node is not None else default

    size = str(prop("getcontentlength", "0")).strip()
    return {
        "size": int(size) if size.isdigit() else 0,
        "mtime": prop("getlastmodified", ""),
        "etag": (prop("getetag", "") or "").strip('"'),
    }
