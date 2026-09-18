"""检查 OCR pipeline 依赖的安装状态（打包诊断用）。"""
import importlib.metadata as m

pkgs = [
    "opencv-contrib-python", "opencv-python", "pyclipper", "shapely",
    "pypdfium2", "python-bidi", "imagesize", "safetensors", "scipy",
    "scikit-learn", "regex", "tiktoken", "sentencepiece", "tokenizers",
    "ftfy", "einops", "Jinja2", "lxml", "premailer", "openpyxl",
    "latex2mathml", "beautifulsoup4", "numpy", "PyYAML", "paddlepaddle",
    "paddlex", "paddleocr", "requests", "huggingface-hub", "prettytable",
    "py-cpuinfo", "ruamel.yaml", "ujson", "packaging", "filelock",
    "chardet", "colorlog", "aistudio-sdk", "pydantic", "pandas",
    "pillow", "typing-extensions", "modelscope", "paddle",
]
for p in pkgs:
    try:
        v = m.version(p)
    except Exception:
        v = "-"
    print(f"{p}: {v}")
