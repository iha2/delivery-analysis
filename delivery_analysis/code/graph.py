"""Code graph: import edges between repository files and the file weights built from them."""
from __future__ import annotations

import json
import math
import posixpath
import re
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Set, Tuple

from delivery_analysis.code import languages

MAX_FILE_BYTES = 1_000_000
ROOT_NAMES = {"main.py", "__main__.py", "manage.py", "app.py", "wsgi.py", "asgi.py", "program.cs", "startup.cs"}
ROOT_STEMS = {"index", "main", "app"}
SOURCE_ROOTS = {"", "src", "lib", "app"}
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
JS_LANGUAGES = {"javascript", "typescript"}
TYPE_NODES = {
    "class_declaration", "interface_declaration", "enum_declaration", "struct_declaration",
    "record_declaration", "record_struct_declaration", "delegate_declaration",
    "annotation_type_declaration",
}


class FileNode(NamedTuple):
    path: str
    language: Optional[str]
    fan_in: int
    is_root: bool
    weight: float


def weight(fan_in: int, is_root: bool) -> float:
    return 1 + math.log2(1 + fan_in) + (1 if is_root else 0)


def _walk(root: Any) -> Iterator[Any]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _text(node: Any) -> str:
    return node.text.decode("utf-8", "ignore") if node is not None and node.text else ""


# ---------------------------------------------------------------- Python

def _python_modules(paths: List[str]) -> Dict[str, str]:
    modules: Dict[str, str] = {}
    for path in sorted(paths, key=lambda p: (p.count("/"), p)):
        parts = path[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        modules.setdefault(".".join(parts), path)
        if parts[0] == "src" and len(parts) > 1:
            modules.setdefault(".".join(parts[1:]), path)
    return modules


def _dotted(node: Any) -> str:
    if node.type == "aliased_import":
        node = node.child_by_field_name("name") or node
    return _text(node)


def _python_edges(path: str, root: Any, modules: Dict[str, str], files: Set[str]) -> Set[str]:
    found: Set[str] = set()

    def rel_lookup(parts: List[str]) -> Optional[str]:
        base = "/".join(parts)
        for candidate in (base + ".py", base + "/__init__.py" if base else "__init__.py"):
            if candidate in files:
                return candidate
        return None

    for node in _walk(root):
        if node.type == "import_statement":
            for child in node.children_by_field_name("name"):
                name = _dotted(child)
                parts = name.split(".")
                for size in range(len(parts), 0, -1):
                    hit = modules.get(".".join(parts[:size]))
                    if hit:
                        found.add(hit)
                        break
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            names = [_dotted(c) for c in node.children_by_field_name("name") if c.type != "wildcard_import"]
            if module_node is None:
                continue
            if module_node.type == "relative_import":
                prefix = next((c for c in module_node.children if c.type == "import_prefix"), None)
                level = _text(prefix).count(".")
                dotted = next((c for c in module_node.children if c.type == "dotted_name"), None)
                module = _text(dotted).split(".") if dotted is not None else []
                here = path.split("/")[:-1]
                if level - 1 > len(here):
                    continue
                base = here[: len(here) - (level - 1)] + module
                hit = rel_lookup(base)
                if hit:
                    found.add(hit)
                for name in names:
                    sub = rel_lookup(base + [name])
                    if sub:
                        found.add(sub)
            else:
                module = _text(module_node)
                hit = modules.get(module)
                if hit:
                    found.add(hit)
                for name in names:
                    sub = modules.get(module + "." + name)
                    if sub:
                        found.add(sub)
    return found


# ---------------------------------------------------------------- JavaScript / TypeScript

def _string_value(node: Any) -> Optional[str]:
    if node is None or node.type != "string":
        return None
    return "".join(_text(c) for c in node.children if c.type == "string_fragment")


def _js_specifiers(root: Any) -> List[str]:
    specs: List[str] = []
    for node in _walk(root):
        value = None
        if node.type in ("import_statement", "export_statement"):
            value = _string_value(node.child_by_field_name("source"))
        elif node.type == "import_require_clause":
            value = next((_string_value(c) for c in node.children if c.type == "string"), None)
        elif node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and (func.type == "import" or (func.type == "identifier" and _text(func) == "require")):
                args = node.child_by_field_name("arguments")
                first = next((c for c in args.children if c.type not in ("(", ")", ",")), None) if args else None
                value = _string_value(first)
        if value:
            specs.append(value)
    return specs


def _read_tsconfig(files: Dict[str, bytes]) -> Tuple[Optional[str], Dict[str, List[str]]]:
    raw = files.get("tsconfig.json")
    if raw is None:
        return None, {}
    text = raw.decode("utf-8", "ignore").lstrip("\ufeff")
    text = re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
        lambda m: m.group(0) if m.group(0).startswith('"') else "",
        text,
        flags=re.S,
    )
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        options = json.loads(text).get("compilerOptions") or {}
        base = options.get("baseUrl")
        paths = options.get("paths") or {}
        base = posixpath.normpath(base) if isinstance(base, str) else None
        if base == ".":
            base = ""
        return base, {k: [t for t in v if isinstance(t, str)] for k, v in paths.items() if isinstance(v, list)}
    except (ValueError, AttributeError):
        return None, {}


