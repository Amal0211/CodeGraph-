"""Data models for graph entities and relationships."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RepositoryModel:
    """Represents a code repository in the graph."""

    id: str
    name: str
    root_path: str
    file_count: int = 0
    node_count: int = 0
    edge_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NodeModel:
    """Represents a graph node (repository, directory, file, class, interface, function, method)."""

    id: str
    repo_id: str
    type: str  # 'repository' | 'directory' | 'file' | 'class' | 'interface' | 'function' | 'method'
    name: str
    qualified_name: str
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    start_column: Optional[int] = None
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    parent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EdgeModel:
    """Represents a directed relationship between two nodes."""

    id: str
    repo_id: str
    source_id: str
    target_id: str
    type: str  # 'CONTAINS' | 'DEFINES' | 'IMPORTS' | 'CALLS' | 'EXTENDS' | 'IMPLEMENTS'
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
