"""Execute the real pytest test files without pytest (PyPI blocked in sandbox).
Provides a tiny pytest stand-in (approx/mark/fixture) and supplies tmp_path."""

import sys, types, importlib.util, inspect, tempfile, traceback
from pathlib import Path

REPO = Path("/sessions/gracious-quirky-carson/mnt/AgenticGovernance-ArtemisCity")
sys.path.insert(0, str(REPO))  # canonical: repo root on path, import via src.*


class _Approx:
    def __init__(self, e, rel=1e-6, abs=1e-9):
        self.e, self.rel, self.abs = e, rel, abs

    def __eq__(self, a):
        try:
            return abs(a - self.e) <= max(self.abs, self.rel * abs(self.e))
        except TypeError:
            return NotImplemented

    __hash__ = None

    def __repr__(self):
        return f"approx({self.e})"


class _Mark:
    def __getattr__(self, _):
        def deco(fn):
            return fn

        return deco


pytest = types.ModuleType("pytest")
pytest.approx = lambda e, rel=1e-6, abs=1e-9: _Approx(e, rel, abs)
pytest.mark = _Mark()


def _fixture(*a, **k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


pytest.fixture = _fixture
sys.modules["pytest"] = pytest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


targets = [
    ("t_md", REPO / "src/tests/test_memory_decay.py"),
    ("t_hs", REPO / "src/tests/test_hebbian_sync.py"),
]
total = fail = 0
for modname, path in targets:
    m = load(modname, path)
    for fname, fn in sorted(inspect.getmembers(m, inspect.isfunction)):
        if not fname.startswith("test_"):
            continue
        total += 1
        kwargs = {}
        if "tmp_path" in inspect.signature(fn).parameters:
            kwargs["tmp_path"] = Path(tempfile.mkdtemp())
        try:
            fn(**kwargs)
            print(f"PASS  {fname}")
        except Exception:
            fail += 1
            print(f"FAIL  {fname}")
            traceback.print_exc()
print(f"\n{total - fail}/{total} tests passed")
sys.exit(1 if fail else 0)
