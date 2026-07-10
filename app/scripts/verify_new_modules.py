import sys, importlib.util, glob, json
from pathlib import Path
from datetime import datetime, timedelta, timezone

REPO = Path("/sessions/gracious-quirky-carson/mnt/AgenticGovernance-ArtemisCity")
SRC = REPO / "src"
sys.path.insert(
    0, str(SRC)
)  # makes the `from utils.helpers import logger` fallback resolve


def load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, SRC / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


md = load("memory_decay_mod", "integration/memory_decay.py")
hs = load("hebbian_sync_mod", "integration/hebbian_sync.py")


def days_ago(d):
    return datetime.now(timezone.utc) - timedelta(days=d)


# --- memory_decay ---
s = md.MemoryDecayService(decay_rate=0.1, log_dir="/tmp/d1")
for i in range(5):
    s.register_node(md.MemoryNode(f"mem_{i}", f"c{i}", 0.9))
r = s.run_decay_cycle()
assert r.scanned == 5 and r.decayed == 0
assert all(n.weight == 0.9 for n in s.all_nodes())

s = md.MemoryDecayService(decay_rate=0.05, decay_interval_days=30, log_dir="/tmp/d2")
s.register_node(md.MemoryNode("stale", "x", 0.9, last_access=days_ago(60)))
r = s.run_decay_cycle()
assert r.decayed == 1
assert abs(s.get_node("stale").weight - 0.8) < 1e-9, s.get_node("stale").weight

s = md.MemoryDecayService(decay_rate=0.0, archive_threshold_days=180, log_dir="/tmp/d3")
s.register_node(md.MemoryNode("anc", "x", 0.9, last_access=days_ago(200)))
r = s.run_decay_cycle()
assert r.archived == 1 and s.get_node("anc").archived

s = md.MemoryDecayService(
    decay_rate=1.0,
    decay_interval_days=30,
    delete_threshold_weight=0.01,
    log_dir="/tmp/d4",
)
s.register_node(md.MemoryNode("doom", "x", 0.05, last_access=days_ago(60)))
r = s.run_decay_cycle()
assert r.deleted == 1 and s.get_node("doom") is None

logd = "/tmp/d5"
s = md.MemoryDecayService(decay_rate=0.05, decay_interval_days=30, log_dir=logd)
s.register_node(md.MemoryNode("n", "x", 0.9, last_access=days_ago(60)))
s.run_decay_cycle()
files = glob.glob(logd + "/*.jsonl")
assert files
ev = json.loads(open(files[0]).read().strip().splitlines()[0])
assert (
    ev["event"] == "memory_decay"
    and ev["node_id"] == "n"
    and abs(ev["new_weight"] - 0.8) < 1e-9
)

calls = []
s = md.MemoryDecayService(
    decay_rate=0.05,
    decay_interval_days=30,
    log_dir="/tmp/d6",
    sink=lambda n, p, nw: calls.append(n.node_id),
)
s.register_node(md.MemoryNode("s", "x", 0.9, last_access=days_ago(30)))
s.run_decay_cycle()
assert calls == ["s"]

s = md.MemoryDecayService(restore_boost=0.1, enable_provenance=False)
nd = s.register_node(md.MemoryNode("r", "x", 0.5))
nd.archived = True
rr = s.restore_node("r")
assert rr.archived is False and abs(rr.weight - 0.55) < 1e-9

# --- hebbian_sync ---
WU = hs.WeightUpdate
svc = hs.HebbianSyncService()
for i in range(5):
    assert svc.queue_update(WU(f"c{i}", 0.5, 0.6, 0.1)) is False
assert svc.pending() == 5
res = svc.flush_batch()
assert res.flushed == 5 and svc.pending() == 0 and svc.total_batches == 1

seen = []
svc = hs.HebbianSyncService(sink=lambda b: seen.append(list(b)))
for i in range(3):
    svc.queue_update(WU(f"c{i}", 0.5, 0.6, 0.1))
res = svc.flush_batch()
assert res.applied == 3 and len(seen) == 1 and len(seen[0]) == 3

flushes = []
svc = hs.HebbianSyncService(
    batch_size=4, auto_flush=True, sink=lambda b: flushes.append(len(b))
)
trig = [svc.queue_update(WU(f"c{i}", 0.5, 0.6, 0.1)) for i in range(4)]
assert trig[-1] is True and svc.pending() == 0 and flushes == [4]

res = hs.HebbianSyncService().flush_batch()
assert res.flushed == 0 and res.applied == 0
u = WU.from_weights("o->t", 0.4, 0.7)
assert abs(u.delta - 0.3) < 1e-9

# --- exact benchmark constructor contract ---
svc = hs.HebbianSyncService()
for i in range(100):
    svc.queue_update(WU(f"w_0_{i}", 0.5, 0.5 + i * 0.0001, i * 0.0001))
assert svc.flush_batch().flushed == 100
s = md.MemoryDecayService(decay_rate=0.1)
for i in range(50):
    s.register_node(md.MemoryNode(f"mem_{i}", f"content_{i}", 0.9))
s.run_decay_cycle()

print("ALL STANDALONE CHECKS PASSED")
