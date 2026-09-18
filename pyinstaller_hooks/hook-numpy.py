# 覆盖 PyInstaller 内置的 hook-numpy.py。
#
# 原因：本机 site-packages 中残留旧版 numpy 元数据目录（如 numpy-2.5.2.dist-info，
# 而实际安装的 numpy 为 2.5.3），导致 importlib.metadata.version("numpy") 返回 None，
# 内置 hook 执行 Version(None) 时抛 InvalidVersion，打包直接失败。
#
# 本 hook 在元数据不可用时回退到 numpy.__version__，内容与官方 hook 一致。
# 若将来清理了环境（只剩一份 numpy dist-info），可删除本文件恢复使用内置 hook。
# $PyInstaller-Hook-Priority: 2

from PyInstaller import compat
from PyInstaller.utils.hooks import (
    get_installer,
    collect_dynamic_libs,
)

from packaging.version import Version


def _numpy_version():
    """安全获取 numpy 版本：元数据缺失时回退到 numpy.__version__。"""
    v = None
    try:
        v = compat.importlib_metadata.version("numpy")
    except Exception:  # noqa: BLE001
        v = None
    if not v:
        try:
            import numpy  # noqa: F401
            v = numpy.__version__
        except Exception:  # noqa: BLE001
            v = "0.0.0"
    try:
        return Version(v).release
    except Exception:  # noqa: BLE001
        return (0, 0, 0)


numpy_version = _numpy_version()
numpy_installer = get_installer('numpy')

hiddenimports = []
datas = []
binaries = []

# 收集 numpy 包内自带的动态库
binaries += collect_dynamic_libs("numpy")

# Anaconda 版本额外收集依赖 DLL
if numpy_installer == 'conda':
    from PyInstaller.utils.hooks import conda_support
    datas += conda_support.collect_dynamic_libs("numpy", dependencies=True)

# Windows PyPI wheel（delvewheel）的外部 DLL 目录 numpy.libs
if compat.is_win and numpy_version >= (1, 26) and numpy_installer != 'conda':
    from PyInstaller.utils.hooks import collect_delvewheel_libs_directory
    datas, binaries = collect_delvewheel_libs_directory(
        "numpy", datas=datas, binaries=binaries)

# 扩展模块内部导入、PyInstaller 无法静态分析的子模块
if numpy_version >= (2, 0):
    hiddenimports += ['numpy._core._dtype_ctypes', 'numpy._core._multiarray_tests']
else:
    hiddenimports += ['numpy.core._dtype_ctypes']
    if numpy_version >= (1, 25):
        hiddenimports += ['numpy.core._multiarray_tests']

if numpy_version >= (2, 3, 0):
    hiddenimports += ['numpy._core._exceptions']

if compat.is_conda and numpy_version < (1, 19):
    hiddenimports += ["six"]

excludedimports = [
    "scipy",
    "pytest",
    "nose",
    "f2py",
    "setuptools",
]

if numpy_version < (1, 22, 0) or numpy_version > (1, 22, 1):
    excludedimports += [
        "distutils",
        "numpy.distutils",
    ]

if numpy_version < (2, 0):
    excludedimports += [
        "numpy.f2py",
    ]
