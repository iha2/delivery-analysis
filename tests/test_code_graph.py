import math
import os
import subprocess

import pytest

from delivery_analysis.code import graph, languages


def build(files):
    return graph.build_graph({k: v.encode() if isinstance(v, str) else v for k, v in files.items()})


def test_weight_formula():
    assert graph.weight(0, False) == 1
    assert graph.weight(3, False) == pytest.approx(3.0)
    assert graph.weight(40, True) == pytest.approx(1 + math.log2(41) + 1)


def test_python_imports_absolute_and_relative():
    nodes = build(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from .b import x\nfrom . import c\nimport pkg.d\n",
            "pkg/b.py": "x = 1\n",
            "pkg/c.py": "",
            "pkg/d.py": "from pkg.b import x\n",
            "src/lib/e.py": "import lib.f\n",
            "src/lib/f.py": "",
            "src/lib/__init__.py": "",
        }
    )
    assert nodes["pkg/b.py"].fan_in == 2
    assert nodes["pkg/c.py"].fan_in == 1
    assert nodes["pkg/d.py"].fan_in == 1
    assert nodes["pkg/a.py"].fan_in == 0
    assert nodes["src/lib/f.py"].fan_in == 1
    assert nodes["pkg/b.py"].weight == pytest.approx(1 + math.log2(3))
    assert nodes["pkg/b.py"].language == "python"


def test_python_from_package_import_submodule_and_function_scope():
    nodes = build(
        {
            "app/__init__.py": "",
            "app/util.py": "",
            "app/use.py": "def f():\n    from app import util\n",
        }
    )
    assert nodes["app/util.py"].fan_in == 1
    assert nodes["app/__init__.py"].fan_in == 1


def test_fan_in_counts_distinct_importing_files_not_self():
    nodes = build({"a.py": "import a\nimport b\nimport b\n", "b.py": ""})
    assert nodes["a.py"].fan_in == 0
    assert nodes["b.py"].fan_in == 1


def test_python_entry_files_are_roots():
    nodes = build({"main.py": "", "tools/manage.py": "", "x/__main__.py": "", "x/helper.py": ""})
    assert nodes["main.py"].is_root and nodes["tools/manage.py"].is_root and nodes["x/__main__.py"].is_root
    assert not nodes["x/helper.py"].is_root
    assert nodes["main.py"].weight == pytest.approx(2.0)


def test_js_ts_imports_and_resolution():
    nodes = build(
        {
            "src/a.ts": "import { b } from './b';\nexport * from './c';\nconst d = require('./lib');\nimport('./dyn.js');\n",
            "src/b.ts": "export const b = 1;",
            "src/c.tsx": "",
            "src/lib/index.js": "",
            "src/dyn.ts": "",
            "src/e.js": "import x from './b.js'; import './missing'; import r from 'react';",
        }
    )
    assert nodes["src/b.ts"].fan_in == 2
    assert nodes["src/c.tsx"].fan_in == 1
    assert nodes["src/lib/index.js"].fan_in == 1
    assert nodes["src/dyn.ts"].fan_in == 1
    assert nodes["src/b.ts"].language == "typescript"
    assert nodes["src/e.js"].language == "javascript"


def test_ts_import_require_and_type_imports():
    nodes = build(
        {
            "a.ts": "import x = require('./b');\nimport type { T } from './c';\nexport { d } from './d';",
            "b.ts": "",
            "c.ts": "",
            "d.ts": "",
        }
    )
    assert [nodes[p].fan_in for p in ("b.ts", "c.ts", "d.ts")] == [1, 1, 1]


def test_tsconfig_base_url_and_paths_alias():
    tsconfig = """{
      // comment
      "compilerOptions": {
        "baseUrl": "src",
        "paths": { "@ui/*": ["components/*"], "@cfg": ["config/index"], },
      },
    }"""
    nodes = build(
        {
            "tsconfig.json": tsconfig,
            "src/app.ts": "import a from '@ui/button'; import c from '@cfg'; import u from 'utils/helpers';",
            "src/components/button.ts": "",
            "src/config/index.ts": "",
            "src/utils/helpers.ts": "",
        }
    )
    assert nodes["src/components/button.ts"].fan_in == 1
    assert nodes["src/config/index.ts"].fan_in == 1
    assert nodes["src/utils/helpers.ts"].fan_in == 1
    assert nodes["tsconfig.json"].weight == 0.5


