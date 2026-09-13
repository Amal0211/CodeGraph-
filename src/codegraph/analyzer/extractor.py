"""Extracts symbols, definitions, imports, exports, and call sites from Tree-sitter ASTs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import tree_sitter


@dataclass(frozen=True)
class SourceLocation:
    """Precise source location coordinates (1-indexed)."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int

    @classmethod
    def from_node(cls, node: tree_sitter.Node) -> "SourceLocation":
        return cls(
            start_line=node.start_point.row + 1,
            start_column=node.start_point.column + 1,
            end_line=node.end_point.row + 1,
            end_column=node.end_point.column + 1,
        )


@dataclass(frozen=True)
class ExtractedSymbol:
    """A declared code entity (class, function, method, interface)."""

    name: str
    qualified_name: str
    kind: str  # 'function' | 'method' | 'class' | 'interface'
    file_path: str
    location: SourceLocation
    parent_name: Optional[str] = None


@dataclass(frozen=True)
class ExtractedImport:
    """An imported dependency specification."""

    file_path: str
    imported_name: str
    source_module: str  # e.g., './payment' or 'express'
    alias: Optional[str] = None
    is_default: bool = False
    is_namespace: bool = False
    location: SourceLocation = field(default_factory=lambda: SourceLocation(0, 0, 0, 0))


@dataclass(frozen=True)
class ExtractedExport:
    """An exported symbol specification."""

    file_path: str
    name: str
    is_default: bool = False
    location: SourceLocation = field(default_factory=lambda: SourceLocation(0, 0, 0, 0))


@dataclass(frozen=True)
class ExtractedCall:
    """A raw function or method call site."""

    caller_qualified_name: Optional[str]
    callee_name: str
    receiver_name: Optional[str] = None  # e.g., 'paymentService' in 'paymentService.charge()'
    file_path: str = ""
    location: SourceLocation = field(default_factory=lambda: SourceLocation(0, 0, 0, 0))


@dataclass
class FileExtractionResult:
    """Contains all symbols, imports, exports, and calls extracted from a single file."""

    file_path: str
    symbols: List[ExtractedSymbol] = field(default_factory=list)
    imports: List[ExtractedImport] = field(default_factory=list)
    exports: List[ExtractedExport] = field(default_factory=list)
    calls: List[ExtractedCall] = field(default_factory=list)


