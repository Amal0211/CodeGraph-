-- ---------------------------------------------------------------------
-- CodeGraph SQLite Schema (Milestone 3)
-- ---------------------------------------------------------------------

-- Table 1: REPOSITORIES
-- Stores analyzed projects and summary statistics
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_count INTEGER DEFAULT 0,
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0
);

-- Table 2: NODES
-- Stores every code entity: Repositories, Directories, Files, Classes, Interfaces, Functions, Methods
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    type TEXT NOT NULL, -- 'repository' | 'directory' | 'file' | 'class' | 'interface' | 'function' | 'method'
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    file_path TEXT,     -- Relative file path (NULL for directory or repository root)
    start_line INTEGER,
    start_column INTEGER,
    end_line INTEGER,
    end_column INTEGER,
    parent_id TEXT,     -- Self-referencing Foreign Key for containment tree
    metadata JSON,      -- Extra attributes (e.g. is_async, params, docstrings)
    FOREIGN KEY(repo_id) REFERENCES repositories(id) ON DELETE CASCADE,
    FOREIGN KEY(parent_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Table 3: EDGES
-- Stores directed connections between nodes (Subject -> Predicate -> Object)
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL, -- 'CONTAINS' | 'DEFINES' | 'IMPORTS' | 'CALLS' | 'EXTENDS' | 'IMPLEMENTS'
    metadata JSON,      -- Provenance: {"confidence": 1.0, "source_type": "static_analysis", "location": {...}}
    FOREIGN KEY(repo_id) REFERENCES repositories(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_nodes_repo ON nodes(repo_id);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(repo_id, file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_qualified ON nodes(repo_id, qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_repo_type ON edges(repo_id, type);
