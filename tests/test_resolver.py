"""Tests for ReferenceResolver in codegraph.analyzer.resolver."""

from codegraph.analyzer.parser import CodeParser
from codegraph.analyzer.extractor import FileExtractionResult, SymbolExtractor
from codegraph.analyzer.resolver import ReferenceResolver


def analyze_repo_files(files_dict: dict[str, str]):
    """Helper to parse, extract, and resolve a dictionary of {file_path: code}."""
    parser = CodeParser()
    extractor = SymbolExtractor()
    extractions = {}

    for file_path, code in files_dict.items():
        ext = "." + file_path.split(".")[-1]
        tree = parser.parse(code, ext)
        extractions[file_path] = extractor.extract(file_path, tree, code.encode("utf-8"))

    resolver = ReferenceResolver(extractions)
    return resolver.resolve()


def test_resolver_module_path_resolution():
    """Resolves relative specifiers with candidate extensions."""
    resolver = ReferenceResolver(
        extractions={
            "src/order.ts": FileExtractionResult(file_path="src/order.ts"),
            "src/payment.ts": FileExtractionResult(file_path="src/payment.ts"),
            "src/utils/logger.js": FileExtractionResult(file_path="src/utils/logger.js"),
        }
    )

    # ./payment from src/order.ts -> src/payment.ts
    assert resolver.resolve_module_path("src/order.ts", "./payment") == "src/payment.ts"

    # ../utils/logger from src/sub/handler.ts -> src/utils/logger.js
    assert resolver.resolve_module_path("src/sub/handler.ts", "../utils/logger") == "src/utils/logger.js"

    # Non-relative module (npm package) should return None
    assert resolver.resolve_module_path("src/order.ts", "express") is None


def test_resolver_cross_file_call():
    """Verifies that calling an imported function links to the target definition."""
    payment_code = """
export function charge(amount: number) {
    return true;
}
"""
    order_code = """
import { charge } from './payment';

export function createOrder() {
    charge(100);
}
"""
    result = analyze_repo_files(
        {
            "src/payment.ts": payment_code,
            "src/order.ts": order_code,
        }
    )

    # Find CALLS edges
    call_edges = [e for e in result.edges if e.type == "CALLS"]
    assert len(call_edges) == 1

    call_edge = call_edges[0]
    assert call_edge.source == "src/order.ts::createOrder"
    assert call_edge.target == "src/payment.ts::charge"
    assert call_edge.metadata["confidence"] == 1.0


def test_resolver_creates_imports_edges():
    """Generates IMPORTS edges between dependent files."""
    code_a = "import { b } from './b';"
    code_b = "export const b = 1;"

    result = analyze_repo_files(
        {
            "src/a.ts": code_a,
            "src/b.ts": code_b,
        }
    )

    import_edges = [e for e in result.edges if e.type == "IMPORTS"]
    assert len(import_edges) == 1
    assert import_edges[0].source == "src/a.ts"
    assert import_edges[0].target == "src/b.ts"


def test_resolver_local_function_call():
    """Resolves calls to functions defined within the same file."""
    code = """
function helper() {
    return 42;
}

export function main() {
    helper();
}
"""
    result = analyze_repo_files({"src/main.ts": code})

    call_edges = [e for e in result.edges if e.type == "CALLS"]
    assert len(call_edges) == 1
    assert call_edges[0].source == "src/main.ts::main"
    assert call_edges[0].target == "src/main.ts::helper"


def test_resolver_class_method_contains_edge():
    """Generates CONTAINS edges from class to methods."""
    code = """
class Calculator {
    add() { return 1; }
}
"""
    result = analyze_repo_files({"src/calc.ts": code})

    contains_edges = [e for e in result.edges if e.type == "CONTAINS"]
    assert len(contains_edges) == 1
    assert contains_edges[0].source == "src/calc.ts::Calculator"
    assert contains_edges[0].target == "src/calc.ts::Calculator.add"


def test_resolver_unresolved_external_call():
    """Third-party calls like console.log are preserved in unresolved_calls."""
    code = """
function logSomething() {
    console.log("hello");
}
"""
    result = analyze_repo_files({"src/log.ts": code})

    # Should not produce a hallucinated CALLS edge
    call_edges = [e for e in result.edges if e.type == "CALLS"]
    assert len(call_edges) == 0

    # But should be captured in unresolved_calls
    assert len(result.unresolved_calls) == 1
    assert result.unresolved_calls[0].callee_name == "log"