class SymbolExtractor:
    """Walks a Tree-sitter syntax tree to extract symbols, dependencies, and calls."""

    def extract(self, file_path: str, tree: tree_sitter.Tree, code_bytes: bytes) -> FileExtractionResult:
        """Extracts all definitions, imports, exports, and calls for a file."""
        # Normalize file path with forward slashes
        normalized_path = Path(file_path).as_posix()
        result = FileExtractionResult(file_path=normalized_path)

        # Context stack tracks enclosing entities for qualified names and call context
        # Entries are (kind, name, qualified_name)
        context_stack: List[tuple[str, str, str]] = []

        def get_current_caller() -> Optional[str]:
            """Returns the innermost function/method qualified name, if any."""
            for kind, name, qual_name in reversed(context_stack):
                if kind in ("function", "method"):
                    return qual_name
            return None

        def get_current_class() -> Optional[str]:
            """Returns the innermost class name, if any."""
            for kind, name, qual_name in reversed(context_stack):
                if kind == "class":
                    return name
            return None

        def node_text(node: tree_sitter.Node) -> str:
            return code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

        def visit(node: tree_sitter.Node):
            nonlocal context_stack

            node_type = node.type

            # -------------------------------------------------------------
            # 1. Imports
            # -------------------------------------------------------------
            if node_type == "import_statement":
                self._extract_import(node, normalized_path, node_text, result)
                return  # Do not recurse into import statement children

            # -------------------------------------------------------------
            # 2. Exports
            # -------------------------------------------------------------
            if node_type == "export_statement":
                self._extract_export_clause(node, normalized_path, node_text, result)
                # Note: export statements often wrap declarations (export function ...),
                # so we continue traversing their children below.

            # -------------------------------------------------------------
            # 3. Class Declarations
            # -------------------------------------------------------------
            if node_type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    class_name = node_text(name_node)
                    qual_name = f"{normalized_path}::{class_name}"
                    loc = SourceLocation.from_node(node)

                    result.symbols.append(
                        ExtractedSymbol(
                            name=class_name,
                            qualified_name=qual_name,
                            kind="class",
                            file_path=normalized_path,
                            location=loc,
                        )
                    )

                    context_stack.append(("class", class_name, qual_name))
                    for child in node.children:
                        visit(child)
                    context_stack.pop()
                    return

            # -------------------------------------------------------------
            # 4. Method Definitions inside Classes
            # -------------------------------------------------------------
            if node_type == "method_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    method_name = node_text(name_node)
                    parent_class = get_current_class()
                    if parent_class:
                        qual_name = f"{normalized_path}::{parent_class}.{method_name}"
                    else:
                        qual_name = f"{normalized_path}::{method_name}"

                    loc = SourceLocation.from_node(node)
                    result.symbols.append(
                        ExtractedSymbol(
                            name=method_name,
                            qualified_name=qual_name,
                            kind="method",
                            file_path=normalized_path,
                            location=loc,
                            parent_name=parent_class,
                        )
                    )

                    context_stack.append(("method", method_name, qual_name))
                    for child in node.children:
                        visit(child)
                    context_stack.pop()
                    return

            # -------------------------------------------------------------
            # 5. Function Declarations
            # -------------------------------------------------------------
            if node_type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    func_name = node_text(name_node)
                    qual_name = f"{normalized_path}::{func_name}"
                    loc = SourceLocation.from_node(node)

                    result.symbols.append(
                        ExtractedSymbol(
                            name=func_name,
                            qualified_name=qual_name,
                            kind="function",
                            file_path=normalized_path,
                            location=loc,
                        )
                    )

                    context_stack.append(("function", func_name, qual_name))
                    for child in node.children:
                        visit(child)
                    context_stack.pop()
                    return

            # -------------------------------------------------------------
            # 6. Variable Declarator (e.g., const fn = () => ...)
            # -------------------------------------------------------------
            if node_type == "variable_declarator":
                name_node = node.child_by_field_name("name")
                value_node = node.child_by_field_name("value")

                if name_node and value_node and value_node.type in ("arrow_function", "function_expression"):
                    fn_name = node_text(name_node)
                    qual_name = f"{normalized_path}::{fn_name}"
                    loc = SourceLocation.from_node(node)

                    result.symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            qualified_name=qual_name,
                            kind="function",
                            file_path=normalized_path,
                            location=loc,
                        )
                    )

                    context_stack.append(("function", fn_name, qual_name))
                    for child in value_node.children:
                        visit(child)
                    context_stack.pop()
                    return

            # -------------------------------------------------------------
            # 7. Interface Declarations (TypeScript)
            # -------------------------------------------------------------
            if node_type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    iface_name = node_text(name_node)
                    qual_name = f"{normalized_path}::{iface_name}"
                    loc = SourceLocation.from_node(node)

                    result.symbols.append(
                        ExtractedSymbol(
                            name=iface_name,
                            qualified_name=qual_name,
                            kind="interface",
                            file_path=normalized_path,
                            location=loc,
                        )
                    )

            # -------------------------------------------------------------
            # 8. Call Expressions
            # -------------------------------------------------------------
            if node_type == "call_expression":
                fn_expr = node.child_by_field_name("function")
                if fn_expr:
                    caller_qual_name = get_current_caller()
                    loc = SourceLocation.from_node(node)

                    if fn_expr.type == "identifier":
                        # Direct call: charge()
                        callee = node_text(fn_expr)
                        result.calls.append(
                            ExtractedCall(
                                caller_qualified_name=caller_qual_name,
                                callee_name=callee,
                                receiver_name=None,
                                file_path=normalized_path,
                                location=loc,
                            )
                        )
                    elif fn_expr.type == "member_expression":
                        # Method call: paymentService.charge()
                        prop_node = fn_expr.child_by_field_name("property")
                        obj_node = fn_expr.child_by_field_name("object")
                        if prop_node:
                            callee = node_text(prop_node)
                            receiver = node_text(obj_node) if obj_node else None
                            result.calls.append(
                                ExtractedCall(
                                    caller_qualified_name=caller_qual_name,
                                    callee_name=callee,
                                    receiver_name=receiver,
                                    file_path=normalized_path,
                                    location=loc,
                                )
                            )

            # Recurse into children
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        return result

    def _extract_import(
        self,
        node: tree_sitter.Node,
        file_path: str,
        node_text,
        result: FileExtractionResult,
    ):
        """Extracts import details from an import_statement node."""
        source_node = node.child_by_field_name("source")
        if not source_node:
            return

        source_module = node_text(source_node).strip("'\"")
        loc = SourceLocation.from_node(node)

        # Look for import_clause
        clause_node = None
        for child in node.children:
            if child.type == "import_clause":
                clause_node = child
                break

        if not clause_node:
            # Side-effect import: import './polyfills';
            result.imports.append(
                ExtractedImport(
                    file_path=file_path,
                    imported_name="",
                    source_module=source_module,
                    location=loc,
                )
            )
            return

        for child in clause_node.children:
            if child.type == "identifier":
                # Default import: import PaymentService from './payment';
                result.imports.append(
                    ExtractedImport(
                        file_path=file_path,
                        imported_name=node_text(child),
                        source_module=source_module,
                        is_default=True,
                        location=loc,
                    )
                )

            elif child.type == "namespace_import":
                # Namespace import: import * as api from './api';
                for sub in child.children:
                    if sub.type == "identifier":
                        result.imports.append(
                            ExtractedImport(
                                file_path=file_path,
                                imported_name="*",
                                source_module=source_module,
                                alias=node_text(sub),
                                is_namespace=True,
                                location=loc,
                            )
                        )

            elif child.type == "named_imports":
                # Named imports: import { charge, refund as r } from './payment';
                for spec in child.children:
                    if spec.type == "import_specifier":
                        name_n = spec.child_by_field_name("name")
                        alias_n = spec.child_by_field_name("alias")
                        if name_n:
                            imported_name = node_text(name_n)
                            alias = node_text(alias_n) if alias_n else None
                            result.imports.append(
                                ExtractedImport(
                                    file_path=file_path,
                                    imported_name=imported_name,
                                    source_module=source_module,
                                    alias=alias,
                                    is_default=False,
                                    location=loc,
                                )
                            )

    def _extract_export_clause(
        self,
        node: tree_sitter.Node,
        file_path: str,
        node_text,
        result: FileExtractionResult,
    ):
        """Extracts export statements (named, default, or re-exports)."""
        loc = SourceLocation.from_node(node)
        is_default = any(child.type == "default" for child in node.children)

        # 1. Direct declaration export: export function foo() / export class Bar
        decl = node.child_by_field_name("declaration")
        if decl:
            name_node = decl.child_by_field_name("name")
            if name_node:
                result.exports.append(
                    ExtractedExport(
                        file_path=file_path,
                        name=node_text(name_node),
                        is_default=is_default,
                        location=loc,
                    )
                )
            elif decl.type in ("lexical_declaration", "variable_declaration"):
                for declarator in decl.children:
                    if declarator.type == "variable_declarator":
                        d_name = declarator.child_by_field_name("name")
                        if d_name:
                            result.exports.append(
                                ExtractedExport(
                                    file_path=file_path,
                                    name=node_text(d_name),
                                    is_default=is_default,
                                    location=loc,
                                )
                            )
            return

        # 2. export default identifier / expression: export default PaymentService;
        if is_default:
            value_node = node.child_by_field_name("value")
            if value_node and value_node.type == "identifier":
                result.exports.append(
                    ExtractedExport(
                        file_path=file_path,
                        name=node_text(value_node),
                        is_default=True,
                        location=loc,
                    )
                )
            return

        # 3. Export clause: export { a, b as c };
        for child in node.children:
            if child.type == "export_clause":
                for spec in child.children:
                    if spec.type == "export_specifier":
                        name_n = spec.child_by_field_name("name")
                        alias_n = spec.child_by_field_name("alias")
                        # The exported name is the alias if provided, otherwise the identifier name
                        exported_name = node_text(alias_n or name_n) if (alias_n or name_n) else ""
                        if exported_name:
                            result.exports.append(
                                ExtractedExport(
                                    file_path=file_path,
                                    name=exported_name,
                                    is_default=False,
                                    location=loc,
                                )
                            )