def _js_try(base: str, js_files: Set[str]) -> Optional[str]:
    if base.startswith("../") or base == "..":
        return None
    candidates = [base]
    candidates += [base + ext for ext in JS_EXTS]
    candidates += [base + "/index" + ext for ext in JS_EXTS]
    stem, ext = posixpath.splitext(base)
    if ext in (".js", ".jsx", ".mjs", ".cjs"):
        candidates += [stem + ".ts", stem + ".tsx"]
    return next((c for c in candidates if c in js_files), None)


def _js_resolve(
    spec: str, path: str, js_files: Set[str], base_url: Optional[str], aliases: Dict[str, List[str]]
) -> Optional[str]:
    if spec.startswith("."):
        return _js_try(posixpath.normpath(posixpath.join(posixpath.dirname(path), spec)), js_files)
    bases: List[str] = []
    for pattern, targets in aliases.items():
        if "*" in pattern:
            head, tail = pattern.split("*", 1)
            if spec.startswith(head) and spec.endswith(tail) and len(spec) >= len(head) + len(tail):
                middle = spec[len(head): len(spec) - len(tail)]
                bases += [t.replace("*", middle) for t in targets]
        elif spec == pattern:
            bases += targets
    root = base_url or ""
    resolved = [posixpath.normpath(posixpath.join(root, b)) for b in bases]
    if base_url is not None:
        resolved.append(posixpath.normpath(posixpath.join(root, spec)))
    for candidate in resolved:
        hit = _js_try(candidate, js_files)
        if hit:
            return hit
    return None


# ---------------------------------------------------------------- C# and Java

class _TypeInfo(NamedTuple):
    declared: Set[str]
    namespaces: Set[str]
    imports: Set[str]
    refs: Set[str]
    has_main: bool


