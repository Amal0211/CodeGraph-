"""Resolves module imports and call references across extracted files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from .extractor import (
    ExtractedCall,
    ExtractedExport,
    ExtractedImport,
    ExtractedSymbol,
    FileExtractionResult,
    SourceLocation,
)


@dataclass(frozen=True)
class ResolvedEdge:
    """A directed, typed relationship between two entities with provenance metadata."""

    source: str
    target: str
    type: str  # 'CALLS' | 'IMPORTS' | 'DEFINES' | 'CONTAINS'
    metadata: dict = field(default_factory=dict)


@dataclass
class ResolutionResult:
    """The aggregate result of cross-file symbol and dependency resolution."""

    symbols: List[ExtractedSymbol] = field(default_factory=list)
    edges: List[ResolvedEdge] = field(default_factory=list)
    unresolved_calls: List[ExtractedCall] = field(default_factory=list)


class ReferenceResolver:
    """Resolves relative imports and maps call sites to target symbols."""

    CANDIDATE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]

    def __init__(self, extractions: Dict[str, FileExtractionResult]) -> None:
        # extractions keyed by normalized relative file path (e.g. 'src/order.ts')
        self.extractions = extractions
        self.all_file_paths: Set[str] = set(extractions.keys())

        # Index symbols by qualified name and by (file, symbol_name)
        self.symbols_by_qual_name: Dict[str, ExtractedSymbol] = {}
        self.symbols_by_file_and_name: Dict[str, Dict[str, ExtractedSymbol]] = {}

        for file_path, data in extractions.items():
            self.symbols_by_file_and_name[file_path] = {}
            if data and data.symbols:
                for sym in data.symbols:
                    self.symbols_by_qual_name[sym.qualified_name] = sym
                    self.symbols_by_file_and_name[file_path][sym.name] = sym

    def resolve_module_path(self, current_file: str, specifier: str) -> Optional[str]:
        """Resolves a relative module specifier (e.g. './payment') to a known file in the repository."""
        # Only resolve relative imports (starting with ./ or ../)
        if not (specifier.startswith("./") or specifier.startswith("../")):
            return None

        current_dir = Path(current_file).parent
        target_candidate = (current_dir / specifier)

        # Normalize relative path using PurePosixPath semantics
        # e.g., src/services/../payment -> src/payment
        parts = []
        for part in target_candidate.parts:
            if part == ".":
                continue
            elif part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        normalized_base = "/".join(parts)

        # 1. Exact match (if specifier already has extension)
        if normalized_base in self.all_file_paths:
            return normalized_base

        # 2. Try candidate extensions
        for ext in self.CANDIDATE_EXTENSIONS:
            candidate = f"{normalized_base}{ext}"
            if candidate in self.all_file_paths:
                return candidate

        return None

    def resolve(self) -> ResolutionResult:
        """Executes reference resolution across all files and generates edges."""
        all_symbols: List[ExtractedSymbol] = []
        edges: List[ResolvedEdge] = []
        unresolved_calls: List[ExtractedCall] = []

        # Process each file's extractions
        for file_path, data in self.extractions.items():
            all_symbols.extend(data.symbols)

            # -------------------------------------------------------------
            # 1. Generate DEFINES / CONTAINS edges
            # -------------------------------------------------------------
            for sym in data.symbols:
                if sym.kind == "method" and sym.parent_name:
                    # Class -> Method CONTAINS edge
                    parent_qual = f"{file_path}::{sym.parent_name}"
                    edges.append(
                        ResolvedEdge(
                            source=parent_qual,
                            target=sym.qualified_name,
                            type="CONTAINS",
                            metadata={"confidence": 1.0, "source_type": "static_analysis"},
                        )
                    )
                else:
                    # File -> Symbol DEFINES edge
                    edges.append(
                        ResolvedEdge(
                            source=file_path,
                            target=sym.qualified_name,
                            type="DEFINES",
                            metadata={"confidence": 1.0, "source_type": "static_analysis"},
                        )
                    )

            # -------------------------------------------------------------
            # 2. Resolve IMPORTS
            # -------------------------------------------------------------
            # Map imported local name -> (target_file, remote_name)
            # e.g., 'charge' -> ('src/payment.ts', 'charge')
            import_map: Dict[str, tuple[str, str]] = {}

            for imp in data.imports:
                resolved_target_file = self.resolve_module_path(file_path, imp.source_module)
                if not resolved_target_file:
                    continue

                # File-level IMPORTS edge
                edges.append(
                    ResolvedEdge(
                        source=file_path,
                        target=resolved_target_file,
                        type="IMPORTS",
                        metadata={
                            "module_specifier": imp.source_module,
                            "confidence": 1.0,
                            "source_type": "static_analysis",
                            "location": {
                                "file": file_path,
                                "line": imp.location.start_line,
                            },
                        },
                    )
                )

                # Track identifier mappings for call resolution
                local_name = imp.alias or imp.imported_name
                if local_name:
                    remote_name = imp.imported_name if not imp.is_default else "default"
                    import_map[local_name] = (resolved_target_file, remote_name)

            # -------------------------------------------------------------
            # 3. Resolve CALLS
            # -------------------------------------------------------------
            for call in data.calls:
                resolved_target: Optional[ExtractedSymbol] = None

                # Case A: Member call with receiver, e.g. PaymentService.charge() or ps.charge()
                if call.receiver_name:
                    if call.receiver_name in import_map:
                        target_file, _ = import_map[call.receiver_name]
                        # Check if target file has a class method with this callee name
                        target_qual = f"{target_file}::{call.receiver_name}.{call.callee_name}"
                        if target_qual in self.symbols_by_qual_name:
                            resolved_target = self.symbols_by_qual_name[target_qual]
                        else:
                            # Or perhaps the target file exported a function with that name
                            target_file_syms = self.symbols_by_file_and_name.get(target_file, {})
                            if call.callee_name in target_file_syms:
                                resolved_target = target_file_syms[call.callee_name]
                    else:
                        # Check if receiver directly matches a local class name
                        local_class_qual = f"{file_path}::{call.receiver_name}.{call.callee_name}"
                        if local_class_qual in self.symbols_by_qual_name:
                            resolved_target = self.symbols_by_qual_name[local_class_qual]
                        else:
                            # Or check if any class defined in this file contains this method
                            for sym in data.symbols:
                                if sym.kind == "method" and sym.name == call.callee_name:
                                    resolved_target = sym
                                    break

                # Case B: Direct function call, e.g. charge()
                if not resolved_target and not call.receiver_name:
                    # B1. Local function in current file
                    local_syms = self.symbols_by_file_and_name.get(file_path, {})
                    if call.callee_name in local_syms:
                        resolved_target = local_syms[call.callee_name]

                    # B2. Imported function
                    elif call.callee_name in import_map:
                        target_file, remote_name = import_map[call.callee_name]
                        target_file_syms = self.symbols_by_file_and_name.get(target_file, {})
                        # Match by remote_name or callee_name
                        if remote_name in target_file_syms:
                            resolved_target = target_file_syms[remote_name]
                        elif call.callee_name in target_file_syms:
                            resolved_target = target_file_syms[call.callee_name]

                # Create CALLS edge if resolved
                caller_source = call.caller_qualified_name or file_path
                if resolved_target:
                    edges.append(
                        ResolvedEdge(
                            source=caller_source,
                            target=resolved_target.qualified_name,
                            type="CALLS",
                            metadata={
                                "confidence": 1.0,
                                "source_type": "static_analysis",
                                "location": {
                                    "file": file_path,
                                    "line": call.location.start_line,
                                    "column": call.location.start_column,
                                },
                            },
                        )
                    )
                else:
                    unresolved_calls.append(call)

        return ResolutionResult(
            symbols=all_symbols,
            edges=edges,
            unresolved_calls=unresolved_calls,
        )
