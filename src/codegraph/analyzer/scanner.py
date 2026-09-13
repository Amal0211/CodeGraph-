"""Repository scanner for discovering and filtering source files."""

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set


# Standard source extensions supported in Phase 1
DEFAULT_EXTENSIONS: Set[str] = {".js", ".jsx", ".ts", ".tsx"}

# Directories that must never be scanned (vendor, build outputs, version control, cache)
DEFAULT_IGNORE_DIRS: Set[str] = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    ".nuxt",
    ".cache",
    ".turbo",
    ".idea",
    ".vscode",
    "__pycache__",
    ".venv",
    "venv",
    "env",
}

# File patterns to exclude (minified bundles, sourcemaps)
DEFAULT_IGNORE_PATTERNS: Set[str] = {
    "*.min.js",
    "*.min.jsx",
    "*.bundle.js",
    "*.bundle.ts",
    "*.d.ts.map",
    "*.js.map",
}

# 1 MB threshold for skipping massive generated artifacts
DEFAULT_MAX_FILE_SIZE_BYTES: int = 1_048_576


@dataclass(frozen=True)
class ScannedFile:
    """Represents a discovered source file with normalized paths and metadata."""

    absolute_path: Path
    relative_path: str  # Always normalized with forward slashes (e.g., 'src/utils/math.ts')
    extension: str  # e.g., '.ts'
    size_bytes: int


@dataclass
class ScanResult:
    """Encapsulates the outcome of a repository scan."""

    root_path: Path
    files: list[ScannedFile] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)


class RepositoryScanner:
    """Scans a repository filesystem tree and yields valid JS/TS source files."""

    def __init__(
        self,
        root_path: str | Path,
        extensions: Optional[Set[str]] = None,
        ignore_dirs: Optional[Set[str]] = None,
        ignore_patterns: Optional[Set[str]] = None,
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    ) -> None:
        self.root_path = Path(root_path).resolve()
        self.extensions = {ext.lower() for ext in (extensions or DEFAULT_EXTENSIONS)}
        self.ignore_dirs = set(ignore_dirs or DEFAULT_IGNORE_DIRS)
        self.ignore_patterns = set(ignore_patterns or DEFAULT_IGNORE_PATTERNS)
        self.max_file_size_bytes = max_file_size_bytes

    def scan(self) -> ScanResult:
        """Walks the repository directory tree, prunes ignored directories, and returns discovered files."""
        if not self.root_path.exists():
            raise FileNotFoundError(f"Repository root does not exist: {self.root_path}")

        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Repository root is not a directory: {self.root_path}")

        discovered_files: list[ScannedFile] = []

        # os.walk provides top-down traversal with in-place directory pruning
        for dirpath_str, dirnames, filenames in os.walk(self.root_path, followlinks=False):
            # In-place directory pruning: Removing unwanted folders here instructs
            # os.walk to NEVER recurse into them, saving immense I/O and time.
            dirnames[:] = [
                d for d in dirnames
                if d not in self.ignore_dirs and not d.startswith(".")
            ]

            current_dir = Path(dirpath_str)

            for filename in filenames:
                file_ext = Path(filename).suffix.lower()

                # 1. Fast check: Extension matching
                if file_ext not in self.extensions:
                    continue

                # 2. Pattern matching check: Exclude minified or map files
                if any(fnmatch.fnmatch(filename, pattern) for pattern in self.ignore_patterns):
                    continue

                full_path = current_dir / filename

                try:
                    stat_result = full_path.stat()
                except (OSError, PermissionError):
                    # Gracefully skip files with permission or filesystem errors
                    continue

                file_size = stat_result.st_size

                # 3. Guard against huge bundles or generated files
                if file_size > self.max_file_size_bytes:
                    continue

                # Compute relative path and normalize to POSIX forward slashes
                relative_path = full_path.relative_to(self.root_path).as_posix()

                discovered_files.append(
                    ScannedFile(
                        absolute_path=full_path,
                        relative_path=relative_path,
                        extension=file_ext,
                        size_bytes=file_size,
                    )
                )

        # Sort files deterministically by relative path for consistent outputs across platforms
        discovered_files.sort(key=lambda f: f.relative_path)

        return ScanResult(root_path=self.root_path, files=discovered_files)
