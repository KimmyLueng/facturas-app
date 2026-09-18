"""OCR 引擎封装：优先 PaddleOCR（西班牙语），可回退到 Tesseract。"""
import os
import sys
import tempfile
import threading

from app import config
from app.utils import parse_amount  # noqa: F401  复用金额解析


class OCREngine:
    """懒加载 OCR 引擎，支持 PaddleOCR 2.x 与 3.x API。"""

    def __init__(self, lang: str = None):
        self.lang = lang or config.OCR_LANG
        self._engine = None
        self._backend = None
        self._lock = threading.Lock()
        self.error = None

    # ------------------------------------------------------------ 引擎加载
    def _lazy_load(self):
        if self._engine is not None:
            return True
        with self._lock:
            if self._engine is not None:
                return True
            try:
                from paddleocr import PaddleOCR
                # PaddleOCR 3.x 参数；2.x 会忽略未知参数（部分版本会报错，用 try 回退）
                try:
                    self._engine = PaddleOCR(
                        lang=self.lang,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                except TypeError:
                    self._engine = PaddleOCR(lang=self.lang)
                self._backend = "paddle"
                self.error = None
                return True
            except Exception as e:  # noqa: BLE001
                import traceback
                # 记录完整调用栈，便于诊断打包缺失依赖等问题
                try:
                    log_dir = config.APP_DIR
                    log_path = os.path.join(log_dir, "ocr_error.log")
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(f"OCR 引擎加载失败: {e}\n\n")
                        traceback.print_exc(file=f)
                except Exception:  # noqa: BLE001
                    pass
                hint = ""
                if getattr(sys, "frozen", False) and (
                    "pipeline" in str(e).lower() or "does not exist" in str(e)
                ):
                    hint = "（打包版缺少 paddlex 资源配置，请用最新 build.ps1 重新打包）"
                if "dependency" in str(e).lower():
                    hint += "（依赖检查失败，请用最新 build.ps1 重新打包，详细原因见 ocr_error.log）"
                self.error = f"PaddleOCR 加载失败: {e}{hint}"
        return False

    def load(self) -> bool:
        """显式加载 OCR 引擎（首次会下载模型）。"""
        return self._lazy_load()

    @property
    def backend(self):
        return self._backend or "未加载"

    # ------------------------------------------------------------ 识别
    def recognize(self, image_path: str) -> list:
        """识别图片，返回文本行列表 ['line1', 'line2', ...]"""
        if not self._lazy_load():
            return []
        try:
            result = self._engine.predict(image_path)  # PaddleOCR 3.x
            return self._extract_texts_v3(result)
        except (AttributeError, TypeError):
            try:
                result = self._engine.ocr(image_path, cls=False)  # PaddleOCR 2.x
                texts = []
                for page in result:
                    for line in page or []:
                        texts.append(line[1][0])
                return texts
            except Exception as e:  # noqa: BLE001
                self.error = f"OCR 识别失败: {e}"
                return []

    @staticmethod
    def _extract_texts_v3(result) -> list:
        texts = []
        for res in result or []:
            data = getattr(res, "json", None)
            if data is None and isinstance(res, dict):
                data = res
            # 递归查找 rec_texts
            found = OCREngine._find_key(data, "rec_texts")
            if found:
                texts.extend(str(t) for t in found if t)
        return texts

    @staticmethod
    def _find_key(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = OCREngine._find_key(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                r = OCREngine._find_key(v, key)
                if r is not None:
                    return r
        return None


# ---------------------------------------------------------------- PDF 支持
def pdf_to_images(pdf_path: str, max_pages: int = 20) -> list:
    """将 PDF 每页渲染为临时 PNG，返回文件路径列表。"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    images = []
    doc = fitz.open(pdf_path)
    tmpdir = tempfile.mkdtemp(prefix="facturas_pdf_")
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=200)
        out = os.path.join(tmpdir, f"page_{i:03d}.png")
        pix.save(out)
        images.append(out)
    doc.close()
    return images
