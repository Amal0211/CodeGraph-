"""Integration test running Scanner + Parser + Extractor + Resolver on demo-repo."""

from pathlib import Path
from codegraph.analyzer.scanner import RepositoryScanner
from codegraph.analyzer.parser import CodeParser
from codegraph.analyzer.extractor import SymbolExtractor
from codegraph.analyzer.resolver import ReferenceResolver


def test_end_to_end_analysis_on_demo_repo():
    """Runs scanner, parser, extractor, and resolver on demo-repo."""
    demo_path = Path(__file__).parent.parent / "demo-repo"
    assert demo_path.exists()

    # 1. Milestone 1: Scanner
    scanner = RepositoryScanner(demo_path)
    scan_result = scanner.scan()

    assert scan_result.total_files == 3
    rel_paths = [f.relative_path for f in scan_result.files]
    assert sorted(rel_paths) == ["order.ts", "payment.ts", "user.ts"]

    # 2. Milestone 2: Parser & Extractor
    parser = CodeParser()
    extractor = SymbolExtractor()
    extractions = {}

    for scanned_file in scan_result.files:
        tree, code_bytes = parser.parse_file(scanned_file.absolute_path)
        extractions[scanned_file.relative_path] = extractor.extract(
            scanned_file.relative_path, tree, code_bytes
        )

    # Check extracted symbols count
    # user.ts: User (interface), validateUser (function)
    # payment.ts: PaymentService (class), chargeCard (method), refundCard (method), quickCharge (function)
    # order.ts: createOrder (function)
    all_sym_names = [
        sym.name
        for data in extractions.values()
        for sym in data.symbols
    ]
    assert "User" in all_sym_names
    assert "validateUser" in all_sym_names
    assert "PaymentService" in all_sym_names
    assert "chargeCard" in all_sym_names
    assert "refundCard" in all_sym_names
    assert "quickCharge" in all_sym_names
    assert "createOrder" in all_sym_names

    # 3. Milestone 2: Resolver
    resolver = ReferenceResolver(extractions)
    resolution = resolver.resolve()

    # Find CALLS edges
    call_edges = [e for e in resolution.edges if e.type == "CALLS"]

    # createOrder calls validateUser and quickCharge
    create_order_calls = [e for e in call_edges if e.source == "order.ts::createOrder"]
    create_order_targets = {e.target for e in create_order_calls}

    assert "user.ts::validateUser" in create_order_targets
    assert "payment.ts::quickCharge" in create_order_targets

    # quickCharge calls PaymentService.chargeCard
    quick_charge_calls = [e for e in call_edges if e.source == "payment.ts::quickCharge"]
    assert any(e.target == "payment.ts::PaymentService.chargeCard" for e in quick_charge_calls)

    # IMPORTS edges
    import_edges = [e for e in resolution.edges if e.type == "IMPORTS"]
    order_imports = {e.target for e in import_edges if e.source == "order.ts"}
    assert "user.ts" in order_imports
    assert "payment.ts" in order_imports
