"""Database manager for CodeGraph SQLite storage."""

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union


class DatabaseManager:
    """Manages SQLite connections, schema initialization, and graph persistence."""

    def __init__(self, db_path: Union[str, Path] = "codegraph.db") -> None:
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        """Returns an active SQLite connection with foreign keys and row factory enabled."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row #Returns rows in form of dictionary not tuples.

            #Enforce foreign key constraints
            self._conn.execute("PRAGMA foreign_keys = ON;")

            #Enable Write-Ahead Logging for better concurrent read/write performance
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")

        return self._conn

    def initialize_schema(self) -> None:
        """Executes schema.sql to create tables and indexes."""
        conn = self.get_connection()
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

    def close(self) -> None:
        """Closes the active database connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -------------------------------------------------------------------------
    # Repositories
    # -------------------------------------------------------------------------

    def save_repository(
        self,
        repo_id: str,
        name: str,
        root_path: str,
        file_count: int = 0,
        node_count: int = 0,
        edge_count: int = 0,
    ) -> None:
        """Inserts or updates a repository entry."""
        conn = self.get_connection()
        sql = """
        INSERT INTO repositories (id, name, root_path, file_count, node_count, edge_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            root_path = excluded.root_path,
            analyzed_at = CURRENT_TIMESTAMP,
            file_count = excluded.file_count,
            node_count = excluded.node_count,
            edge_count = excluded.edge_count;
        """
        with conn:
            conn.execute(sql, (repo_id, name, str(root_path), file_count, node_count, edge_count))

    def get_repository(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves repository metadata by ID."""
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM repositories WHERE id = ?;", (repo_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_repositories(self) -> List[Dict[str, Any]]:
        """Lists all analyzed repositories."""
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM repositories ORDER BY analyzed_at DESC;")
        return [dict(row) for row in cursor.fetchall()]

    def delete_repository(self, repo_id: str) -> None:
        """Deletes a repository and cascades deletion to its nodes and edges."""
        conn = self.get_connection()
        with conn:
            conn.execute("DELETE FROM repositories WHERE id = ?;", (repo_id,))

    # -------------------------------------------------------------------------
    # Nodes
    # -------------------------------------------------------------------------

    def insert_nodes_batch(self, nodes: List[Dict[str, Any]]) -> None:
        """Bulk inserts nodes within an atomic transaction."""
        if not nodes:
            return

        conn = self.get_connection()
        sql = """
        INSERT INTO nodes (
            id, repo_id, type, name, qualified_name, file_path,
            start_line, start_column, end_line, end_column, parent_id, metadata
        ) VALUES (
            :id, :repo_id, :type, :name, :qualified_name, :file_path,
            :start_line, :start_column, :end_line, :end_column, :parent_id, :metadata
        );
        """
        # Ensure metadata is serialized to JSON string if it's a dict
        formatted_nodes = []
        for n in nodes:
            item = dict(n)
            meta = item.get("metadata")
            item["metadata"] = json.dumps(meta) if isinstance(meta, (dict, list)) else meta
            formatted_nodes.append(item)

        with conn:
            conn.executemany(sql, formatted_nodes)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single node by its primary ID."""
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM nodes WHERE id = ?;", (node_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if res.get("metadata"):
            res["metadata"] = json.loads(res["metadata"])
        return res

    def get_nodes_by_repo(self, repo_id: str, node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries nodes for a given repo, optionally filtering by type."""
        conn = self.get_connection()
        if node_type:
            cursor = conn.execute(
                "SELECT * FROM nodes WHERE repo_id = ? AND type = ?;",
                (repo_id, node_type),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM nodes WHERE repo_id = ?;",
                (repo_id,),
            )
        results = []
        for row in cursor.fetchall():
            item = dict(row)
            if item.get("metadata"):
                item["metadata"] = json.loads(item["metadata"])
            results.append(item)
        return results

    def get_node_by_qualified_name(self, repo_id: str, qualified_name: str) -> Optional[Dict[str, Any]]:
        """Finds a node by its qualified name within a repo."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT * FROM nodes WHERE repo_id = ? AND qualified_name = ?;",
            (repo_id, qualified_name),
        )
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if res.get("metadata"):
            res["metadata"] = json.loads(res["metadata"])
        return res

    # -------------------------------------------------------------------------
    # Edges
    # -------------------------------------------------------------------------

    def insert_edges_batch(self, edges: List[Dict[str, Any]]) -> None:
        """Bulk inserts edges within an atomic transaction."""
        if not edges:
            return

        conn = self.get_connection()
        sql = """
        INSERT INTO edges (id, repo_id, source_id, target_id, type, metadata)
        VALUES (:id, :repo_id, :source_id, :target_id, :type, :metadata);
        """
        formatted_edges = []
        for e in edges:
            item = dict(e)
            meta = item.get("metadata")
            item["metadata"] = json.dumps(meta) if isinstance(meta, (dict, list)) else meta
            formatted_edges.append(item)

        with conn:
            conn.executemany(sql, formatted_edges)

    def get_edges_by_repo(self, repo_id: str, edge_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries edges for a given repo, optionally filtering by type."""
        conn = self.get_connection()
        if edge_type:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE repo_id = ? AND type = ?;",
                (repo_id, edge_type),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE repo_id = ?;",
                (repo_id,),
            )
        results = []
        for row in cursor.fetchall():
            item = dict(row)
            if item.get("metadata"):
                item["metadata"] = json.loads(item["metadata"])
            results.append(item)
        return results

    def get_outgoing_edges(self, source_id: str, edge_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Finds edges originating from source_id (e.g. Callees)."""
        conn = self.get_connection()
        if edge_type:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE source_id = ? AND type = ?;",
                (source_id, edge_type),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE source_id = ?;",
                (source_id,),
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_incoming_edges(self, target_id: str, edge_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Finds edges pointing to target_id (e.g. Callers)."""
        conn = self.get_connection()
        if edge_type:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE target_id = ? AND type = ?;",
                (target_id, edge_type),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM edges WHERE target_id = ?;",
                (target_id,),
            )
        return [dict(row) for row in cursor.fetchall()]
