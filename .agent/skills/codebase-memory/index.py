#!/usr/bin/env python3
"""
codebase-memory :: index.py
Builds a local, offline knowledge graph of a repository and renders it into
markdown memory files that an agent can read cheaply.

  python .agent/skills/codebase-memory/index.py build          # incremental
  python .agent/skills/codebase-memory/index.py build --full   # from scratch
  python .agent/skills/codebase-memory/index.py verify         # staleness check

Guarantees:
  * Python 3.8+ standard library only. No network. No telemetry. No installs.
  * Reads source files; writes ONLY inside .agent/memory/.
  * Honours .gitignore (via git) plus a hard deny-list plus .agentignore.
  * Never writes file bodies to disk -- only paths, names, signatures, counts.
  * Deterministic output (sorted) so re-runs produce clean diffs.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

SCHEMA = 3
DEFAULT_MAX_BYTES = 1_500_000
DEFAULT_MAX_LINE = 2_000          # a longer line means minified/generated
CALLS_AUTO_LIMIT = 25_000         # above this many files, call edges are opt-in
MAP_MODULE_LIMIT = 60
SHARD_SYMBOL_LIMIT = 400

# ---------------------------------------------------------------- discovery --

HARD_DENY_DIRS = {
    ".git", ".hg", ".svn", ".agent", "node_modules", "bower_components",
    "vendor", "venv", ".venv", "env", "virtualenv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".nox", ".gradle", ".idea", ".vs",
    ".vscode-test", "dist", "build", "out", "target", "bin", "obj", "coverage",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache", ".cache",
    "site-packages", "Pods", "DerivedData", ".terraform", ".serverless",
    "bundle", "public/build", "storybook-static", ".dart_tool",
}

# Paths that must never be opened, let alone summarised.
SECRET_PATH_GLOBS = [
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.der",
    "*.crt", "*.cer", "id_rsa*", "id_ed25519*", "*.ppk",
    ".env", ".env.*", "*.env", "*credentials*", "*secret*", "*secrets*",
    "*.tfstate", "*.tfstate.*", "*.kubeconfig", "kubeconfig*",
    "*.sqlite", "*.db", "*.pdb", "*.aof", "*.rdb",
]

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".ogg", ".webm", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".so", ".dll", ".dylib", ".exe", ".o", ".a", ".class", ".jar", ".war",
    ".wasm", ".bin", ".dat", ".pyc", ".pyo", ".node", ".onnx", ".pt", ".pkl",
    ".parquet", ".avro", ".xlsx", ".docx", ".pptx",
}

# Recorded as file nodes but never parsed for symbols.
OPAQUE_GLOBS = [
    "*.lock", "*-lock.json", "*.lockb", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "composer.lock",
    "Gemfile.lock", "go.sum", "*.min.js", "*.min.css", "*.map",
    "*.snap", "*.golden", "*.pb.go", "*_pb2.py", "*.g.dart", "*.freezed.dart",
    "*.generated.*", "*.designer.cs",
]

MANIFESTS = {
    "package.json", "go.mod", "Cargo.toml", "pyproject.toml", "setup.py",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
    "pubspec.yaml", "mix.exs", "Gemfile", "*.csproj", "*.fsproj", "CMakeLists.txt",
}

EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".mts": "typescript", ".cts": "typescript",
    ".vue": "vue", ".svelte": "svelte",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".cs": "csharp", ".fs": "fsharp", ".swift": "swift", ".m": "objc",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell",
    ".sql": "sql", ".lua": "lua", ".r": "r", ".jl": "julia", ".dart": "dart",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".clj": "clojure",
    ".hs": "haskell", ".ml": "ocaml", ".pl": "perl", ".pm": "perl",
    ".tf": "terraform", ".tfvars": "terraform", ".hcl": "terraform",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".xml": "xml", ".proto": "protobuf",
    ".graphql": "graphql", ".gql": "graphql", ".prisma": "prisma",
    ".md": "markdown", ".mdx": "markdown", ".rst": "rst",
    ".css": "css", ".scss": "scss", ".less": "less", ".html": "html",
}
NAME_LANG = {
    "Dockerfile": "dockerfile", "Containerfile": "dockerfile",
    "Makefile": "make", "GNUmakefile": "make", "Justfile": "just",
}

CODE_LANGS = {
    "python", "javascript", "typescript", "vue", "svelte", "go", "rust", "ruby",
    "php", "java", "kotlin", "scala", "csharp", "fsharp", "swift", "objc",
    "c", "cpp", "bash", "powershell", "sql", "lua", "dart", "elixir", "erlang",
    "clojure", "haskell", "ocaml", "perl", "r", "julia", "terraform", "protobuf",
    "graphql", "prisma",
}

KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function", "class",
    "new", "await", "typeof", "instanceof", "delete", "void", "do", "else",
    "try", "throw", "case", "with", "in", "of", "and", "or", "not", "print",
    "super", "self", "this", "constructor", "get", "set", "static", "public",
    "private", "protected", "async", "yield", "import", "export", "require",
    "assert", "raise", "pass", "def", "let", "const", "var", "match", "when",
    "foreach", "using", "lock", "select", "go", "defer", "range", "map", "len",
    "str", "int", "list", "dict", "type", "bool", "func", "end", "then", "elif",
}

SECRET_TEXT = re.compile(
    r"(?i)(?:api[_-]?key|secret|passw(?:or)?d|token|bearer\s|access[_-]?key"
    r"|private[_-]?key|-----BEGIN|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}"
    r"|sk-[A-Za-z0-9]{20,}|xox[baprs]-)"
)


def is_secret_path(rel):
    base = os.path.basename(rel)
    low = rel.replace("\\", "/").lower()
    for g in SECRET_PATH_GLOBS:
        if fnmatch.fnmatch(base.lower(), g) or fnmatch.fnmatch(low, "*/" + g):
            return True
    return False


def is_opaque(rel):
    base = os.path.basename(rel)
    return any(fnmatch.fnmatch(base, g) for g in OPAQUE_GLOBS)


def lang_of(rel):
    base = os.path.basename(rel)
    if base in NAME_LANG:
        return NAME_LANG[base]
    if base.startswith("Dockerfile"):
        return "dockerfile"
    ext = os.path.splitext(base)[1].lower()
    return EXT_LANG.get(ext)


def load_agentignore(root):
    pats = []
    p = os.path.join(root, ".agentignore")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line.rstrip("/"))
    return pats


def matches_any(rel, pats):
    rel = rel.replace("\\", "/")
    base = os.path.basename(rel)
    for p in pats:
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(base, p) \
           or rel.startswith(p + "/") or ("/" + p + "/") in ("/" + rel + "/"):
            return True
    return False


def git_files(root):
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "-co", "--exclude-standard"],
            capture_output=True, text=True, timeout=180, check=True,
        ).stdout
    except Exception:
        return None
    return [l for l in out.splitlines() if l]


def walk_files(root):
    acc = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in HARD_DENY_DIRS and not d.startswith(".")
            or d in (".github", ".gitlab")
        )
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            acc.append(os.path.relpath(full, root).replace("\\", "/"))
    return acc


def discover(root, extra_ignores):
    files = git_files(root)
    used_git = files is not None
    if not used_git:
        files = walk_files(root)
    keep = []
    for rel in files:
        rel = rel.replace("\\", "/")
        parts = rel.split("/")
        if any(p in HARD_DENY_DIRS for p in parts[:-1]):
            continue
        if extra_ignores and matches_any(rel, extra_ignores):
            continue
        if os.path.splitext(rel)[1].lower() in BINARY_EXT:
            continue
        if is_secret_path(rel):
            continue
        full = os.path.join(root, rel)
        if not os.path.isfile(full) or os.path.islink(full):
            continue
        keep.append(rel)
    return sorted(set(keep)), used_git


# ------------------------------------------------------------- extraction ---
# Best-effort, regex based. Deliberately conservative: it is better to miss a
# symbol than to invent one, because the agent is told to trust these records.

def _rx(*pairs):
    return [(re.compile(p, re.M), k) for p, k in pairs]


DEFS = {
    "python": _rx(
        (r"^[ \t]*class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)[ \t]*\(", "function"),
    ),
    "javascript": _rx(
        (r"^[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:abstract[ \t]+)?class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?function[ \t]*\*?[ \t]*(\w+)", "function"),
        (r"^[ \t]*(?:export[ \t]+)?(?:const|let|var)[ \t]+(\w+)[ \t]*=[ \t]*(?:async[ \t]*)?(?:\([^)]*\)|\w+)[ \t]*=>", "function"),
        (r"^[ \t]*(?:export[ \t]+)?(?:interface|type|enum)[ \t]+(\w+)", "type"),
        (r"^[ \t]{2,}(?:public |private |protected |static |readonly |async |\*)*(\w+)[ \t]*\([^)]*\)[ \t]*[{:]", "method"),
    ),
    "go": _rx(
        (r"^func[ \t]+\([^)]*\)[ \t]*(\w+)[ \t]*\(", "method"),
        (r"^func[ \t]+(\w+)[ \t]*[\(\[]", "function"),
        (r"^type[ \t]+(\w+)[ \t]+struct", "class"),
        (r"^type[ \t]+(\w+)[ \t]+interface", "interface"),
        (r"^type[ \t]+(\w+)[ \t]+\w", "type"),
    ),
    "rust": _rx(
        (r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?(?:async[ \t]+)?(?:unsafe[ \t]+)?fn[ \t]+(\w+)", "function"),
        (r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?struct[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?enum[ \t]+(\w+)", "type"),
        (r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?trait[ \t]+(\w+)", "interface"),
    ),
    "java": _rx(
        (r"^[ \t]*(?:public |private |protected |abstract |final |static )*class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:public |private |protected )*interface[ \t]+(\w+)", "interface"),
        (r"^[ \t]*(?:public |private |protected )*(?:record|enum)[ \t]+(\w+)", "type"),
        (r"^[ \t]+(?:public |private |protected |static |final |synchronized |abstract |native )+[\w<>\[\],\. ]+[ \t]+(\w+)[ \t]*\([^;]*\)[ \t]*\{", "method"),
    ),
    "csharp": _rx(
        (r"^[ \t]*(?:public |private |protected |internal |abstract |sealed |static |partial )*class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:public |private |protected |internal )*interface[ \t]+(\w+)", "interface"),
        (r"^[ \t]*(?:public |private |protected |internal )*(?:record|enum|struct)[ \t]+(\w+)", "type"),
        (r"^[ \t]+(?:public |private |protected |internal |static |async |override |virtual |sealed )+[\w<>\[\],\.\?]+[ \t]+(\w+)[ \t]*\([^;]*\)", "method"),
    ),
    "ruby": _rx(
        (r"^[ \t]*class[ \t]+([\w:]+)", "class"),
        (r"^[ \t]*module[ \t]+([\w:]+)", "module"),
        (r"^[ \t]*def[ \t]+(?:self\.)?([\w_?!]+)", "method"),
    ),
    "php": _rx(
        (r"^[ \t]*(?:abstract |final )?class[ \t]+(\w+)", "class"),
        (r"^[ \t]*interface[ \t]+(\w+)", "interface"),
        (r"^[ \t]*(?:public |private |protected |static |abstract |final )*function[ \t]+(\w+)", "function"),
    ),
    "kotlin": _rx(
        (r"^[ \t]*(?:public |private |internal |open |abstract |sealed |data )*class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:public |private |internal )*interface[ \t]+(\w+)", "interface"),
        (r"^[ \t]*(?:public |private |internal |open |override |suspend |inline )*fun[ \t]+(?:<[^>]*>[ \t]*)?(?:[\w\.]+\.)?(\w+)", "function"),
        (r"^[ \t]*object[ \t]+(\w+)", "class"),
    ),
    "swift": _rx(
        (r"^[ \t]*(?:public |private |internal |open |final )*(?:class|struct|enum|actor)[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:public |private |internal )*protocol[ \t]+(\w+)", "interface"),
        (r"^[ \t]*(?:public |private |internal |static |override |mutating )*func[ \t]+(\w+)", "function"),
    ),
    "scala": _rx(
        (r"^[ \t]*(?:case[ \t]+)?(?:class|object|trait)[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:override[ \t]+)?(?:private[ \t]+|protected[ \t]+)?def[ \t]+(\w+)", "function"),
    ),
    "c": _rx(
        (r"^[A-Za-z_][\w \t\*&]*?[ \t\*]+(\w+)[ \t]*\([^;{]*\)[ \t]*\{", "function"),
        (r"^typedef[ \t]+struct[^;{]*\{?[^;]*?\}?[ \t]*(\w+)[ \t]*;", "type"),
        (r"^struct[ \t]+(\w+)[ \t]*\{", "class"),
    ),
    "bash": _rx(
        (r"^[ \t]*(?:function[ \t]+)?([\w\-\.]+)[ \t]*\(\)[ \t]*\{", "function"),
    ),
    "sql": _rx(
        (r"(?i)^[ \t]*CREATE[ \t]+(?:OR[ \t]+REPLACE[ \t]+)?(?:TABLE|VIEW|MATERIALIZED[ \t]+VIEW)[ \t]+(?:IF[ \t]+NOT[ \t]+EXISTS[ \t]+)?([\w\.\"`]+)", "table"),
        (r"(?i)^[ \t]*CREATE[ \t]+(?:OR[ \t]+REPLACE[ \t]+)?(?:FUNCTION|PROCEDURE)[ \t]+([\w\.\"`]+)", "function"),
    ),
    "terraform": _rx(
        (r'^[ \t]*resource[ \t]+"([^"]+)"[ \t]+"([^"]+)"', "resource"),
        (r'^[ \t]*module[ \t]+"([^"]+)"', "module"),
    ),
    "protobuf": _rx(
        (r"^[ \t]*(?:message|enum)[ \t]+(\w+)", "type"),
        (r"^[ \t]*service[ \t]+(\w+)", "interface"),
        (r"^[ \t]*rpc[ \t]+(\w+)", "function"),
    ),
    "graphql": _rx(
        (r"^[ \t]*(?:type|input|enum|interface)[ \t]+(\w+)", "type"),
    ),
    "elixir": _rx(
        (r"^[ \t]*defmodule[ \t]+([\w\.]+)", "module"),
        (r"^[ \t]*def(?:p)?[ \t]+([\w_?!]+)", "function"),
    ),
    "dart": _rx(
        (r"^[ \t]*(?:abstract[ \t]+)?class[ \t]+(\w+)", "class"),
        (r"^[ \t]*(?:Future<[^>]*>|void|[A-Z]\w*|\w+)[ \t]+(\w+)[ \t]*\([^;]*\)[ \t]*(?:async[ \t]*)?\{", "function"),
    ),
    "lua": _rx((r"^[ \t]*(?:local[ \t]+)?function[ \t]+([\w\.:]+)", "function"),),
    "perl": _rx((r"^[ \t]*sub[ \t]+(\w+)", "function"),),
    "haskell": _rx((r"^(\w+)[ \t]*::", "function"),),
    "powershell": _rx((r"(?i)^[ \t]*function[ \t]+([\w\-]+)", "function"),),
    "r": _rx((r"^[ \t]*([\w\.]+)[ \t]*<-[ \t]*function", "function"),),
    "julia": _rx((r"^[ \t]*function[ \t]+([\w\.!]+)", "function"),),
    "clojure": _rx((r"^\([ \t]*def(?:n|record|protocol)?[ \t]+([\w\-\*\?!]+)", "function"),),
    "erlang": _rx((r"^([a-z]\w*)\(", "function"),),
    "ocaml": _rx((r"^[ \t]*let[ \t]+(?:rec[ \t]+)?(\w+)", "function"),),
    "objc": _rx(
        (r"^[+-][ \t]*\([^)]*\)[ \t]*(\w+)", "method"),
        (r"^@(?:interface|implementation)[ \t]+(\w+)", "class"),
    ),
    "prisma": _rx((r"^[ \t]*model[ \t]+(\w+)", "type"),),
    "fsharp": _rx((r"^[ \t]*(?:let|type)[ \t]+(?:rec[ \t]+)?(\w+)", "function"),),
}
DEFS["typescript"] = DEFS["javascript"]
DEFS["vue"] = DEFS["javascript"]
DEFS["svelte"] = DEFS["javascript"]
DEFS["cpp"] = DEFS["c"] + _rx(
    (r"^[ \t]*(?:class|struct)[ \t]+(\w+)[ \t]*[:{]", "class"),
    (r"^[ \t]*namespace[ \t]+(\w+)", "module"),
)

IMPORTS = {
    "python": [re.compile(r"^[ \t]*from[ \t]+([\w\.]+)[ \t]+import", re.M),
               re.compile(r"^[ \t]*import[ \t]+([\w\.]+)", re.M)],
    "javascript": [re.compile(r"""^[ \t]*import[^'"\n]*['"]([^'"]+)['"]""", re.M),
                   re.compile(r"""require\([ \t]*['"]([^'"]+)['"]""")],
    "go": [re.compile(r'^[ \t]*(?:[\w\.]+[ \t]+)?"([^"]+)"', re.M)],
    "java": [re.compile(r"^import[ \t]+(?:static[ \t]+)?([\w\.\*]+)[ \t]*;", re.M)],
    "rust": [re.compile(r"^[ \t]*(?:pub[ \t]+)?use[ \t]+([\w:]+)", re.M)],
    "ruby": [re.compile(r"""^[ \t]*require(?:_relative)?[ \t(]+['"]([^'"]+)['"]""", re.M)],
    "php": [re.compile(r"^[ \t]*use[ \t]+([\w\\\\]+)", re.M)],
    "csharp": [re.compile(r"^[ \t]*using[ \t]+([\w\.]+)[ \t]*;", re.M)],
    "elixir": [re.compile(r"^[ \t]*(?:import|alias|use)[ \t]+([\w\.]+)", re.M)],
    "terraform": [re.compile(r'^[ \t]*source[ \t]*=[ \t]*"([^"]+)"', re.M)],
}
IMPORTS["typescript"] = IMPORTS["javascript"]
IMPORTS["vue"] = IMPORTS["javascript"]
IMPORTS["svelte"] = IMPORTS["javascript"]
IMPORTS["kotlin"] = IMPORTS["java"]
IMPORTS["scala"] = IMPORTS["java"]

