"""Tests for KnowledgeGraphBuilder in codegraph.graph.builder."""

from pathlib import Path
from codegraph.analyzer.extractor import SymbolExtractor
from codegraph.analyzer.parser import CodeParser
from codegraph.analyzer.resolver import ReferenceResolver
from codegraph.analyzer.scanner import RepositoryScanner
from codegraph.db.database import DatabaseManager
from codegraph.graph.builder import KnowledgeGraphBuilder


def test_build_and_save_demo_repo_graph():
    """Builds and persists a full knowledge graph for demo-repo into SQLite."""
    demo_path = Path(__file__).parent.parent / "demo-repo"
    assert demo_path.exists()

    # 1. Scan
    scanner = RepositoryScanner(demo_path)
    scan_res = scanner.scan()

    # 2. Parse & Extract
    parser = CodeParser()
    extractor = SymbolExtractor()
    extractions = {}
    for sf in scan_res.files:
        tree, code_bytes = parser.parse_file(sf.absolute_path)
        extractions[sf.relative_path] = extractor.extract(sf.relative_path, tree, code_bytes)

    # 3. Resolve
    resolver = ReferenceResolver(extractions)
    res_result = resolver.resolve()

    # 4. Build & Save into SQLite
    db = DatabaseManager(":memory:")
    db.initialize_schema()

    builder = KnowledgeGraphBuilder()
    repo_model = builder.build_and_save(
        repo_name="demo-repo",
        root_path=str(demo_path),
        scan_result=scan_res,
        resolution_result=res_result,
        db=db,
    )

    # Verify repository record in DB
    saved_repo = db.get_repository(repo_model.id)
    assert saved_repo is not None
    assert saved_repo["name"] == "demo-repo"
    assert saved_repo["file_count"] == 3
    assert saved_repo["node_count"] > 0
    assert saved_repo["edge_count"] > 0

    # Verify nodes in DB
    all_nodes = db.get_nodes_by_repo(repo_model.id)
    node_types = {n["type"] for n in all_nodes}
    assert "repository" in node_types
    assert "file" in node_types
    assert "function" in node_types
    assert "class" in node_types
    assert "method" in node_types

    # Verify file nodes
    file_nodes = db.get_nodes_by_repo(repo_model.id, node_type="file")
    file_names = {f["name"] for f in file_nodes}
    assert file_names == {"order.ts", "payment.ts", "user.ts"}

    # Verify method parenting (chargeCard parent is PaymentService class)
    payment_class = db.get_node_by_qualified_name(repo_model.id, "payment.ts::PaymentService")
    charge_method = db.get_node_by_qualified_name(repo_model.id, "payment.ts::PaymentService.chargeCard")
    assert payment_class is not None
    assert charge_method is not None
    assert charge_method["parent_id"] == payment_class["id"]

    # Verify CALLS edge in DB: createOrder -> quickCharge
    create_order_fn = db.get_node_by_qualified_name(repo_model.id, "order.ts::createOrder")
    quick_charge_fn = db.get_node_by_qualified_name(repo_model.id, "payment.ts::quickCharge")
    assert create_order_fn is not None
    assert quick_charge_fn is not None

    outgoing_calls = db.get_outgoing_edges(create_order_fn["id"], edge_type="CALLS")
    target_ids = {e["target_id"] for e in outgoing_calls}
    assert quick_charge_fn["id"] in target_ids

    # Verify Callers query (Who calls quickCharge?)
    incoming_calls = db.get_incoming_edges(quick_charge_fn["id"], edge_type="CALLS")
    source_ids = {e["source_id"] for e in incoming_calls}
    assert create_order_fn["id"] in source_ids

    db.close()
