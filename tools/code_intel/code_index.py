import os
import re
import threading
from collections import Counter
from pathlib import Path

from tools.code_intel.cache import IndexCache, _hash_file
from tools.code_intel.parsers import detect_language, get_snippet, parse_file
from tools.code_intel.symbol_table import Reference, SymbolTable

# Directories to skip during indexing
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".env",
             ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs"}

# Max file size to parse (skip generated / vendored files)
MAX_FILE_SIZE = 512 * 1024  # 512 KB


class CodeIndex:
    def __init__(self, root: Path, storage_manager=None):
        self.root = root
        self.table = SymbolTable()
        self.references: list[Reference] = []
        self._file_hashes: dict[str, str] = {}
        self._cache = IndexCache(root)
        self._storage = storage_manager

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def build(self):
        """Build the index, using disk cache when possible."""
        current_files = [self._rel(f) for f in self._walk_files()]

        # Try loading from cache
        cached = self._cache.load()
        if cached is not None:
            self.table, self.references, self._file_hashes = cached
            changed, deleted = self._cache.get_stale_files(
                self.root, self._file_hashes, current_files
            )

            if not changed and not deleted:
                return  # cache is fully current

            # Remove stale entries
            for rel in deleted:
                self.table.remove_file(rel)
                self.references = [r for r in self.references if r.file != rel]
                self._file_hashes.pop(rel, None)

            # Re-parse only changed files
            for rel in changed:
                self.table.remove_file(rel)
                self.references = [r for r in self.references if r.file != rel]
                self._index_file(str(self.root / rel))

            self._save_cache()
            return

        # No cache — full build
        self.table = SymbolTable()
        self.references = []
        self._file_hashes = {}

        for file_path in self._walk_files():
            self._index_file(file_path)

        self._save_cache()

    def update_file(self, file_path: str):
        """Re-index a single file (after edit/write/delete)."""
        rel = self._rel(file_path)
        self.table.remove_file(rel)
        self.references = [r for r in self.references if r.file != rel]
        self._file_hashes.pop(rel, None)

        abs_path = self.root / rel
        if abs_path.exists():
            self._index_file(str(abs_path))

        self._save_cache()

    def _save_cache(self):
        """Save to disk only if storage budget allows."""
        if self._storage and not self._storage.is_write_allowed():
            return
        self._cache.save(self.table, self.references, self._file_hashes)

    def _index_file(self, abs_path: str):
        rel = self._rel(abs_path)
        if detect_language(rel) is None:
            return

        try:
            size = os.path.getsize(abs_path)
            if size > MAX_FILE_SIZE:
                return
            source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        symbols, refs = parse_file(rel, source)
        for sym in symbols:
            self.table.add(sym)
        self.references.extend(refs)
        self._file_hashes[rel] = _hash_file(abs_path)

    def _walk_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                if detect_language(fname) is not None:
                    yield full

    def _rel(self, path: str) -> str:
        try:
            return str(Path(path).relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def find_definition(self, symbol: str, language: str | None = None,
                        kind: str | None = None) -> list[dict]:
        matches = self.table.lookup(symbol)
        if kind:
            matches = [s for s in matches if s.kind == kind]
        if language:
            matches = [s for s in matches if detect_language(s.file) == language]

        results = []
        for sym in matches:
            try:
                snippet = get_snippet(
                    str(self.root / sym.file), sym.line, sym.end_line
                )
            except OSError:
                snippet = ""

            results.append({
                "symbol": sym.name,
                "qualified_name": sym.qualified_name,
                "kind": sym.kind,
                "file": sym.file,
                "line": sym.line,
                "end_line": sym.end_line,
                "params": sym.params or None,
                "return_type": sym.return_type,
                "docstring": sym.docstring,
                "parent": sym.parent,
                "snippet": snippet,
            })
        return results

    def find_usages(self, symbol: str, kind: str | None = None) -> list[dict]:
        """Find all references to a symbol across the codebase."""
        usages = []
        token_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")

        # 1. Search import references
        for ref in self.references:
            if token_re.search(ref.context):
                usages.append({
                    "file": ref.file,
                    "line": ref.line,
                    "kind": ref.kind,
                    "context": ref.context,
                })

        # 2. Scan files for call-site / attribute references
        for file_path in self._walk_files():
            rel = self._rel(file_path)
            try:
                source = Path(file_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for line_num, line in enumerate(source.splitlines(), start=1):
                # Skip lines already captured as imports
                if any(u["file"] == rel and u["line"] == line_num for u in usages):
                    continue
                if token_re.search(line):
                    # Determine usage kind from context
                    stripped = line.strip()
                    if not stripped or stripped.startswith(("#", "//", "/*", "*")):
                        continue
                    if f"import {symbol}" in stripped or f"from " in stripped:
                        continue  # already captured
                    elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}\s*\(", stripped):
                        use_kind = "call"
                    elif f".{symbol}" in stripped:
                        use_kind = "attribute"
                    elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}\s*[:=]", stripped):
                        use_kind = "assignment"
                    else:
                        use_kind = "reference"

                    if kind and use_kind != kind:
                        continue

                    usages.append({
                        "file": rel,
                        "line": line_num,
                        "kind": use_kind,
                        "context": stripped,
                    })

        return usages

    def read_symbol(self, symbol: str | None = None, qualified_name: str | None = None,
                    kind: str | None = None, max_lines: int = 400,
                    include_line_numbers: bool = True) -> dict:
        """Return the full source body for matching symbol definitions."""
        if qualified_name:
            match = self.table.lookup_qualified(qualified_name)
            matches = [match] if match else []
        elif symbol:
            matches = self.table.lookup(symbol)
        else:
            raise ValueError("symbol or qualified_name is required")

        if kind:
            matches = [s for s in matches if s.kind == kind]
        if not matches:
            return {
                "symbol": symbol,
                "qualified_name": qualified_name,
                "found": False,
                "results": [],
            }

        results = []
        for sym in matches[:10]:
            try:
                source = Path(self.root / sym.file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                source = ""
            lines = source.splitlines()
            start = max(1, sym.line)
            end = min(len(lines), sym.end_line)
            body_lines = lines[start - 1:end]
            truncated = len(body_lines) > max_lines
            body_lines = body_lines[:max_lines]
            if include_line_numbers:
                width = len(str(start + len(body_lines)))
                body = "\n".join(
                    f"{line_no:>{width}}: {line}"
                    for line_no, line in enumerate(body_lines, start=start)
                )
            else:
                body = "\n".join(body_lines)
            results.append({
                "symbol": sym.name,
                "qualified_name": sym.qualified_name,
                "kind": sym.kind,
                "file": sym.file,
                "line": sym.line,
                "end_line": sym.end_line,
                "params": sym.params or None,
                "return_type": sym.return_type,
                "docstring": sym.docstring,
                "parent": sym.parent,
                "content": body,
                "truncated": truncated,
            })

        return {
            "symbol": symbol,
            "qualified_name": qualified_name,
            "found": True,
            "count": len(matches),
            "results": results,
            "truncated": len(matches) > 10,
        }

    def find_usages_context(self, symbol: str, kind: str | None = None,
                            context_lines: int = 2, max_results: int = 25) -> dict:
        """Find usages and include nearby source context."""
        usages = self.find_usages(symbol, kind=kind)
        results = []
        for usage in usages[:max_results]:
            try:
                source = Path(self.root / usage["file"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                source = ""
            lines = source.splitlines()
            line_no = int(usage["line"])
            start = max(1, line_no - context_lines)
            end = min(len(lines), line_no + context_lines)
            width = len(str(end))
            context = "\n".join(
                f"{idx:>{width}}: {lines[idx - 1]}"
                for idx in range(start, end + 1)
            )
            results.append({
                **usage,
                "context_start_line": start,
                "context_end_line": end,
                "source_context": context,
            })
        return {
            "symbol": symbol,
            "total": len(usages),
            "count": len(results),
            "truncated": len(usages) > len(results),
            "usages": results,
        }

    def code_index_summary(self) -> dict:
        """Return high-level stats for the current code index."""
        symbols = self.table.all_symbols()
        return {
            "root": str(self.root),
            "symbols": len(symbols),
            "references": len(self.references),
            "indexed_files": len(self._file_hashes),
            "languages": dict(Counter(detect_language(path) for path in self._file_hashes).most_common()),
            "symbol_kinds": dict(Counter(sym.kind for sym in symbols).most_common()),
            "largest_symbol_files": [
                {"file": file, "symbols": count}
                for file, count in Counter(sym.file for sym in symbols).most_common(20)
            ],
        }

    def get_file_structure(self, file_path: str) -> dict:
        """Return a table-of-contents for a file."""
        rel = self._rel(file_path)
        symbols = self.table.get_file_symbols(rel)

        # Also get imports for this file
        file_imports = [r.context for r in self.references
                        if r.file == rel and r.kind == "import"]

        language = detect_language(rel)

        # Build hierarchical structure: classes with their methods
        top_level = []
        children_map: dict[str, list] = {}

        for sym in sorted(symbols, key=lambda s: s.line):
            entry = {
                "name": sym.name,
                "kind": sym.kind,
                "line": sym.line,
            }
            if sym.params:
                entry["params"] = sym.params
            if sym.return_type:
                entry["returns"] = sym.return_type

            if sym.parent:
                children_map.setdefault(sym.parent, []).append(entry)
            else:
                top_level.append(entry)

        # Attach children to their parent classes
        for item in top_level:
            qn = f"{rel.replace('/', '.').removesuffix('.py').removesuffix('.js').removesuffix('.ts').removesuffix('.tsx')}.{item['name']}"
            kids = children_map.get(qn, [])
            if kids:
                item["children"] = kids

        return {
            "file": rel,
            "language": language,
            "imports": file_imports,
            "symbols": top_level,
        }

    def search_symbols(self, query: str, kind: str | None = None,
                       limit: int = 20) -> list[dict]:
        results = self.table.search(query, kind=kind, limit=limit)
        return [
            {
                "name": sym.name,
                "qualified_name": sym.qualified_name,
                "kind": sym.kind,
                "file": sym.file,
                "line": sym.line,
                "score": score,
            }
            for sym, score in results
        ]

    def find_imports(self, module: str | None = None,
                     symbol: str | None = None) -> list[dict]:
        """Find who imports a given module or symbol."""
        results = []
        query = module or symbol or ""
        query_lower = query.lower()

        for ref in self.references:
            if ref.kind != "import":
                continue
            if query_lower in ref.context.lower():
                results.append({
                    "file": ref.file,
                    "line": ref.line,
                    "statement": ref.context,
                })

        return results

    def get_call_graph(self, function: str, depth: int = 1) -> dict:
        """Get what a function calls and what calls it."""
        # Find the function definition
        matches = self.table.lookup(function)
        func_matches = [s for s in matches if s.kind in ("function", "method")]
        if not func_matches:
            return {"function": function, "found": False}

        sym = func_matches[0]

        # Read the function body to find what it calls
        calls = []
        try:
            source = Path(self.root / sym.file).read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            body = lines[sym.line - 1:sym.end_line]

            # Find all function/method calls in the body
            all_symbol_names = {s.name for s in self.table.all_symbols()
                                if s.kind in ("function", "method") and s.name != function}

            for line_num, line in enumerate(body, start=sym.line):
                for name in all_symbol_names:
                    if f"{name}(" in line:
                        calls.append(name)
        except OSError:
            pass

        calls = sorted(set(calls))

        # Find what calls this function (scan all files)
        called_by = []
        for file_path in self._walk_files():
            rel = self._rel(file_path)
            if rel == sym.file:
                # Same file — skip lines within the function itself
                try:
                    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line_num, line in enumerate(source.splitlines(), start=1):
                    if line_num < sym.line or line_num > sym.end_line:
                        if f"{function}(" in line:
                            called_by.append(f"{rel}:{line_num}")
            else:
                try:
                    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line_num, line in enumerate(source.splitlines(), start=1):
                    if f"{function}(" in line:
                        called_by.append(f"{rel}:{line_num}")

        return {
            "function": function,
            "found": True,
            "file": sym.file,
            "line": sym.line,
            "calls": calls,
            "called_by": called_by,
        }

    # ------------------------------------------------------------------
    # Tool exports
    # ------------------------------------------------------------------

    def get_tools(self) -> list[dict]:
        return [
            get_find_definition_tool(self),
            get_find_usages_tool(self),
            get_find_usages_context_tool(self),
            get_file_structure_tool(self),
            get_read_symbol_tool(self),
            get_search_symbols_tool(self),
            get_find_imports_tool(self),
            get_call_graph_tool(self),
            get_code_index_summary_tool(self),
        ]


class LazyCodeIndex:
    """Build CodeIndex only when a code-intel tool actually needs it."""

    def __init__(self, root: Path, storage_manager=None, *, background: bool = False):
        self.root = root
        self._storage = storage_manager
        self._index: CodeIndex | None = None
        self._build_error: str | None = None
        self._building = False
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        if background:
            self.start_background_build()

    def start_background_build(self) -> None:
        with self._lock:
            if self._index is not None or self._building:
                return
            self._building = True
        thread = threading.Thread(target=self._build_in_background, daemon=True)
        thread.start()

    def _build_in_background(self) -> None:
        self._build_index()

    def _ensure_built(self) -> CodeIndex:
        with self._lock:
            if self._index is not None:
                return self._index
            while self._building:
                self._condition.wait()
                if self._index is not None:
                    return self._index
            if self._build_error:
                raise RuntimeError(self._build_error)
            self._building = True
            self._build_error = None

        return self._build_index()

    def _build_index(self) -> CodeIndex:
        try:
            index = CodeIndex(root=self.root, storage_manager=self._storage)
            index.build()
        except Exception as exc:
            with self._lock:
                self._build_error = str(exc)
                self._building = False
                self._condition.notify_all()
            raise

        with self._lock:
            self._index = index
            self._building = False
            self._condition.notify_all()
            return index

    def status(self) -> dict:
        with self._lock:
            if self._index is not None:
                return {
                    "state": "ready",
                    "symbols": len(self._index.table.all_symbols()),
                    "references": len(self._index.references),
                    "error": None,
                }
            if self._building:
                return {
                    "state": "building",
                    "symbols": None,
                    "references": None,
                    "error": None,
                }
            if self._build_error:
                return {
                    "state": "error",
                    "symbols": None,
                    "references": None,
                    "error": self._build_error,
                }
            return {
                "state": "lazy",
                "symbols": None,
                "references": None,
                "error": None,
            }

    def get_tools(self) -> list[dict]:
        return [
            get_find_definition_tool(self),
            get_find_usages_tool(self),
            get_find_usages_context_tool(self),
            get_file_structure_tool(self),
            get_read_symbol_tool(self),
            get_search_symbols_tool(self),
            get_find_imports_tool(self),
            get_call_graph_tool(self),
            get_code_index_summary_tool(self),
        ]

    def update_file(self, file_path: str):
        with self._lock:
            index = self._index
        if index is None:
            return None
        return index.update_file(file_path)

    def find_definition(self, *args, **kwargs):
        return self._ensure_built().find_definition(*args, **kwargs)

    def find_usages(self, *args, **kwargs):
        return self._ensure_built().find_usages(*args, **kwargs)

    def find_usages_context(self, *args, **kwargs):
        return self._ensure_built().find_usages_context(*args, **kwargs)

    def get_file_structure(self, *args, **kwargs):
        return self._ensure_built().get_file_structure(*args, **kwargs)

    def read_symbol(self, *args, **kwargs):
        return self._ensure_built().read_symbol(*args, **kwargs)

    def search_symbols(self, *args, **kwargs):
        return self._ensure_built().search_symbols(*args, **kwargs)

    def find_imports(self, *args, **kwargs):
        return self._ensure_built().find_imports(*args, **kwargs)

    def get_call_graph(self, *args, **kwargs):
        return self._ensure_built().get_call_graph(*args, **kwargs)

    def code_index_summary(self, *args, **kwargs):
        return self._ensure_built().code_index_summary(*args, **kwargs)


# ======================================================================
# Tool factory functions (match LumaKit's get_*_tool() pattern)
# ======================================================================

def get_find_definition_tool(index: CodeIndex):
    def _execute(inputs):
        results = index.find_definition(
            symbol=inputs["symbol"],
            language=inputs.get("language"),
            kind=inputs.get("kind"),
        )
        if not results:
            return {"symbol": inputs["symbol"], "found": False, "results": []}
        return {"symbol": inputs["symbol"], "found": True, "count": len(results), "results": results}

    return {
        "name": "find_definition",
        "description": (
            "Find where a symbol (function, class, method, variable) is defined in the codebase. "
            "Returns the file, line number, parameters, docstring, and a code snippet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Name of the symbol to find"},
                "language": {"type": "string", "description": "Filter by language (python, javascript, typescript)"},
                "kind": {"type": "string", "description": "Filter by kind (function, class, method, variable)"},
            },
            "required": ["symbol"],
        },
        "execute": _execute,
    }


def get_find_usages_tool(index: CodeIndex):
    def _execute(inputs):
        usages = index.find_usages(
            symbol=inputs["symbol"],
            kind=inputs.get("kind"),
        )
        return {
            "symbol": inputs["symbol"],
            "total": len(usages),
            "usages": usages[:50],  # cap output size
            "truncated": len(usages) > 50,
        }

    return {
        "name": "find_usages",
        "description": (
            "Find all places where a symbol is used across the codebase. "
            "Returns file, line, usage kind (call, import, assignment, attribute, reference), and context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Name of the symbol to search for"},
                "kind": {"type": "string", "description": "Filter by usage kind (call, import, assignment, attribute)"},
            },
            "required": ["symbol"],
        },
        "execute": _execute,
    }