def test_js_roots_at_source_root_only():
    nodes = build({"index.js": "", "src/main.ts": "", "src/deep/index.js": "", "src/other.js": ""})
    assert nodes["index.js"].is_root and nodes["src/main.ts"].is_root
    assert not nodes["src/deep/index.js"].is_root and not nodes["src/other.js"].is_root


def test_csharp_dependency_by_type_and_namespace():
    nodes = build(
        {
            "Program.cs": "using Acme.Models;\nnamespace Acme.App { class Program { Order o; Helper h; } }",
            "Models/Order.cs": "namespace Acme.Models { public class Order {} }",
            "Svc/Helper.cs": "namespace Acme.App { public class Helper {} }",
            "Other/Order2.cs": "namespace Elsewhere { public class Gadget {} }",
            "Use2.cs": "namespace Acme.Models { class U { Order x; Gadget g; } }",
        }
    )
    assert nodes["Models/Order.cs"].fan_in == 2
    assert nodes["Svc/Helper.cs"].fan_in == 1
    assert nodes["Other/Order2.cs"].fan_in == 0
    assert nodes["Program.cs"].is_root
    assert nodes["Program.cs"].language == "csharp"


def test_csharp_file_scoped_namespace_and_startup():
    nodes = build(
        {
            "Startup.cs": "namespace A;\nclass Startup { Svc s; }",
            "Svc.cs": "namespace A;\nclass Svc {}",
        }
    )
    assert nodes["Svc.cs"].fan_in == 1
    assert nodes["Startup.cs"].is_root


def test_java_imports_package_and_main():
    nodes = build(
        {
            "src/a/Main.java": "package a;\nimport b.Util;\npublic class Main { public static void main(String[] x) { Util u; Peer p; } }",
            "src/b/Util.java": "package b;\npublic class Util {}",
            "src/a/Peer.java": "package a;\nclass Peer {}",
            "src/c/Hidden.java": "package c;\nclass Hidden {}",
            "src/d/Wild.java": "package d;\nimport c.*;\nclass Wild { Hidden h; }",
        }
    )
    assert nodes["src/b/Util.java"].fan_in == 1
    assert nodes["src/a/Peer.java"].fan_in == 1
    assert nodes["src/c/Hidden.java"].fan_in == 1
    assert nodes["src/a/Main.java"].is_root
    assert not nodes["src/b/Util.java"].is_root
    assert nodes["src/b/Util.java"].language == "java"


def test_ignored_and_other_files():
    nodes = build(
        {
            "package-lock.json": "{}",
            "yarn.lock": "x",
            "a.min.js": "x",
            "a.js.map": "x",
            "x.snap": "x",
            "Foo.Designer.cs": "class Foo {}",
            "node_modules/x/index.js": "",
            "dist/a.js": "",
            "src/build/o.py": "",
            "vendor/v.go": "",
            "bin/x.cs": "",
            "obj/y.cs": "",
            "logo.png": "text but png",
            "blob.dat": b"abc\x00def",
            "README.md": "# hi",
            "config.yaml": "a: 1",
        }
    )
    ignored = [
        "package-lock.json", "yarn.lock", "a.min.js", "a.js.map", "x.snap", "Foo.Designer.cs",
        "node_modules/x/index.js", "dist/a.js", "src/build/o.py", "vendor/v.go", "bin/x.cs",
        "obj/y.cs", "logo.png", "blob.dat",
    ]
    for path in ignored:
        assert nodes[path].weight == 0, path
    assert nodes["README.md"].weight == 0.5 and nodes["config.yaml"].weight == 0.5
    assert nodes["README.md"].language is None


