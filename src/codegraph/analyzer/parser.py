"""Tree-sitter parser initialization and AST generation for JS/TS."""

from pathlib import Path
from typing import Dict, Union
import tree_sitter
from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript


class CodeParser:
    """Parses JavaScript and TypeScript source files into Tree-sitter ASTs."""

    def __init__(self) -> None:
        # Initialize languages
        self.js_language = Language(tree_sitter_javascript.language())
        self.ts_language = Language(tree_sitter_typescript.language_typescript())
        self.tsx_language = Language(tree_sitter_typescript.language_tsx())

        # Map extensions to languages
        self._language_map: Dict[str, Language] = {
            ".js": self.js_language,
            ".jsx": self.js_language,
            ".mjs": self.js_language,
            ".cjs": self.js_language,
            ".ts": self.ts_language,
            ".mts": self.ts_language,
            ".cts": self.ts_language,
            ".tsx": self.tsx_language,
        }

        # Cache parsers for performance
        self._parsers: Dict[str, Parser] = {}

    def _get_parser_for_extension(self, ext: str) -> Parser:
        ext_lower = ext.lower()
        if ext_lower not in self._language_map:
            raise ValueError(f"Unsupported file extension for parsing: {ext}")

        if ext_lower not in self._parsers:
            lang = self._language_map[ext_lower]
            self._parsers[ext_lower] = Parser(lang)

        return self._parsers[ext_lower]

    def parse(self, code: Union[str, bytes], extension: str) -> tree_sitter.Tree:
        """Parses raw source code string or bytes into a Tree-sitter Tree."""
        parser = self._get_parser_for_extension(extension)
        if isinstance(code, str):
            code_bytes = code.encode("utf-8")
        else:
            code_bytes = code
        return parser.parse(code_bytes)

    def parse_file(self, file_path: Union[str, Path]) -> tuple[tree_sitter.Tree, bytes]:
        """Reads a file from disk and parses it into an AST, returning (tree, code_bytes)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        code_bytes = path.read_bytes()
        tree = self.parse(code_bytes, path.suffix)
        return tree, code_bytes