ROUTES = [
    re.compile(r"""(?i)@\w*\.?(get|post|put|patch|delete|route)[ \t]*\([ \t]*["'`]([^"'`]+)"""),
    re.compile(r"""(?i)\b(?:app|router|api|server|r|mux|e)\.(get|post|put|patch|delete|head|options)\([ \t]*["'`]([^"'`]+)"""),
    re.compile(r"""(?i)\b(?:HandleFunc|Handle)\([ \t]*["'`]([^"'`]+)"""),
    re.compile(r"""(?i)@(?:Get|Post|Put|Patch|Delete|Request)Mapping\([ \t]*(?:value[ \t]*=[ \t]*)?["']([^"']+)"""),
]

CALL_RX = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})[ \t]*\(")
TEST_HINT = re.compile(r"(?i)(^|/)(tests?|spec|__tests__|e2e)(/|$)|(^|[._-])(test|spec)([._-]|$)")


def read_text(full, max_bytes):
    try:
        if os.path.getsize(full) > max_bytes:
            return None, "too-large"
    except OSError:
        return None, "unreadable"
    try:
        with open(full, "rb") as fh:
            raw = fh.read(max_bytes + 1)
    except OSError:
        return None, "unreadable"
    if b"\x00" in raw[:4096]:
        return None, "binary"
    text = raw.decode("utf-8", errors="replace")
    for line in text.split("\n", 40)[:40]:
        if len(line) > DEFAULT_MAX_LINE:
            return None, "generated"
    return text, None


def extract(rel, text, lang):
    """Return (symbols, imports, routes) for one file."""
    syms, imps, routes = [], [], []
    for rx, kind in DEFS.get(lang, []):
        for m in rx.finditer(text):
            name = m.group(m.lastindex or 1)
            if not name:
                continue
            name = name.strip('"`')
            if name.lower() in KEYWORDS or len(name) < 2:
                continue
            if SECRET_TEXT.search(name):
                continue
            line = text.count("\n", 0, m.start()) + 1
            sig = m.group(0).strip()
            if len(sig) > 160 or SECRET_TEXT.search(sig):
                sig = name
            syms.append((name, kind, line, sig))
    seen = set()
    uniq = []
    for s in syms:
        k = (s[0], s[2])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    for rx in IMPORTS.get(lang, []):
        for m in rx.finditer(text):
            t = m.group(1)
            if t and len(t) < 200:
                imps.append(t)
    if lang in CODE_LANGS:
        for rx in ROUTES:
            for m in rx.finditer(text):
                g = m.groups()
                verb = g[0].upper() if len(g) > 1 else "ANY"
                path = g[-1]
                if path.startswith(("/", "http")) or "/" in path:
                    if not SECRET_TEXT.search(path) and len(path) < 200:
                        routes.append((verb, path))
    return uniq, sorted(set(imps))[:80], sorted(set(routes))[:80]


# ---------------------------------------------------------------- modules ---

def build_module_map(files, root):
    """A module is the nearest ancestor directory holding a package manifest,
    else the first one or two path segments."""
    manifest_dirs = set()
    for rel in files:
        base = os.path.basename(rel)
        d = os.path.dirname(rel)
        for pat in MANIFESTS:
            if fnmatch.fnmatch(base, pat):
                manifest_dirs.add(d)
                break
    manifest_dirs.discard("")

    def module_of(rel):
        d = os.path.dirname(rel)
        best = None
        while True:
            if d in manifest_dirs and (best is None or len(d) > len(best)):
                best = d
            if not d or "/" not in d:
                break
            d = d.rsplit("/", 1)[0]
        if best:
            return best
        parts = rel.split("/")
        if len(parts) == 1:
            return "(root)"
        if len(parts) == 2:
            return parts[0]
        return "/".join(parts[:2])

    return module_of


def slug(s):
    s = s.strip("/").replace("/", "__").replace(" ", "-")
    s = re.sub(r"[^A-Za-z0-9._\-]", "-", s).lstrip(".") or "root"
    return s[:80]


# ------------------------------------------------------------------- build --

def sha1_of(full):
    h = hashlib.sha1()
    try:
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(262144), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:12]


