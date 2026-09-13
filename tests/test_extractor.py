"""Tests for SymbolExtractor in codegraph.analyzer.extractor."""

from codegraph.analyzer.parser import CodeParser
from codegraph.analyzer.extractor import SymbolExtractor


def parse_and_extract(code: str, file_path: str = "src/demo.ts", ext: str = ".ts"):
    parser = CodeParser()
    tree = parser.parse(code, ext)
    extractor = SymbolExtractor()
    return extractor.extract(file_path, tree, code.encode("utf-8"))


def test_extract_function_declaration():
    """Extracts top-level function declarations and exact coordinates."""
    code = """
function calculateTotal(price: number, tax: number): number {
    return price + tax;
}
"""
    result = parse_and_extract(code, "src/math.ts")
    assert len(result.symbols) == 1
    sym = result.symbols[0]
    assert sym.name == "calculateTotal"
    assert sym.kind == "function"
    assert sym.qualified_name == "src/math.ts::calculateTotal"
    assert sym.location.start_line == 2


def test_extract_arrow_function_declarator():
    """Extracts arrow functions assigned to const/let variables."""
    code = "const formatCurrency = (amount: number) => `$${amount}`;";
    result = parse_and_extract(code, "src/utils.ts")
    assert len(result.symbols) == 1
    sym = result.symbols[0]
    assert sym.name == "formatCurrency"
    assert sym.kind == "function"
    assert sym.qualified_name == "src/utils.ts::formatCurrency"


def test_extract_class_and_methods():
    """Extracts classes, inner methods, and establishes hierarchical naming."""
    code = """
export class OrderService {
    createOrder(id: string) {
        return id;
    }

    cancelOrder(id: string) {
        return false;
    }
}
"""
    result = parse_and_extract(code, "src/order.service.ts")
    # OrderService (class), createOrder (method), cancelOrder (method)
    assert len(result.symbols) == 3

    cls = next(s for s in result.symbols if s.kind == "class")
    assert cls.name == "OrderService"
    assert cls.qualified_name == "src/order.service.ts::OrderService"

    methods = [s for s in result.symbols if s.kind == "method"]
    assert len(methods) == 2
    method_names = [m.name for m in methods]
    assert "createOrder" in method_names
    assert "cancelOrder" in method_names
    assert methods[0].parent_name == "OrderService"
    assert methods[0].qualified_name == "src/order.service.ts::OrderService.createOrder"


def test_extract_interface():
    """Extracts TypeScript interface declarations."""
    code = """
interface UserProfile {
    id: string;
    email: string;
}
"""
    result = parse_and_extract(code, "src/types.ts")
    assert len(result.symbols) == 1
    assert result.symbols[0].name == "UserProfile"
    assert result.symbols[0].kind == "interface"


def test_extract_imports():
    """Extracts named, default, and namespace imports."""
    code = """
import { charge, refund as returnMoney } from './payment';
import Logger from './logger';
import * as utils from '../utils';
"""
    result = parse_and_extract(code, "src/main.ts")
    assert len(result.imports) == 4

    charge_imp = next(i for i in result.imports if i.imported_name == "charge")
    assert charge_imp.source_module == "./payment"
    assert charge_imp.is_default is False

    refund_imp = next(i for i in result.imports if i.imported_name == "refund")
    assert refund_imp.alias == "returnMoney"

    logger_imp = next(i for i in result.imports if i.imported_name == "Logger")
    assert logger_imp.is_default is True

    utils_imp = next(i for i in result.imports if i.is_namespace)
    assert utils_imp.alias == "utils"


def test_extract_exports():
    """Extracts export statements."""
    code = """
export function add(a: number, b: number) { return a + b; }
export default class App {}
export { add as sum };
"""
    result = parse_and_extract(code, "src/index.ts")
    export_names = [e.name for e in result.exports]
    assert "add" in export_names
    assert "App" in export_names
    assert "sum" in export_names

    default_exp = next(e for e in result.exports if e.name == "App")
    assert default_exp.is_default is True


def test_extract_calls_and_callers():
    """Tracks caller context for direct and member call expressions."""
    code = """
function processOrder() {
    validate();
    paymentService.charge();
}
"""
    result = parse_and_extract(code, "src/order.ts")
    assert len(result.calls) == 2

    c1 = result.calls[0]
    assert c1.caller_qualified_name == "src/order.ts::processOrder"
    assert c1.callee_name == "validate"
    assert c1.receiver_name is None

    c2 = result.calls[1]
    assert c2.caller_qualified_name == "src/order.ts::processOrder"
    assert c2.callee_name == "charge"
    assert c2.receiver_name == "paymentService"
