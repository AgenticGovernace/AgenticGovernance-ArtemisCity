import sys, types, importlib.util, inspect, re, traceback, py_compile

REPO = "/sessions/gracious-quirky-carson/mnt/AgenticGovernance-ArtemisCity"
sys.path.insert(0, REPO)

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
        assert et and issubclass(
            et, self.exc
        ), f"expected {self.exc.__name__}, got {et}"
        if self.match:
            assert re.search(self.match, str(ev)), f"{self.match!r} not in {str(ev)!r}"
        return True


pytest.raises = lambda exc, match=None: _Raises(exc, match)
sys.modules["pytest"] = pytest

print("=== compile ===")
for f in [
    "src/mcp/orchestrator.py",
    "src/agents/llm_agent.py",
    "src/launch/main.py",
    "src/integration/hebbian_router.py",
    "src/tests/test_hebbian_router.py",
]:
    try:
        py_compile.compile(f"{REPO}/{f}", doraise=True)
        print("  OK  ", f)
    except Exception as e:
        print("  FAIL", f, "->", e)

print("\n=== router unit tests ===")
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
        print("  PASS", name)
    except Exception:
        fail += 1
        print("  FAIL", name)
        traceback.print_exc()
print(f"  {total-fail}/{total} passed")

print("\n=== real capability map + fallback=llm_chat ===")
from src.integration.hebbian_router import HebbianRouter


class A:
    def __init__(s, n, c):
        s.name = n
        s.capabilities = c


class S:
    def __init__(s, c):
        s.composite_score = c


class Reg:
    def __init__(s):
        s._a = [
            A("Artemis Agent", ["system_management", "agent_coordination"]),
            A("Research Agent", ["web_search", "document_analysis"]),
            A("Summarizer Agent", ["text_summarization"]),
            A(
                "LLM Agent",
                [
                    "llm_chat",
                    "text_generation",
                    "reasoning",
                    "chat",
                    "general",
                    "inference",
                ],
            ),
        ]
        s.scores = {x.name: S(0.5) for x in s._a}

    def get_all_agents(s):
        return s._a

    def get_governance_state(s, n):
        return {"status": "active"}

    def is_quarantined(s, n):
        return False


class Heb:
    def get_agent_average_weight(s, n):
        return 0.0


r = HebbianRouter(Reg(), Heb(), fallback_capability="llm_chat")
for cap in ["web_search", "general", "chitchat", "inference"]:
    print(
        f"  required_capability={cap!r:12} -> {r.route_name({'required_capability':cap})}"
    )
print(f"  (no capability)            -> {r.route_name({'title':'hi'})}")