def build(args):
    root = os.path.abspath(args.root)
    mem = os.path.join(root, ".agent", "memory")
    graph_dir = os.path.join(mem, "graph")
    mod_dir = os.path.join(mem, "modules")
    for d in (graph_dir, mod_dir):
        os.makedirs(d, exist_ok=True)

    t0 = time.time()
    ignores = load_agentignore(root)
    files, used_git = discover(root, ignores)
    if args.max_files and len(files) > args.max_files:
        sys.stderr.write(
            "note: %d files found, capping at %d (raise with --max-files)\n"
            % (len(files), args.max_files))
        files = files[:args.max_files]

    module_of = build_module_map(files, root)

    file_recs, sym_recs, edges = [], [], []
    skipped = Counter()
    name_index = defaultdict(list)      # name -> [sym_id, ...] (capped)
    name_count = Counter()
    lang_loc = Counter()
    routes_all = []
    parsed_paths = []

    for rel in files:
        full = os.path.join(root, rel)
        lang = lang_of(rel)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        rec = {"p": rel, "lang": lang or "other", "bytes": size,
               "mod": module_of(rel), "sha": sha1_of(full)}
        if lang is None or is_opaque(rel) or lang not in CODE_LANGS:
            rec["parsed"] = False
            if lang is None:
                skipped["unknown-type"] += 1
            elif is_opaque(rel):
                skipped["generated-or-lockfile"] += 1
            else:
                skipped["non-code"] += 1
            file_recs.append(rec)
            continue
        text, why = read_text(full, args.max_bytes)
        if text is None:
            rec["parsed"] = False
            rec["skip"] = why
            skipped[why] += 1
            file_recs.append(rec)
            continue
        loc = text.count("\n") + 1
        rec["loc"] = loc
        rec["parsed"] = True
        rec["test"] = bool(TEST_HINT.search(rel))
        lang_loc[lang] += loc
        syms, imps, routes = extract(rel, text, lang)
        rec["syms"] = len(syms)
        file_recs.append(rec)
        parsed_paths.append(rel)
        for name, kind, line, sig in syms:
            sid = "%s#%s@%d" % (rel, name, line)
            sym_recs.append({"id": sid, "n": name, "k": kind, "p": rel,
                             "l": line, "sig": sig, "mod": rec["mod"]})
            edges.append((rel, sid, "DEFINES"))
            name_count[name] += 1
            if len(name_index[name]) < 4:
                name_index[name].append(sid)
        for t in imps:
            edges.append((rel, t, "IMPORTS"))
        for verb, path in routes:
            routes_all.append((verb, path, rel))
            edges.append((rel, "%s %s" % (verb, path), "EXPOSES"))

    # --- second pass: call edges (name-unique only, mirrors CALLS vs USAGE) --
    do_calls = args.calls == "on" or (args.calls == "auto" and len(parsed_paths) <= CALLS_AUTO_LIMIT)
    call_edges = 0
    ambiguous = 0
    if do_calls:
        # A definition line such as `def foo(` also matches the call pattern, so
        # a same-file name only counts as a call when it occurs more often than
        # it is defined in that file.
        defs_here = Counter((s["p"], s["n"]) for s in sym_recs)
        for rel in parsed_paths:
            full = os.path.join(root, rel)
            text, why = read_text(full, args.max_bytes)
            if text is None:
                continue
            hits = Counter(m.group(1) for m in CALL_RX.finditer(text))
            for name, cnt in hits.items():
                if name.lower() in KEYWORDS:
                    continue
                c = name_count.get(name, 0)
                if c == 0:
                    continue
                if c == 1:
                    target = name_index[name][0]
                    if target.rsplit("#", 1)[0] == rel and \
                       cnt <= defs_here.get((rel, name), 0):
                        continue
                    edges.append((rel, target, "CALLS"))
                    call_edges += 1
                else:
                    ambiguous += 1
    # --------------------------------------------------------------- write --
    # Content-addressed: identical trees produce identical generations, so an
    # agent can tell "rebuilt" from "actually changed".
    h = hashlib.sha1()
    for r in sorted(file_recs, key=lambda r: r["p"]):
        h.update(("%s:%s\n" % (r["p"], r["sha"])).encode("utf-8"))
    gen = h.hexdigest()[:10]
    built_at = int(time.time())
    write_jsonl(os.path.join(graph_dir, "files.jsonl"), sorted(file_recs, key=lambda r: r["p"]))
    write_jsonl(os.path.join(graph_dir, "symbols.jsonl"), sorted(sym_recs, key=lambda r: (r["p"], r["l"])))
    edge_recs = [{"s": s, "d": d, "t": t} for (s, d, t) in edges]
    edge_recs.sort(key=lambda r: (r["t"], r["s"], r["d"]))
    write_jsonl(os.path.join(graph_dir, "edges.jsonl"), edge_recs)

    stats = {
        "schema": SCHEMA,
        "generation": gen,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)),
        "built_at": built_at,
        "root_name": os.path.basename(root),
        "discovery": "git" if used_git else "walk",
        "files_total": len(file_recs),
        "files_parsed": len(parsed_paths),
        "symbols": len(sym_recs),
        "edges": len(edge_recs),
        "call_edges": call_edges,
        "ambiguous_calls": ambiguous,
        "calls_mode": "on" if do_calls else "off",
        "skipped": dict(skipped),
        "loc_by_lang": dict(lang_loc.most_common()),
        "elapsed_s": round(time.time() - t0, 2),
        "indexer_sha": sha1_of(os.path.abspath(__file__)),
    }
    with open(os.path.join(graph_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, sort_keys=True)
        fh.write("\n")

    append_drift_snapshot(root, stats, file_recs)
    render(mem, mod_dir, stats, file_recs, sym_recs, edge_recs, routes_all, module_of)
    sys.stderr.write(
        "codebase-memory: %d files, %d parsed, %d symbols, %d edges in %.1fs -> .agent/memory/\n"
        % (stats["files_total"], stats["files_parsed"], stats["symbols"],
           stats["edges"], stats["elapsed_s"]))
    return 0


DRIFT_LOG_PATH = os.path.join("history", "drift-log.jsonl")
DRIFT_LOG_MAX_ENTRIES = 500  # ~one per build; capped so it never grows unbounded


def append_drift_snapshot(root, stats, file_recs):
    """One compact line per build under .agent/memory/history/drift-log.jsonl
    -- derived counts only (module -> LOC, LOC by language, totals), never
    file bodies, same write discipline as the rest of this indexer. This is
    what `query.py drift` reads to show how the codebase's shape has changed
    build over build. Skips a duplicate entry if this generation was already
    the most recent one logged (a `verify`-triggered no-op rebuild)."""
    path = os.path.join(root, ".agent", "memory", DRIFT_LOG_PATH)
    entries = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if entries and entries[-1].get("generation") == stats["generation"]:
        return

    mod_loc = Counter()
    for r in file_recs:
        mod_loc[r.get("mod", "")] += r.get("loc", 0)

    entries.append({
        "generation": stats["generation"],
        "ts": stats["generated_at"],
        "files_total": stats["files_total"],
        "files_parsed": stats["files_parsed"],
        "symbols": stats["symbols"],
        "edges": stats["edges"],
        "loc_total": sum(stats["loc_by_lang"].values()),
        "loc_by_lang": stats["loc_by_lang"],
        "modules": dict(mod_loc),
    })
    entries = entries[-DRIFT_LOG_MAX_ENTRIES:]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    os.replace(tmp, path)


def write_jsonl(path, recs):
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")))
            fh.write("\n")


# -------------------------------------------------------------- rendering ---

def render(mem, mod_dir, stats, file_recs, sym_recs, edge_recs, routes_all, module_of):
    by_mod = defaultdict(lambda: {"files": [], "syms": [], "loc": 0, "langs": Counter()})
    for r in file_recs:
        m = by_mod[r["mod"]]
        m["files"].append(r)
        m["loc"] += r.get("loc", 0)
        if r.get("parsed"):
            m["langs"][r["lang"]] += 1
    for s in sym_recs:
        by_mod[s["mod"]]["syms"].append(s)

    indeg = Counter()
    for e in edge_recs:
        if e["t"] == "CALLS":
            indeg[e["d"]] += 1
    import_targets = Counter(e["d"] for e in edge_recs if e["t"] == "IMPORTS")

    entry = [r["p"] for r in file_recs if re.search(
        r"(?i)(^|/)(main|index|app|server|cli|__main__|program|startup)\.[a-z]+$", r["p"])]
    entry += [r["p"] for r in file_recs if os.path.basename(r["p"]) in
              ("Dockerfile", "docker-compose.yml", "Makefile", "justfile", "Justfile")]
    entry = sorted(set(entry))[:40]

    mods_sorted = sorted(by_mod.items(), key=lambda kv: -kv[1]["loc"])

    # ---- root map -----------------------------------------------------------
    L = []
    A = L.append
    A("# CODEBASE MAP — %s" % stats["root_name"])
    A("")
    A("> GENERATED FILE. Do not edit by hand; rerun the codebase-memory skill.")
    A("> generation `%s` · %s · %d files (%d parsed) · %d symbols · %d edges"
      % (stats["generation"], stats["generated_at"], stats["files_total"],
         stats["files_parsed"], stats["symbols"], stats["edges"]))
    A("")
    A("## How to use this file")
    A("")
    A("1. Read this map first. It is the cheapest view of the repo.")
    A("2. Narrow to a module, then open `.agent/memory/modules/<slug>.md`.")
    A("3. For a symbol, run `query.py def|who-calls|calls-of <name>` instead of grepping.")
    A("4. Only then open source files, and only the line ranges you need.")
    A("")
    A("Absence of a symbol here is **not** proof it does not exist — see Coverage.")
    A("")
    A("## Stack")
    A("")
    tot = sum(stats["loc_by_lang"].values()) or 1
    for lang, loc in list(stats["loc_by_lang"].items())[:14]:
        A("- `%s` — %s LOC (%.0f%%)" % (lang, f"{loc:,}", 100.0 * loc / tot))
    A("")
    if entry:
        A("## Likely entry points")
        A("")
        for p in entry:
            A("- `%s`" % p)
        A("")
    if routes_all:
        A("## HTTP surface (%d detected)" % len(routes_all))
        A("")
        for verb, path, rel in sorted(set(routes_all))[:60]:
            A("- `%s %s` → `%s`" % (verb, path, rel))
        if len(set(routes_all)) > 60:
            A("- …%d more, see module shards" % (len(set(routes_all)) - 60))
        A("")
    A("## Modules (%d) — largest first" % len(by_mod))
    A("")
    A("| module | files | LOC | symbols | shard |")
    A("|---|---:|---:|---:|---|")
    for name, m in mods_sorted[:MAP_MODULE_LIMIT]:
        A("| `%s` | %d | %s | %d | [`%s.md`](modules/%s.md) |"
          % (name, len(m["files"]), f'{m["loc"]:,}', len(m["syms"]),
             slug(name), slug(name)))
    if len(mods_sorted) > MAP_MODULE_LIMIT:
        A("")
        A("_%d smaller modules omitted; every module still has a shard in `modules/`._"
          % (len(mods_sorted) - MAP_MODULE_LIMIT))
    A("")
    hubs = [(indeg[s["id"]], s) for s in sym_recs if indeg.get(s["id"])]
    hubs.sort(key=lambda t: -t[0])
    if hubs:
        A("## Hubs — most-called symbols (change these carefully)")
        A("")
        for n, s in hubs[:25]:
            A("- `%s` (%s) ← %d callers · `%s:%d`" % (s["n"], s["k"], n, s["p"], s["l"]))
        A("")
    ext = [(c, t) for t, c in import_targets.items()
           if not t.startswith((".", "/")) and c > 2]
    ext.sort(reverse=True)
    if ext:
        A("## Most-imported dependencies")
        A("")
        A(", ".join("`%s` (%d)" % (t, c) for c, t in ext[:40]))
        A("")
    A("## Coverage and limits")
    A("")
    A("- Discovery: `%s`. Parsed %d of %d files."
      % (stats["discovery"], stats["files_parsed"], stats["files_total"]))
    if stats["skipped"]:
        A("- Skipped: " + ", ".join("%s=%d" % (k, v) for k, v in sorted(stats["skipped"].items())))
    A("- Call edges: `%s`. %d resolved, %d call sites left unresolved because the "
      "name was ambiguous across files." % (stats["calls_mode"], stats["call_edges"],
                                            stats["ambiguous_calls"]))
    A("- Symbols come from language-aware pattern matching, not a full compiler "
      "front end. Dynamic dispatch, macros, reflection, code generation and "
      "string-built calls are invisible to it.")
    A("- **A clean result means \"no recorded gap\", never \"proven complete\".** "
      "Before any claim that something does not exist, confirm with a direct "
      "search over the relevant paths and say which paths you covered.")
    A("")
    with open(os.path.join(mem, "CODEBASE_MAP.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    # ---- shards -------------------------------------------------------------
    for name, m in by_mod.items():
        S = []
        B = S.append
        B("# module: `%s`" % name)
        B("")
        B("> GENERATED · generation `%s` · %d files · %s LOC · %d symbols"
          % (stats["generation"], len(m["files"]), f'{m["loc"]:,}', len(m["syms"])))
        B("")
        if m["langs"]:
            B("Languages: " + ", ".join("`%s`×%d" % (k, v) for k, v in m["langs"].most_common()))
            B("")
        mroutes = [r for r in routes_all if module_of(r[2]) == name]
        if mroutes:
            B("## Routes")
            B("")
            for verb, path, rel in sorted(set(mroutes))[:80]:
                B("- `%s %s` → `%s`" % (verb, path, rel))
            B("")
        B("## Files")
        B("")
        for r in sorted(m["files"], key=lambda r: r["p"])[:400]:
            tag = "" if r.get("parsed") else "  _(not parsed: %s)_" % r.get("skip", r["lang"])
            B("- `%s` — %s, %s LOC, %d symbols%s"
              % (r["p"], r["lang"], f'{r.get("loc",0):,}', r.get("syms", 0), tag))
        if len(m["files"]) > 400:
            B("- …%d more files" % (len(m["files"]) - 400))
        B("")
        B("## Symbols")
        B("")
        syms = sorted(m["syms"], key=lambda s: (-indeg.get(s["id"], 0), s["p"], s["l"]))
        for s in syms[:SHARD_SYMBOL_LIMIT]:
            cal = " ←%d" % indeg[s["id"]] if indeg.get(s["id"]) else ""
            B("- `%s` %s `%s:%d`%s" % (s["n"], s["k"], s["p"], s["l"], cal))
        if len(syms) > SHARD_SYMBOL_LIMIT:
            B("- …%d more symbols — use `query.py search --module %s <pattern>`"
              % (len(syms) - SHARD_SYMBOL_LIMIT, name))
        B("")
        with open(os.path.join(mod_dir, slug(name) + ".md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(S))

    # prune shards from earlier generations
    live = {slug(n) + ".md" for n in by_mod}
    for fn in os.listdir(mod_dir):
        if fn.endswith(".md") and fn not in live:
            os.remove(os.path.join(mod_dir, fn))


# --------------------------------------------------------------- verify -----

def verify(args):
    root = os.path.abspath(args.root)
    mpath = os.path.join(root, ".agent", "memory", "graph", "manifest.json")
    if not os.path.exists(mpath):
        print("STALE: no index. Run: python .agent/skills/codebase-memory/index.py build")
        return 2
    man = json.load(open(mpath, encoding="utf-8"))
    if man.get("schema") != SCHEMA:
        print("STALE: schema %s, indexer expects %s. Rebuild with --full."
              % (man.get("schema"), SCHEMA))
        return 2
    drift = 0
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        if head.returncode == 0:
            since = subprocess.run(
                ["git", "-C", root, "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=60)
            drift = len([l for l in since.stdout.splitlines() if l])
    except Exception:
        pass
    age_h = (time.time() - man.get("built_at", 0)) / 3600.0
    print("generation %s (%s) · %.1fh old · %d files · %d symbols · %d uncommitted changes"
          % (man["generation"], man["generated_at"], age_h,
             man["files_total"], man["symbols"], drift))
    if age_h > 24 * 14 or drift > 40:
        print("STALE: rebuild recommended.")
        return 2
    print("OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Local codebase memory indexer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", default=".")
    b.add_argument("--full", action="store_true", help="ignored; build is always full")
    b.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    b.add_argument("--max-files", type=int, default=200_000)
    b.add_argument("--calls", choices=["auto", "on", "off"], default="auto")
    b.set_defaults(fn=build)
    v = sub.add_parser("verify")
    v.add_argument("--root", default=".")
    v.set_defaults(fn=verify)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
