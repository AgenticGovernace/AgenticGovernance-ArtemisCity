import sys, types, importlib.util, inspect, re, traceback, py_compile

REPO = "/sessions/gracious-quirky-carson/mnt/AgenticGovernance-ArtemisCity"
sys.path.insert(0, REPO)

# --- minimal pytest shim ---
pytest = types.ModuleType("pytest")


class _Mark:
    def __getattr__(self, _):
        return lambda fn: fn


pytest.mark = _Mark()


class _Raises:
    def __init__(self, exc, match=None):
        self.exc, self.match = exc, match

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(
            et, self.exc
        ), f"expected {self.exc.__name__}, got {et}"
        if self.match:
            assert re.search(self.match, str(ev)), f"{self.match!r} not in {str(ev)!r}"
        return True


pytest.raises = lambda exc, match=None: _Raises(exc, match)
sys.modules["pytest"] = pytest

# --- syntax compile checks (catches the orchestrator edits) ---
for f in [
    "src/mcp/orchestrator.py",
    "src/integration/hebbian_router.py",
    "src/tests/test_hebbian_router.py",
]:
    try:
        py_compile.compile(f"{REPO}/{f}", doraise=True)
        print("COMPILE OK ", f)
    except Exception as e:
        print("COMPILE FAIL", f, "->", e)

# --- run the real test file ---
spec = importlib.util.spec_from_file_location(
    "t_hr", f"{REPO}/src/tests/test_hebbian_router.py"
)
m = importlib.util.module_from_spec(spec)
sys.modules["t_hr"] = m
spec.loader.exec_module(m)
total = fail = 0
for name, fn in sorted(inspect.getmembers(m, inspect.isfunction)):
    if not name.startswith("test_"):
        continue
    total += 1
    try:
        fn()
        print("PASS ", name)
    except Exception:
        fail += 1
        print("FAIL ", name)
        traceback.print_exc()
print(f"\n{total-fail}/{total} router tests passed")