def _type_info(language: str, root: Any) -> _TypeInfo:
    declared: Set[str] = set()
    namespaces: Set[str] = set()
    imports: Set[str] = set()
    refs: Set[str] = set()
    has_main = False
    stack: List[Tuple[Any, str]] = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        kind = node.type
        child_prefix = prefix
        if kind in ("identifier", "type_identifier"):
            refs.add(_text(node))
        elif kind in TYPE_NODES:
            name = _text(node.child_by_field_name("name"))
            if name:
                declared.add(name)
        elif kind in ("namespace_declaration", "file_scoped_namespace_declaration"):
            name = _text(node.child_by_field_name("name"))
            if name:
                child_prefix = prefix + "." + name if prefix else name
                namespaces.add(child_prefix)
        elif kind == "package_declaration":
            name = next((_text(c) for c in node.children if c.type in ("scoped_identifier", "identifier")), "")
            if name:
                namespaces.add(name)
        elif kind == "using_directive":
            is_static = any(c.type == "static" for c in node.children)
            name = next(
                (_text(c) for c in reversed(node.children) if c.type in ("qualified_name", "identifier")), ""
            )
            if name:
                imports.add(name)
                if is_static and "." in name:
                    imports.add(name.rsplit(".", 1)[0])
        elif kind == "import_declaration":
            name = next((_text(c) for c in node.children if c.type in ("scoped_identifier", "identifier")), "")
            wildcard = any(c.type == "asterisk" for c in node.children)
            static = any(c.type == "static" for c in node.children)
            if name:
                imports.add(name)
                if static:
                    parts = name.split(".")
                    imports.update(".".join(parts[:i]) for i in range(1, len(parts)))
                elif not wildcard and "." in name:
                    imports.add(name.rsplit(".", 1)[0])
        elif kind == "method_declaration" and language == "java":
            if _text(node.child_by_field_name("name")) == "main":
                mods = next((_text(c) for c in node.children if c.type == "modifiers"), "")
                if "public" in mods.split() and "static" in mods.split():
                    has_main = True
        for child in node.children:
            stack.append((child, child_prefix))
    return _TypeInfo(declared, namespaces, imports, refs, has_main)


def _namespace_scope(language: str, info: _TypeInfo) -> Set[str]:
    scope = set(info.namespaces) | set(info.imports)
    if language == "csharp":
        scope.add("")
        for ns in info.namespaces:
            parts = ns.split(".")
            scope.update(".".join(parts[:i]) for i in range(1, len(parts)))
    elif not info.namespaces:
        scope.add("")
    return scope


def _type_edges(language: str, infos: Dict[str, _TypeInfo]) -> Dict[str, Set[str]]:
    index: Dict[str, List[str]] = defaultdict(list)
    for path, info in infos.items():
        for name in info.declared:
            index[name].append(path)
    edges: Dict[str, Set[str]] = defaultdict(set)
    for path, info in infos.items():
        scope = _namespace_scope(language, info)
        for name in info.refs:
            for target in index.get(name, ()):
                target_ns = infos[target].namespaces or {""}
                if target != path and target_ns & scope:
                    edges[path].add(target)
    return edges


# ---------------------------------------------------------------- build