def get_find_usages_context_tool(index: CodeIndex):
    def _execute(inputs):
        return index.find_usages_context(
            symbol=inputs["symbol"],
            kind=inputs.get("kind"),
            context_lines=int(inputs.get("context_lines", 2)),
            max_results=int(inputs.get("max_results", 25)),
        )

    return {
        "name": "find_usages_context",
        "description": (
            "Find symbol usages and include nearby source lines for each result. "
            "Use this when raw usage lines are not enough to make a safe change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Name of the symbol to search for"},
                "kind": {"type": "string", "description": "Filter by usage kind (call, import, assignment, attribute)"},
                "context_lines": {"type": "integer", "description": "Lines before/after each match (default 2)"},
                "max_results": {"type": "integer", "description": "Max usage contexts to return (default 25)"},
            },
            "required": ["symbol"],
        },
        "execute": _execute,
    }


def get_file_structure_tool(index: CodeIndex):
    def _execute(inputs):
        return index.get_file_structure(inputs["path"])

    return {
        "name": "get_file_structure",
        "description": (
            "Get the structure of a source file: its imports, classes, functions, methods, "
            "and variables with line numbers. Like a table of contents — avoids reading the whole file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to project root)"},
            },
            "required": ["path"],
        },
        "execute": _execute,
    }


