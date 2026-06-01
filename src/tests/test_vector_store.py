import pytest

from src.mcp.vector_store import LocalVectorStore


def simple_embedding(text: str):
    # Deterministic small embedding for tests
    """Simple embedding.
    
    Args:
        text (str): Text value to parse, search, or transform.
    
    Returns:
        None: This function does not return a value.
    """
    return [len(text), sum(ord(c) for c in text) % 100]


@pytest.fixture
def vector_store(tmp_path):
    """Vector store.
    
    Args:
        tmp_path: Tmp path value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    db_path = tmp_path / "vector_store.db"
    return LocalVectorStore(db_path=str(db_path), embedding_fn=simple_embedding)


def test_upsert_and_count(vector_store):
    """Test that upsert and count.
    
    Args:
        vector_store: Vector store value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    vector_store.upsert("doc1", "hello world", {"type": "greeting"})
    vector_store.upsert("doc2", "hello mars", {"type": "greeting"})
    assert vector_store.count() == 2


def test_query_orders_by_similarity(vector_store):
    """Test that query orders by similarity.
    
    Args:
        vector_store: Vector store value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    vector_store.upsert("earth", "hello earth")
    vector_store.upsert("mars", "hello mars")
    vector_store.upsert("venus", "salutations venus")

    results = vector_store.query("hello mars", top_k=2)
    assert len(results) == 2
    top_ids = [doc_id for doc_id, _, _ in results]
    assert top_ids[0] == "mars"


def test_delete(vector_store):
    """Test that delete.
    
    Args:
        vector_store: Vector store value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    vector_store.upsert("doc1", "hello world")
    vector_store.delete("doc1")
    assert vector_store.count() == 0


def test_query_can_include_content(vector_store):
    """Test that query can include content.
    
    Args:
        vector_store: Vector store value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    vector_store.upsert("doc1", "embedded content", {"path": "notes/doc1.md"})

    results = vector_store.query("embedded", top_k=1, include_content=True)

    assert len(results) == 1
    doc_id, score, metadata, content = results[0]
    assert doc_id == "doc1"
    assert "path" in metadata
    assert "embedded content" in content
