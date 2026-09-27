"""Tests for DatabaseManager in codegraph.db.database."""

import sqlite3
import pytest
from codegraph.db.database import DatabaseManager


@pytest.fixture
def db():
    """Provides a fresh in-memory database initialized with the schema."""
    manager = DatabaseManager(":memory:")
    manager.initialize_schema()
    yield manager
    manager.close()


def test_schema_initialization(db: DatabaseManager):
    """Database tables and indexes are created successfully."""
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('repositories', 'nodes', 'edges');"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    assert tables == {"repositories", "nodes", "edges"}


def test_save_and_get_repository(db: DatabaseManager):
    """Can insert and retrieve a repository."""
    db.save_repository(
        repo_id="repo-1",
        name="test-repo",
        root_path="/path/to/test-repo",
        file_count=10,
        node_count=50,
        edge_count=75,
    )

    repo = db.get_repository("repo-1")
    assert repo is not None
    assert repo["name"] == "test-repo"
    assert repo["file_count"] == 10
    assert repo["node_count"] == 50
    assert repo["edge_count"] == 75

    # Test update via on conflict
    db.save_repository(
        repo_id="repo-1",
        name="updated-test-repo",
        root_path="/path/to/test-repo",
        file_count=12,
        node_count=60,
        edge_count=90,
    )
    updated = db.get_repository("repo-1")
    assert updated["name"] == "updated-test-repo"
    assert updated["file_count"] == 12


def test_nodes_batch_insert_and_queries(db: DatabaseManager):
    """Can batch insert nodes and query them by repo, type, and qualified name."""
    db.save_repository("repo-1", "test-repo", "/path/to/test-repo")

    nodes = [
        {
            "id": "node-file-1",
            "repo_id": "repo-1",
            "type": "file",
            "name": "order.ts",
            "qualified_name": "src/order.ts",
            "file_path": "src/order.ts",
            "start_line": 1,
            "start_column": 1,
            "end_line": 30,
            "end_column": 1,
            "parent_id": None,
            "metadata": {"size": 400},
        },
        {
            "id": "node-fn-1",
            "repo_id": "repo-1",
            "type": "function",
            "name": "createOrder",
            "qualified_name": "src/order.ts::createOrder",
            "file_path": "src/order.ts",
            "start_line": 10,
            "start_column": 1,
            "end_line": 25,
            "end_column": 1,
            "parent_id": "node-file-1",
            "metadata": {"is_async": True},
        },
    ]
    db.insert_nodes_batch(nodes)

    all_nodes = db.get_nodes_by_repo("repo-1")
    assert len(all_nodes) == 2

    # Query by type
    functions = db.get_nodes_by_repo("repo-1", node_type="function")
    assert len(functions) == 1
    assert functions[0]["name"] == "createOrder"
    assert functions[0]["metadata"] == {"is_async": True}

    # Query by qualified name
    fn_node = db.get_node_by_qualified_name("repo-1", "src/order.ts::createOrder")
    assert fn_node is not None
    assert fn_node["id"] == "node-fn-1"


def test_edges_batch_insert_and_traversal_queries(db: DatabaseManager):
    """Can batch insert edges and query outgoing (callees) and incoming (callers) edges."""
    db.save_repository("repo-1", "test-repo", "/path/to/test-repo")

    nodes = [
        {
            "id": "node-1",
            "repo_id": "repo-1",
            "type": "function",
            "name": "callerFn",
            "qualified_name": "src/a.ts::callerFn",
            "file_path": "src/a.ts",
            "start_line": 1,
            "start_column": 1,
            "end_line": 5,
            "end_column": 1,
            "parent_id": None,
            "metadata": None,
        },
        {
            "id": "node-2",
            "repo_id": "repo-1",
            "type": "function",
            "name": "calleeFn",
            "qualified_name": "src/b.ts::calleeFn",
            "file_path": "src/b.ts",
            "start_line": 1,
            "start_column": 1,
            "end_line": 5,
            "end_column": 1,
            "parent_id": None,
            "metadata": None,
        },
    ]
    db.insert_nodes_batch(nodes)

    edges = [
        {
            "id": "edge-1",
            "repo_id": "repo-1",
            "source_id": "node-1",
            "target_id": "node-2",
            "type": "CALLS",
            "metadata": {"confidence": 1.0},
        }
    ]
    db.insert_edges_batch(edges)

    # Test outgoing (Callees of node-1)
    outgoing = db.get_outgoing_edges("node-1", edge_type="CALLS")
    assert len(outgoing) == 1
    assert outgoing[0]["target_id"] == "node-2"

    # Test incoming (Callers of node-2)
    incoming = db.get_incoming_edges("node-2", edge_type="CALLS")
    assert len(incoming) == 1
    assert incoming[0]["source_id"] == "node-1"


def test_foreign_key_enforcement(db: DatabaseManager):
    """Inserting an edge pointing to a non-existent node fails with IntegrityError."""
    db.save_repository("repo-1", "test-repo", "/path/to/test-repo")

    # node-999 does not exist
    invalid_edges = [
        {
            "id": "edge-fail",
            "repo_id": "repo-1",
            "source_id": "node-999",
            "target_id": "node-888",
            "type": "CALLS",
            "metadata": None,
        }
    ]
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_edges_batch(invalid_edges)


def test_cascade_delete_repository(db: DatabaseManager):
    """Deleting a repository cascades and removes all associated nodes and edges."""
    db.save_repository("repo-1", "test-repo", "/path/to/test-repo")
    db.insert_nodes_batch([
        {
            "id": "node-1",
            "repo_id": "repo-1",
            "type": "file",
            "name": "a.ts",
            "qualified_name": "a.ts",
            "file_path": "a.ts",
            "start_line": 1,
            "start_column": 1,
            "end_line": 10,
            "end_column": 1,
            "parent_id": None,
            "metadata": None,
        }
    ])

    assert len(db.get_nodes_by_repo("repo-1")) == 1

    # Delete repository
    db.delete_repository("repo-1")

    # Nodes should be automatically wiped
    assert len(db.get_nodes_by_repo("repo-1")) == 0
    assert db.get_repository("repo-1") is None