def test_code_without_grammar_weighs_one():
    nodes = build({"main.go": "package main", "lib/a.rb": "x"})
    assert nodes["main.go"].weight == 1 and nodes["main.go"].fan_in == 0
    assert nodes["lib/a.rb"].weight == 1


def test_ignored_files_do_not_count_as_importers_or_targets():
    nodes = build({"a.py": "import b\n", "node_modules/p/b.py": "", "b.py": ""})
    assert nodes["b.py"].fan_in == 1
    nodes = build({"dist/a.js": "import './b'", "b.js": ""})
    assert nodes["b.js"].fan_in == 0


def test_missing_tree_sitter_falls_back_to_weight_one(monkeypatch):
    monkeypatch.setattr(languages, "load_parser", lambda key: None)
    nodes = build({"main.py": "import b", "b.py": "", "c.cs": "class C {}", "README.md": "x"})
    for path in ("main.py", "b.py", "c.cs"):
        assert nodes[path].weight == 1 and nodes[path].fan_in == 0 and not nodes[path].is_root
    assert nodes["README.md"].weight == 0.5


def test_load_parser_returns_none_when_package_missing(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("tree_sitter"):
            raise ImportError(name)
        return real(name, *a, **k)

    languages._load.cache_clear()
    monkeypatch.setattr(builtins, "__import__", fake)
    assert languages.load_parser("python") is None
    monkeypatch.undo()
    languages._load.cache_clear()
    assert languages.load_parser("python") is not None


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="Ada Example", GIT_AUTHOR_EMAIL="ada@dev.example",
               GIT_COMMITTER_NAME="Ada Example", GIT_COMMITTER_EMAIL="ada@dev.example")
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for path, content in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return repo, sha


def test_snapshot_writes_and_replaces_rows(conn, tmp_path):
    repo, sha = make_repo(
        tmp_path,
        {
            "main.py": "import util\n",
            "util.py": "",
            "docs/notes.md": "hi",
            "big.py": b"x = 1\n" * 300000,
            "pkg/sub dir/a.py": "",
        },
    )
    conn.execute(
        "INSERT INTO code_file (repository_id, path, language, fan_in, is_root, weight, snapshot_sha, built_at) "
        "VALUES ('R1','old.py','python',0,0,1,'x','t'), ('R2','keep.py','python',0,0,1,'x','t')"
    )
    count = graph.snapshot(conn, "R1", repo, "2026-10-19T00:00:00Z")
    rows = {r["path"]: r for r in conn.execute("SELECT * FROM code_file WHERE repository_id='R1'")}
    assert count == 4 and set(rows) == {"main.py", "util.py", "docs/notes.md", "pkg/sub dir/a.py"}
    assert rows["util.py"]["fan_in"] == 1 and rows["util.py"]["weight"] == pytest.approx(2.0)
    assert rows["main.py"]["is_root"] == 1 and rows["main.py"]["snapshot_sha"] == sha
    assert rows["docs/notes.md"]["weight"] == 0.5 and rows["docs/notes.md"]["language"] is None
    assert rows["main.py"]["built_at"] == "2026-10-19T00:00:00Z"
    assert conn.execute("SELECT COUNT(*) FROM code_file WHERE repository_id='R2'").fetchone()[0] == 1
    assert graph.snapshot(conn, "R1", repo, "2026-10-20T00:00:00Z") == 4
    assert conn.execute("SELECT COUNT(*) FROM code_file WHERE repository_id='R1'").fetchone()[0] == 4


def test_snapshot_git_failure_is_a_code_error(conn, tmp_path):
    from delivery_analysis.code.clone import CodeError

    not_repo = tmp_path / "plain"
    not_repo.mkdir()
    with pytest.raises(CodeError):
        graph.snapshot(conn, "R1", not_repo, "2026-10-19T00:00:00Z")


def test_snapshot_missing_git_is_a_code_error(conn, tmp_path, monkeypatch):
    from delivery_analysis.code.clone import CodeError

    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(graph.subprocess, "run", boom)
    with pytest.raises(CodeError):
        graph.snapshot(conn, "R1", tmp_path, "2026-10-19T00:00:00Z")
