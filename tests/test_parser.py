"""Tests for CodeParser using Tree-sitter."""

from pathlib import Path
import pytest
from codegraph.analyzer.parser import CodeParser


def test_parser_initialization():
    """Parser should initialize and hold language references."""
    parser = CodeParser()
    assert parser.js_language is not None
    assert parser.ts_language is not None
    assert parser.tsx_language is not None


def test_parser_parses_javascript():
    """Parser parses JavaScript code into a valid AST."""
    parser = CodeParser()
    code = "function add(a, b) { return a + b; }"
    tree = parser.parse(code, ".js")
    assert tree.root_node.type == "program"
    assert len(tree.root_node.children) > 0


def test_parser_parses_typescript():
    """Parser parses TypeScript code with type annotations."""
    parser = CodeParser()
    code = "interface User { id: string; }\nfunction getUser(id: string): User { return { id }; }"
    tree = parser.parse(code, ".ts")
    assert tree.root_node.type == "program"
    # Should contain interface_declaration and function_declaration
    child_types = [c.type for c in tree.root_node.children]
    assert "interface_declaration" in child_types
    assert "function_declaration" in child_types


def test_parser_parses_tsx():
    """Parser parses TSX with JSX syntax."""
    parser = CodeParser()
    code = "export const Component = () => <div>Hello</div>;"
    tree = parser.parse(code, ".tsx")
    assert tree.root_node.type == "program"


def test_parser_error_tolerance():
    """Parser tolerates syntax errors without throwing exceptions."""
    parser = CodeParser()
    # Code with deliberate syntax error
    broken_code = "function broken( { return"
    tree = parser.parse(broken_code, ".ts")
    assert tree.root_node is not None
    # Tree-sitter includes ERROR node or has_error flag
    assert tree.root_node.has_error is True


def test_parser_parse_file(tmp_path: Path):
    """Parser parses directly from a file on disk."""
    parser = CodeParser()
    file_path = tmp_path / "test.ts"
    file_path.write_text("export const PI = 3.14;", encoding="utf-8")

    tree, code_bytes = parser.parse_file(file_path)
    assert tree.root_node.type == "program"
    assert b"PI" in code_bytes


def test_parser_unsupported_extension_raises_value_error():
    """Parser should reject unsupported extensions."""
    parser = CodeParser()
    with pytest.raises(ValueError, match="Unsupported file extension"):
        parser.parse("print('hello')", ".py")
