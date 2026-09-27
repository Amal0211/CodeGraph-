"""Builds a hierarchical knowledge graph from scanner and resolver outputs."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid

from codegraph.analyzer.resolver import ResolutionResult
from codegraph.analyzer.scanner import ScanResult
from codegraph.db.database import DatabaseManager
from .models import EdgeModel, NodeModel, RepositoryModel


class KnowledgeGraphBuilder:
    """Transforms raw scan and resolution results into a hierarchical property graph."""

    def __init__(self, repo_id: Optional[str] = None) -> None:
        self._custom_repo_id = repo_id

    def _generate_repo_id(self, root_path: str) -> str:
        if self._custom_repo_id:
            return self._custom_repo_id
        # Generate a deterministic UUID based on normalized root path
        normalized = str(Path(root_path).resolve().as_posix())
        return str(uuid.uuid5(uuid.NAMESPACE_URL, normalized))[:12]

    def build(
        self,
        repo_name: str,
        root_path: str,
        scan_result: ScanResult,
        resolution_result: ResolutionResult,
    ) -> Tuple[RepositoryModel, List[NodeModel], List[EdgeModel]]:
        """Constructs repository, directory, file, and symbol nodes and their edges."""
        repo_id = self._generate_repo_id(root_path)
        nodes: List[NodeModel] = []
        edges: List[EdgeModel] = []

        # Maps qualified name / path -> database node ID
        id_map: Dict[str, str] = {}
        dir_cache: Dict[str, str] = {}

        # -------------------------------------------------------------
        # 1. Root Repository Node
        # -------------------------------------------------------------
        repo_node_id = f"{repo_id}:root"
        repo_node = NodeModel(
            id=repo_node_id,
            repo_id=repo_id,
            type="repository",
            name=repo_name,
            qualified_name=repo_name,
            file_path=None,
            parent_id=None,
            metadata={"root_path": str(root_path)},
        )
        nodes.append(repo_node)
        id_map[repo_name] = repo_node_id

        # -------------------------------------------------------------
        # 2. Directory Hierarchy and File Nodes
        # -------------------------------------------------------------
        for scanned_file in scan_result.files:
            rel_path = scanned_file.relative_path
            path_parts = rel_path.split("/")

            # Process intermediate directories
            current_parent_id = repo_node_id
            for i in range(len(path_parts) - 1):
                dir_rel_path = "/".join(path_parts[: i + 1])
                if dir_rel_path not in dir_cache:
                    dir_node_id = f"{repo_id}:dir:{dir_rel_path}"
                    dir_name = path_parts[i]

                    dir_node = NodeModel(
                        id=dir_node_id,
                        repo_id=repo_id,
                        type="directory",
                        name=dir_name,
                        qualified_name=dir_rel_path,
                        file_path=dir_rel_path,
                        parent_id=current_parent_id,
                    )
                    nodes.append(dir_node)
                    dir_cache[dir_rel_path] = dir_node_id

                    # CONTAINS edge from parent to this directory
                    edges.append(
                        EdgeModel(
                            id=f"{repo_id}:edge:contains:{current_parent_id}->{dir_node_id}",
                            repo_id=repo_id,
                            source_id=current_parent_id,
                            target_id=dir_node_id,
                            type="CONTAINS",
                            metadata={"source_type": "filesystem"},
                        )
                    )

                current_parent_id = dir_cache[dir_rel_path]

            # Create File Node
            file_node_id = f"{repo_id}:file:{rel_path}"
            file_name = path_parts[-1]
            file_node = NodeModel(
                id=file_node_id,
                repo_id=repo_id,
                type="file",
                name=file_name,
                qualified_name=rel_path,
                file_path=rel_path,
                parent_id=current_parent_id,
                metadata={"size_bytes": scanned_file.size_bytes, "extension": scanned_file.extension},
            )
            nodes.append(file_node)
            id_map[rel_path] = file_node_id

            # CONTAINS edge from parent directory (or repo) to file
            edges.append(
                EdgeModel(
                    id=f"{repo_id}:edge:contains:{current_parent_id}->{file_node_id}",
                    repo_id=repo_id,
                    source_id=current_parent_id,
                    target_id=file_node_id,
                    type="CONTAINS",
                    metadata={"source_type": "filesystem"},
                )
            )

        # -------------------------------------------------------------
        # 3. Code Symbols (Classes, Interfaces, Functions, Methods)
        # -------------------------------------------------------------
        for sym in resolution_result.symbols:
            sym_node_id = f"{repo_id}:sym:{sym.qualified_name}"
            file_node_id = id_map.get(sym.file_path)

            # Determine parent node (class for methods, file for top-level symbols)
            parent_id = file_node_id
            if sym.kind == "method" and sym.parent_name:
                class_qual_name = f"{sym.file_path}::{sym.parent_name}"
                parent_id = id_map.get(class_qual_name, file_node_id)

            sym_node = NodeModel(
                id=sym_node_id,
                repo_id=repo_id,
                type=sym.kind,
                name=sym.name,
                qualified_name=sym.qualified_name,
                file_path=sym.file_path,
                start_line=sym.location.start_line,
                start_column=sym.location.start_column,
                end_line=sym.location.end_line,
                end_column=sym.location.end_column,
                parent_id=parent_id,
            )
            nodes.append(sym_node)
            id_map[sym.qualified_name] = sym_node_id

        # -------------------------------------------------------------
        # 4. Map Resolved Edges to Database Node IDs
        # -------------------------------------------------------------
        edge_counter = 0
        for res_edge in resolution_result.edges:
            source_id = id_map.get(res_edge.source)
            target_id = id_map.get(res_edge.target)

            if source_id and target_id:
                edge_counter += 1
                edge_id = f"{repo_id}:edge:{res_edge.type}:{edge_counter}"
                edges.append(
                    EdgeModel(
                        id=edge_id,
                        repo_id=repo_id,
                        source_id=source_id,
                        target_id=target_id,
                        type=res_edge.type,
                        metadata=res_edge.metadata,
                    )
                )

        # Repository summary model
        repo_model = RepositoryModel(
            id=repo_id,
            name=repo_name,
            root_path=str(root_path),
            file_count=scan_result.total_files,
            node_count=len(nodes),
            edge_count=len(edges),
        )

        return repo_model, nodes, edges

    def build_and_save(
        self,
        repo_name: str,
        root_path: str,
        scan_result: ScanResult,
        resolution_result: ResolutionResult,
        db: DatabaseManager,
    ) -> RepositoryModel:
        """Constructs the graph and commits it to SQLite within an atomic transaction."""
        repo_model, nodes, edges = self.build(repo_name, root_path, scan_result, resolution_result)

        # 1. Save repository record
        db.save_repository(
            repo_id=repo_model.id,
            name=repo_model.name,
            root_path=repo_model.root_path,
            file_count=repo_model.file_count,
            node_count=repo_model.node_count,
            edge_count=repo_model.edge_count,
        )
 
        # 2. Insert nodes and edges in batches
        db.insert_nodes_batch([n.to_dict() for n in nodes])
        db.insert_edges_batch([e.to_dict() for e in edges])

        return repo_model