def _is_root_name(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name in ROOT_NAMES:
        return True
    directory = posixpath.dirname(path)
    return directory in SOURCE_ROOTS and posixpath.splitext(name)[0] in ROOT_STEMS


def build_graph(files: Dict[str, bytes]) -> Dict[str, FileNode]:
    """Weigh every file: ignored 0, other text 0.5, code 1 + log2(1 + fan_in) + root bonus."""
    kind: Dict[str, Optional[Tuple[str, str]]] = {}
    nodes: Dict[str, FileNode] = {}
    for path, content in files.items():
        if languages.is_ignored_path(path) or languages.is_binary(path, content):
            nodes[path] = FileNode(path, None, 0, False, 0.0)
            continue
        ext = languages.extension(path)
        if ext in languages.GRAMMAR_EXTENSIONS:
            kind[path] = languages.GRAMMAR_EXTENSIONS[ext]
        elif ext in languages.PLAIN_CODE_EXTENSIONS:
            nodes[path] = FileNode(path, languages.PLAIN_CODE_EXTENSIONS[ext], 0, False, 1.0)
        else:
            nodes[path] = FileNode(path, None, 0, False, 0.5)

    parsers: Dict[str, Any] = {}
    roots: Dict[str, Any] = {}
    for path, (language, key) in kind.items():
        if key not in parsers:
            parsers[key] = languages.load_parser(key)
        parser = parsers[key]
        if parser is None:
            nodes[path] = FileNode(path, language, 0, False, 1.0)
            continue
        try:
            roots[path] = parser.parse(files[path]).root_node
        except Exception:
            roots[path] = None

    edges: Dict[str, Set[str]] = defaultdict(set)
    by_language: Dict[str, List[str]] = defaultdict(list)
    for path in roots:
        by_language[kind[path][0]].append(path)

    py = by_language.get("python", [])
    if py:
        modules = _python_modules(py)
        py_set = set(py)
        for path in py:
            if roots[path] is not None:
                edges[path] |= _python_edges(path, roots[path], modules, py_set)

    js = [p for lang in JS_LANGUAGES for p in by_language.get(lang, [])]
    if js:
        js_set = set(js)
        base_url, aliases = _read_tsconfig(files)
        for path in js:
            if roots[path] is None:
                continue
            for spec in _js_specifiers(roots[path]):
                hit = _js_resolve(spec, path, js_set, base_url, aliases)
                if hit:
                    edges[path].add(hit)

    mains: Set[str] = set()
    for language in ("csharp", "java"):
        infos = {p: _type_info(language, roots[p]) for p in by_language.get(language, []) if roots[p] is not None}
        for path, found in _type_edges(language, infos).items():
            edges[path] |= found
        mains |= {p for p, info in infos.items() if info.has_main}

    importers: Dict[str, Set[str]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            if target != source:
                importers[target].add(source)

    for path in roots:
        fan_in = len(importers.get(path, ()))
        is_root = _is_root_name(path) or path in mains
        nodes[path] = FileNode(path, kind[path][0], fan_in, is_root, weight(fan_in, is_root))
    return nodes


# ---------------------------------------------------------------- snapshot

def _git(repo_path: Path, *args: str, data: Optional[bytes] = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args], input=data, capture_output=True, check=True
    )
    return result.stdout


def _read_blobs(repo_path: Path, shas: List[str]) -> Dict[str, bytes]:
    wanted = sorted(set(shas))
    stdin = "".join(sha + "\n" for sha in wanted).encode()
    sizes: Dict[str, int] = {}
    for line in _git(repo_path, "cat-file", "--batch-check", data=stdin).decode().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob":
            sizes[parts[0]] = int(parts[2])
    keep = [sha for sha in wanted if sha in sizes and sizes[sha] <= MAX_FILE_BYTES]
    out = _git(repo_path, "cat-file", "--batch", data="".join(s + "\n" for s in keep).encode())
    blobs: Dict[str, bytes] = {}
    pos = 0
    for _ in keep:
        end = out.index(b"\n", pos)
        sha, _kind, size = out[pos:end].decode().split()
        start = end + 1
        blobs[sha] = out[start: start + int(size)]
        pos = start + int(size) + 1
    return blobs


def snapshot(conn: sqlite3.Connection, repository_id: str, repo_path: Path, now: str) -> int:
    """Weigh the files at HEAD and replace the repository's `code_file` rows; return the row count."""
    try:
        head = _git(repo_path, "rev-parse", "--verify", "HEAD").decode().strip()
    except subprocess.CalledProcessError:
        return 0
    entries: Dict[str, str] = {}
    for item in _git(repo_path, "ls-files", "-s", "-z").split(b"\0"):
        if not item:
            continue
        meta, _, raw_path = item.partition(b"\t")
        mode, sha, _stage = meta.decode().split()
        if mode in ("160000", "120000"):
            continue
        entries[raw_path.decode("utf-8", "replace").replace("\\", "/")] = sha
    blobs = _read_blobs(repo_path, list(entries.values()))
    files = {path: blobs[sha] for path, sha in entries.items() if sha in blobs}
    nodes = build_graph(files)
    rows = [
        (repository_id, n.path, n.language, n.fan_in, int(n.is_root), n.weight, head, now)
        for n in nodes.values()
    ]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM code_file WHERE repository_id = ?", (repository_id,))
        conn.executemany(
            "INSERT INTO code_file (repository_id, path, language, fan_in, is_root, weight, snapshot_sha, built_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)
