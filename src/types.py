"""
Compatibility shim for stdlib `types` plus Artemis-City custom type aliases.

This file re-exports the standard library `types` module API while also exposing
project-specific types from `my_types.py`. It avoids breaking stdlib imports
when `src/` is on `sys.path` by loading the real stdlib module by file path.
"""

from __future__ import annotations

from importlib import util as _importlib_util
import sysconfig as _sysconfig
from pathlib import Path as _Path


def _load_stdlib_types_module():
    stdlib_dir = _sysconfig.get_paths().get("stdlib")
    if not stdlib_dir:
        raise RuntimeError("Unable to locate stdlib path for types.py")
    stdlib_types_path = _Path(stdlib_dir) / "types.py"
    if not stdlib_types_path.exists():
        raise RuntimeError(f"Stdlib types.py not found at {stdlib_types_path}")
    spec = _importlib_util.spec_from_file_location("_stdlib_types", stdlib_types_path)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to create spec for stdlib types module")
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_stdlib_types = _load_stdlib_types_module()

# Populate globals with stdlib types API first
for _name, _value in _stdlib_types.__dict__.items():
    if _name in {"__spec__", "__loader__", "__package__", "__cached__"}:
        continue
    globals().setdefault(_name, _value)

# Import project-specific types (may override stdlib names if necessary)
_custom_all = []
try:
    # Prefer package-relative import when used as src.types
    from .my_types import *  # type: ignore  # noqa: F403,F401
    try:
        from .my_types import __all__ as _custom_all  # type: ignore
    except Exception:
        _custom_all = []
except ModuleNotFoundError:
    # Fallback to absolute import if running with src/ on sys.path
    try:
        from my_types import *  # type: ignore  # noqa: F403,F401
        try:
            from my_types import __all__ as _custom_all  # type: ignore
        except Exception:
            _custom_all = []
    except ModuleNotFoundError:
        # If project-specific types are absent, continue with stdlib types only.
        _custom_all = []

__all__ = list(getattr(_stdlib_types, "__all__", []))
for _name in _custom_all:
    if _name not in __all__:
        __all__.append(_name)