def get_read_symbol_tool(index: CodeIndex):
    def _execute(inputs):
        return index.read_symbol(
            symbol=inputs.get("symbol"),
            qualified_name=inputs.get("qualified_name"),
            kind=inputs.get("kind"),
            max_lines=int(inputs.get("max_lines", 400)),
            include_line_numbers=bool(inputs.get("include_line_numbers", True)),
        )

    return {
        "name": "read_symbol",
        "description": (
            "Read the full source body for a function, class, method, or variable definition. "
            "Use this after search_symbols/find_definition when you need implementation details."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Short symbol name to read"},
                "qualified_name": {"type": "string", "description": "Exact qualified symbol name, if known"},
                "kind": {"type": "string", "description": "Filter by kind (function, class, method, variable)"},
                "max_lines": {"type": "integer", "description": "Maximum lines per symbol (default 400)"},
                "include_line_numbers": {"type": "boolean", "description": "Prefix lines with numbers (default true)"},
            },
        },
        "execute": _execute,
    }


def get_search_symbols_tool(index: CodeIndex):
    def _execute(inputs):
        results = index.search_symbols(
            query=inputs["query"],
            kind=inputs.get("kind"),
            limit=int(inputs.get("limit", 20)),
        )
        return {"query": inputs["query"], "count": len(results), "results": results}

    return {
        "name": "search_symbols",
        "description": (
            "Fuzzy search for symbols (functions, classes, methods, variables) by name. "
            "Returns matches ranked by relevance with file and line info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (partial name match)"},
                "kind": {"type": "string", "description": "Filter by kind (function, class, method, variable)"},
                "limit": {"type": "integer", "description": "Max results to return (default 20)"},
            },
            "required": ["query"],
        },
        "execute": _execute,
    }


