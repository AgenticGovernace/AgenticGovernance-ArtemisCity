"""
Seed the local SQLite vector store with current plan documents and a sample concept note.

Usage:
  python scripts/seed_vector_store.py [--db data/vector_store.db]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp.vector_store import LocalVectorStore


DEFAULT_DOCS = [
    (
        "project_update_plan",
        Path("PROJECT_UPDATE_PLAN.md"),
        {"type": "plan", "source": "project_update_plan"},
    ),
    (
        "whitebook_update_plan",
        Path("WHITEBOOK_UPDATE_PLAN.md"),
        {"type": "plan", "source": "whitebook_update_plan"},
    ),
]

SAMPLE_SNIPPET_ID = "sample_memory_bus_overview"
SAMPLE_SNIPPET = """
Memory Bus Sync Protocol (sample):
- Write-through to Obsidian and vector store
- Embedding generated in parallel with write
- Conflict resolution: last-write-wins + audit log
- Read hierarchy: exact -> keyword -> vector similarity
"""


def load_docs() -> list[tuple[str, str, dict]]:
    records = []
    for doc_id, path, metadata in DEFAULT_DOCS:
        if path.is_file():
            records.append((doc_id, path.read_text(encoding="utf-8"), metadata))
        else:
            print(f"Skipping missing doc: {path}")
    records.append(
        (
            SAMPLE_SNIPPET_ID,
            SAMPLE_SNIPPET.strip(),
            {"type": "sample", "source": "inline"},
        )
    )
    return records


def main():
    parser = argparse.ArgumentParser(
        description="Seed the local vector store with plan documents and sample data."
    )
    parser.add_argument(
        "--db",
        default="data/vector_store.db",
        help="Path to the SQLite vector store DB.",
    )
    args = parser.parse_args()

    store = LocalVectorStore(db_path=args.db)
    records = load_docs()
    store.upsert_many(records)
    print(f"Seeded {len(records)} records into {args.db}. Total rows: {store.count()}")


if __name__ == "__main__":
    main()
