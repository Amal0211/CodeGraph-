"""Tests for RepositoryScanner in codegraph.analyzer.scanner."""

from pathlib import Path
import pytest
from codegraph.analyzer.scanner import RepositoryScanner, ScannedFile, ScanResult


def test_scanner_discovers_supported_extensions(tmp_path: Path):
    """Scanner should find .js, .jsx, .ts, .tsx and ignore unsupported formats."""
    # Create sample files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("console.log('index');", encoding="utf-8")
    (tmp_path / "src" / "App.tsx").write_text("export const App = () => null;", encoding="utf-8")
    (tmp_path / "src" / "legacy.js").write_text("var a = 1;", encoding="utf-8")
    (tmp_path / "src" / "component.jsx").write_text("export default function C() {}", encoding="utf-8")
    (tmp_path / "src" / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Readme", encoding="utf-8")

    scanner = RepositoryScanner(tmp_path)
    result = scanner.scan()

    assert isinstance(result, ScanResult)
    assert result.total_files == 4

    rel_paths = [f.relative_path for f in result.files]
    assert rel_paths == [
        "src/App.tsx",
        "src/component.jsx",
        "src/legacy.js",
        "src/index.ts",
    ] or sorted(rel_paths) == [
        "src/App.tsx",
        "src/component.jsx",
        "src/index.ts",
        "src/legacy.js",
    ]


def test_scanner_prunes_ignored_directories(tmp_path: Path):
    """Scanner must prune node_modules, .git, dist, and hidden directories."""
    # Valid source file
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.ts").write_text("export const main = 1;", encoding="utf-8")

    # Files inside ignored directories
    node_modules = tmp_path / "node_modules" / "lodash"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("module.exports = {};", encoding="utf-8")

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "bundle.js").write_text("console.log('built');", encoding="utf-8")

    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.js").write_text("// hook", encoding="utf-8")

    scanner = RepositoryScanner(tmp_path)
    result = scanner.scan()

    assert result.total_files == 1
    assert result.files[0].relative_path == "src/main.ts"


def test_scanner_normalizes_paths_with_forward_slashes(tmp_path: Path):
    """Scanner must always return forward slashes in relative_path regardless of OS."""
    nested = tmp_path / "src" / "deep" / "nested"
    nested.mkdir(parents=True)
    (nested / "service.ts").write_text("export class Service {}", encoding="utf-8")

    scanner = RepositoryScanner(tmp_path)
    result = scanner.scan()

    assert len(result.files) == 1
    file_info = result.files[0]
    assert "\\" not in file_info.relative_path
    assert file_info.relative_path == "src/deep/nested/service.ts"
    assert file_info.extension == ".ts"
    assert file_info.size_bytes > 0


def test_scanner_ignores_minified_and_map_patterns(tmp_path: Path):
    """Files matching ignore patterns such as *.min.js should be skipped."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "valid.js").write_text("console.log(1);", encoding="utf-8")
    (src / "vendor.min.js").write_text("console.log(2);", encoding="utf-8")
    (src / "bundle.bundle.js").write_text("console.log(3);", encoding="utf-8")

    scanner = RepositoryScanner(tmp_path)
    result = scanner.scan()

    assert result.total_files == 1
    assert result.files[0].relative_path == "src/valid.js"


def test_scanner_file_size_limit(tmp_path: Path):
    """Files exceeding max_file_size_bytes should be skipped."""
    src = tmp_path / "src"
    src.mkdir()
    small_file = src / "small.ts"
    small_file.write_text("let a = 1;", encoding="utf-8")

    large_file = src / "large.ts"
    large_file.write_text("x" * 2000, encoding="utf-8")

    # Set threshold to 1000 bytes
    scanner = RepositoryScanner(tmp_path, max_file_size_bytes=1000)
    result = scanner.scan()

    assert result.total_files == 1
    assert result.files[0].relative_path == "src/small.ts"


def test_scanner_invalid_path_raises_error(tmp_path: Path):
    """Non-existent path or file path passed as root should raise appropriate errors."""
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        RepositoryScanner(non_existent).scan()

    file_path = tmp_path / "file.txt"
    file_path.write_text("hello", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        RepositoryScanner(file_path).scan()