def get_find_imports_tool(index: CodeIndex):
    def _execute(inputs):
        results = index.find_imports(
            module=inputs.get("module"),
            symbol=inputs.get("symbol"),
        )
        query = inputs.get("module") or inputs.get("symbol", "")
        return {"query": query, "total": len(results), "imported_by": results}

    return {
        "name": "find_imports",
        "description": (
            "Find all files that import a given module or symbol. "
            "Answers 'who depends on this?' — useful for understanding blast radius of changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {"type": "string", "description": "Module name to search for (e.g. 'core.session')"},
                "symbol": {"type": "string", "description": "Symbol name to search for in import statements"},
            },
        },
        "execute": _execute,
    }


def get_code_index_summary_tool(index: CodeIndex):
    def _execute(inputs):
        return index.code_index_summary()

    return {
        "name": "code_index_summary",
        "description": (
            "Return high-level code-index stats: indexed files, languages, symbol kinds, "
            "and files with the most symbols."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "execute": _execute,
    }


def get_call_graph_tool(index: CodeIndex):
    def _execute(inputs):
        return index.get_call_graph(
            function=inputs["function"],
            depth=int(inputs.get("depth", 1)),
        )

    return {
        "name": "get_call_graph",
        "description": (
            "Get the call graph for a function: what it calls and what calls it. "
            "Useful for understanding control flow without reading entire files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "function": {"type": "string", "description": "Function or method name"},
                "depth": {"type": "integer", "description": "How many levels deep to trace (default 1)"},
            },
            "required": ["function"],
        },
        "execute": _execute,
    }
