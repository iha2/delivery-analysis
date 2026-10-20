"""Language tables and lazy tree-sitter parser loading."""
from __future__ import annotations

import posixpath
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

# extension -> (language label, grammar key)
GRAMMAR_EXTENSIONS: Dict[str, Tuple[str, str]] = {
    ".py": ("python", "python"),
    ".js": ("javascript", "javascript"),
    ".jsx": ("javascript", "javascript"),
    ".mjs": ("javascript", "javascript"),
    ".cjs": ("javascript", "javascript"),
    ".ts": ("typescript", "typescript"),
    ".tsx": ("typescript", "tsx"),
    ".cs": ("csharp", "csharp"),
    ".java": ("java", "java"),
}

# code with no grammar here: weighed 1, no import edges
PLAIN_CODE_EXTENSIONS = {
    ".go": "go", ".rb": "ruby", ".php": "php", ".rs": "rust", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".m": "objc", ".scala": "scala", ".vue": "vue", ".svelte": "svelte",
    ".dart": "dart", ".lua": "lua", ".pl": "perl", ".r": "r", ".sh": "shell", ".ps1": "powershell",
    ".sql": "sql", ".vb": "vb", ".fs": "fsharp", ".groovy": "groovy", ".ex": "elixir",
    ".exs": "elixir", ".erl": "erlang", ".hs": "haskell", ".clj": "clojure",
}

IGNORED_DIRS = {"node_modules", "dist", "build", "bin", "obj", "vendor"}
IGNORED_SUFFIXES = (".map", ".snap", ".lock", ".designer.cs")
IGNORED_NAMES = {"package-lock.json", "go.sum", "npm-shrinkwrap.json"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".pdf", ".zip", ".gz", ".tar",
    ".tgz", ".7z", ".rar", ".jar", ".war", ".dll", ".exe", ".so", ".dylib", ".class", ".pyc", ".o",
    ".a", ".lib", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".bin", ".pdb", ".nupkg", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".sqlite", ".db",
}

_MODULES = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "csharp": ("tree_sitter_c_sharp", "language"),
    "java": ("tree_sitter_java", "language"),
}


def extension(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def is_ignored_path(path: str) -> bool:
    parts = path.split("/")
    if any(part in IGNORED_DIRS for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    if name in IGNORED_NAMES or name.endswith(IGNORED_SUFFIXES):
        return True
    return ".min." in name


def is_binary(path: str, content: bytes) -> bool:
    return extension(path) in BINARY_EXTENSIONS or b"\x00" in content[:8000]


@lru_cache(maxsize=None)
def _load(grammar_key: str) -> Optional[Any]:
    try:
        import importlib

        from tree_sitter import Language, Parser

        module_name, func = _MODULES[grammar_key]
        module = importlib.import_module(module_name)
        return Parser(Language(getattr(module, func)()))
    except Exception:
        return None


def load_parser(grammar_key: str) -> Optional[Any]:
    """Return a tree-sitter parser for the grammar, or None when it is not installed."""
    return _load(grammar_key)
