"""Code: Huginn's code editor. A folder is the project: its files down the left, open files as tabs, a terminal
underneath, Git built in, search across the project, and language servers (the same ones VS Code uses) for
completions, live problems and go-to-definition.

Opening a file when Code is already running hands it to the open window (one Code at a time)."""
import json
import os
import re
import shutil
import sys
import tempfile
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import (Property, QFileSystemWatcher, QObject, QProcess, QStandardPaths, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtQuick import QQuickImageProvider

import huginn_debug as hd

STATE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "code.json"
TEXT_LIMIT = 8 * 1024 * 1024
HEAVY = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", "dist", ".mypy_cache", ".pytest_cache", ".tox", ".cache", ".idea", ".gradle"}
LIST_LIMIT = 30000

# name: (suffixes or file names, line comment, block comment, key words, LSP language id, servers to try)
LANGS = {
    "Python": ((".py", ".pyw", ".pyi"), "#", None, "and as assert async await break class continue def del elif else except finally for from global if import in is lambda match case nonlocal not or pass raise return try while with yield None True False self cls",
               "python", [["pylsp"], ["pyright-langserver", "--stdio"], ["jedi-language-server"]]),
    "C": ((".c", ".h"), "//", ("/*", "*/"), "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false NULL",
          "c", [["clangd"]]),
    "C++": ((".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"), "//", ("/*", "*/"), "alignas auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern false float for friend if inline int long mutable namespace new noexcept nullptr operator override private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while co_await co_return",
            "cpp", [["clangd"]]),
    "Rust": ((".rs",), "//", ("/*", "*/"), "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
             "rust", [["rust-analyzer"]]),
    "Go": ((".go",), "//", ("/*", "*/"), "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil",
           "go", [["gopls"]]),
    "JavaScript": ((".js", ".mjs", ".cjs", ".jsx"), "//", ("/*", "*/"), "async await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new of return static super switch this throw try typeof var void while yield true false null undefined",
                   "javascript", [["typescript-language-server", "--stdio"]]),
    "TypeScript": ((".ts", ".tsx", ".mts"), "//", ("/*", "*/"), "abstract as async await break case catch class const continue declare default delete do else enum export extends finally for from function if implements import in instanceof interface let namespace new of private protected public readonly return static super switch this throw try type typeof var void while yield true false null undefined",
                   "typescript", [["typescript-language-server", "--stdio"]]),
    "QML": ((".qml",), "//", ("/*", "*/"), "import property signal readonly required alias function var let const if else for while return true false null undefined id component default",
            "qml", [["qmlls"], ["qmlls6"]]),
    "Java": ((".java",), "//", ("/*", "*/"), "abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long new package private protected public return short static super switch this throw throws try void volatile while true false null var record",
             "java", [["jdtls"]]),
    "C#": ((".cs",), "//", ("/*", "*/"), "abstract as base bool break case catch class const continue decimal default do double else enum event false finally float for foreach if in int interface internal is namespace new null object out override private protected public readonly ref return sealed static string struct switch this throw true try using var virtual void while async await",
           "csharp", [["omnisharp", "-lsp"]]),
    "Shell": ((".sh", ".bash", ".zsh", ".bashrc", ".profile", ".zshrc"), "#", None, "if then else elif fi for while until do done case esac in function return exit export local readonly set unset echo cd source shift",
              "shellscript", [["bash-language-server", "start"]]),
    "JSON": ((".json", ".jsonc", ".hsheet", ".hslides", ".code-workspace"), "", None, "true false null", "json", [["vscode-json-languageserver", "--stdio"]]),
    "YAML": ((".yml", ".yaml"), "#", None, "true false null yes no on off", "yaml", [["yaml-language-server", "--stdio"]]),
    "TOML": ((".toml",), "#", None, "true false", "toml", [["taplo", "lsp", "stdio"]]),
    "Settings": ((".conf", ".ini", ".cfg", ".desktop", ".service", ".list", ".env", ".properties", ".gitignore", ".gitattributes", ".editorconfig"), "#", None, "true false yes no on off", "ini", []),
    "Markdown": ((".md", ".markdown"), "", None, "", "markdown", []),
    "HTML": ((".html", ".htm", ".xml", ".svg", ".ui", ".xhtml"), "", ("<!--", "-->"), "", "html", [["vscode-html-language-server", "--stdio"]]),
    "CSS": ((".css", ".scss", ".less"), "", ("/*", "*/"), "important", "css", [["vscode-css-language-server", "--stdio"]]),
    "SQL": ((".sql",), "--", ("/*", "*/"), "select from where insert into values update set delete create table drop alter join left right inner outer on group by order having limit as and or not null primary key", "sql", []),
    "Lua": ((".lua",), "--", ("--[[", "]]"), "and break do else elseif end false for function if in local nil not or repeat return then true until while", "lua", [["lua-language-server"]]),
    "Make": (("Makefile", "makefile", "GNUmakefile", ".mk"), "#", None, "ifeq ifneq ifdef ifndef else endif include define endef export", "makefile", []),
    "CMake": (("CMakeLists.txt", ".cmake"), "#", None, "if else elseif endif foreach endforeach function endfunction macro endmacro set project add_executable add_library target_link_libraries find_package include", "cmake", []),
    "Docker": (("Dockerfile", "Containerfile"), "#", None, "FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL AS", "dockerfile", []),
    "Diff": ((".diff", ".patch"), "", None, "", "diff", []),
    "Text": ((".txt", ".text", ".log", ".csv", ".tsv", ".rst", ".tex", ".srt"), "", None, "", "plaintext", []),
}
SERVER_SETTINGS = {"pylsp": {"plugins": {"pycodestyle": {"enabled": False}, "mccabe": {"enabled": False}, "pyflakes": {"enabled": True}}}}
SHEBANG = {"python": "Python", "bash": "Shell", "sh": "Shell", "zsh": "Shell", "node": "JavaScript"}
RUNNERS = {"Python": 'python3 "{f}"', "Shell": 'bash "{f}"', "JavaScript": 'node "{f}"', "TypeScript": 'npx tsx "{f}"', "Go": 'go run "{f}"',
           "C": 'cc "{f}" -o /tmp/huginn-run && /tmp/huginn-run', "C++": 'c++ "{f}" -o /tmp/huginn-run && /tmp/huginn-run', "Lua": 'lua "{f}"', "Rust": 'rustc "{f}" -o /tmp/huginn-run && /tmp/huginn-run'}


def language_of(path: str, head: str = "") -> str:
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    for lang, (ends, *_rest) in LANGS.items():
        if name in ends or (suffix and suffix in ends) or (name.startswith(".") and name in ends):
            return lang
    if head.startswith("#!"):
        first = head.split("\n", 1)[0]
        for word, lang in SHEBANG.items():
            if re.search(rf"\b{word}[0-9.]*\b", first):
                return lang
    return "Text"


def fuzzy(query: str, text: str) -> int:
    """A score for `query` as a subsequence of `text` (higher is better), or -1 when it isn't one."""
    q, t = query.lower(), text.lower()
    if not q:
        return 0
    base = t.rsplit("/", 1)[-1]
    score, at, last = 0, 0, -2
    for ch in q:
        found = t.find(ch, at)
        if found < 0:
            return -1
        score += 6 if found == last + 1 else 1
        if found == 0 or t[found - 1] in "/_-. ":
            score += 4
        last, at = found, found + 1
    if q in base:
        score += 25 + (15 if base.startswith(q) else 0)
    return score - len(t) // 12


# ============================================================================================ colouring
class CodeStyler(QSyntaxHighlighter):
    """Comments (line and block), strings (including Python's triple quotes), numbers, key words, types, function
    names, decorators and preprocessor lines, carried across lines with the block state."""
    WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    NUMBER = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(\.\d+)?([eE][+-]?\d+)?")

    def __init__(self, document, language: str, colours: dict):
        super().__init__(document)
        _, self.line, self.block, words, *_ = LANGS.get(language, LANGS["Text"])
        self.words = set(words.split())
        self.lang = language
        self.fmt = {}
        for name in ("key", "comment", "string", "number", "type", "func", "deco", "head"):
            f = QTextCharFormat()
            f.setForeground(QColor(colours.get(name) or colours.get("key", "#888888")))
            self.fmt[name] = f
        self.fmt["key"].setFontWeight(QFont.Weight.DemiBold)
        self.fmt["head"].setFontWeight(QFont.Weight.Bold)
        self.fmt["comment"].setFontItalic(True)

    def highlightBlock(self, text: str) -> None:
        lang = self.lang
        if lang == "Text":
            return
        if lang == "Markdown":
            if text.startswith("#"):
                self.setFormat(0, len(text), self.fmt["head"])
            elif text.startswith("```"):
                self.setFormat(0, len(text), self.fmt["comment"])
            elif text.lstrip().startswith(("- ", "* ", "> ", "1. ")):
                self.setFormat(0, len(text) - len(text.lstrip()) + 1, self.fmt["key"])
            return
        if lang == "Diff":
            if text.startswith("+"):
                self.setFormat(0, len(text), self.fmt["string"])
            elif text.startswith("-"):
                self.setFormat(0, len(text), self.fmt["deco"])
            elif text.startswith("@@"):
                self.setFormat(0, len(text), self.fmt["type"])
            return
        i, n = 0, len(text)
        self.setCurrentBlockState(0)
        state = self.previousBlockState()
        if state == 1 and self.block:                        # inside a block comment
            end = text.find(self.block[1])
            if end < 0:
                self.setFormat(0, n, self.fmt["comment"])
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + len(self.block[1]), self.fmt["comment"])
            i = end + len(self.block[1])
        elif state in (2, 3):                                # inside a Python triple-quoted string
            quote = '"""' if state == 2 else "'''"
            end = text.find(quote)
            if end < 0:
                self.setFormat(0, n, self.fmt["string"])
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self.fmt["string"])
            i = end + 3
        if lang in ("C", "C++") and text.lstrip().startswith("#"):
            self.setFormat(0, n, self.fmt["deco"])
            return
        while i < n:
            ch = text[i]
            if self.block and text.startswith(self.block[0], i):
                end = text.find(self.block[1], i + len(self.block[0]))
                if end < 0:
                    self.setFormat(i, n - i, self.fmt["comment"])
                    self.setCurrentBlockState(1)
                    return
                self.setFormat(i, end + len(self.block[1]) - i, self.fmt["comment"])
                i = end + len(self.block[1])
                continue
            if self.line and text.startswith(self.line, i) and (self.line != "#" or lang not in ("C", "C++") ):
                if self.line == "#" and lang == "Shell" and i > 0 and text[i - 1] not in " \t;":
                    i += 1
                    continue
                self.setFormat(i, n - i, self.fmt["comment"])
                return
            if lang == "Python" and text.startswith(('"""', "'''"), i):
                quote = text[i:i + 3]
                end = text.find(quote, i + 3)
                if end < 0:
                    self.setFormat(i, n - i, self.fmt["string"])
                    self.setCurrentBlockState(2 if quote == '"""' else 3)
                    return
                self.setFormat(i, end + 3 - i, self.fmt["string"])
                i = end + 3
                continue
            if ch in "\"'`":
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self.fmt["string"])
                i = j + 1
                continue
            if ch == "@" and lang in ("Python", "Java", "TypeScript", "C#"):
                m = self.WORD.match(text, i + 1)
                if m:
                    self.setFormat(i, m.end() - i, self.fmt["deco"])
                    i = m.end()
                    continue
            if ch.isdigit() and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                m = self.NUMBER.match(text, i)
                if m:
                    self.setFormat(i, m.end() - i, self.fmt["number"])
                    i = m.end()
                    continue
            m = self.WORD.match(text, i)
            if m:
                word = m.group()
                if word in self.words:
                    self.setFormat(i, len(word), self.fmt["key"])
                elif m.end() < n and text[m.end()] == "(":
                    self.setFormat(i, len(word), self.fmt["func"])
                elif word[0].isupper() and len(word) > 1 and lang not in ("Shell", "SQL", "Docker"):
                    self.setFormat(i, len(word), self.fmt["type"])
                elif lang == "JSON" and m.end() < n and text[m.end():].lstrip().startswith(":"):
                    self.setFormat(i, len(word), self.fmt["type"])
                i = m.end()
                continue
            i += 1


# ============================================================================================ language servers
class LspClient(QObject):
    """One language server for one project: speaks JSON-RPC over the server's standard input and output."""
    diagnostics = Signal(str, list)          # file uri, [{line, col, endLine, endCol, severity, message, source}]
    ready = Signal()
    failed = Signal(str)

    def __init__(self, argv: list, root: Path, lang_id: str, parent=None):
        super().__init__(parent)
        self.argv, self.root, self.lang_id = argv, root, lang_id
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(root))
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.errorOccurred.connect(lambda e: self.failed.emit(f"{argv[0]} didn't start") if e == QProcess.FailedToStart else None)
        self.proc.finished.connect(lambda *_: self._gone())
        self._buf, self._next, self._waiting, self._queue = b"", 1, {}, []
        self.up, self.caps, self.alive = False, {}, True
        self.proc.start(argv[0], argv[1:])
        self._request("initialize", {
            "processId": os.getpid(), "rootUri": root.as_uri(), "rootPath": str(root), "clientInfo": {"name": "Huginn Code"},
            "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {"textDocument": {
                "synchronization": {"didSave": True, "dynamicRegistration": False},
                "completion": {"completionItem": {"snippetSupport": False, "documentationFormat": ["plaintext", "markdown"]}, "contextSupport": True},
                "hover": {"contentFormat": ["plaintext", "markdown"]}, "definition": {}, "references": {}, "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                "rename": {"prepareSupport": False},
                "publishDiagnostics": {"relatedInformation": False}, "formatting": {}},
                "workspace": {"workspaceFolders": True, "configuration": True, "workspaceEdit": {"documentChanges": True}}}}, self._started, early=True)

    def _gone(self) -> None:
        self.alive, self.up = False, False

    def _started(self, result, error) -> None:
        if error:
            self.failed.emit(str(error.get("message", error)))
            return
        self.caps = (result or {}).get("capabilities", {})
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self._send({"jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": {"settings": SERVER_SETTINGS}})
        self.up = True
        for msg in self._queue:
            self._send(msg)
        self._queue = []
        self.ready.emit()

    def _send(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        self.proc.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def _post(self, msg: dict, early: bool = False) -> None:
        if self.up or early:
            self._send(msg)
        else:
            self._queue.append(msg)

    def _request(self, method: str, params: dict, then=None, early: bool = False) -> int:
        rid = self._next
        self._next += 1
        if then:
            self._waiting[rid] = then
        self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, early)
        return rid

    def notify(self, method: str, params: dict) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, then) -> int:
        return self._request(method, params, then)

    def _read(self) -> None:
        self._buf += bytes(self.proc.readAllStandardOutput())
        while True:
            head_end = self._buf.find(b"\r\n\r\n")
            if head_end < 0:
                return
            m = re.search(rb"Content-Length:\s*(\d+)", self._buf[:head_end], re.I)
            if not m:
                self._buf = self._buf[head_end + 4:]
                continue
            size = int(m.group(1))
            if len(self._buf) < head_end + 4 + size:
                return
            body, self._buf = self._buf[head_end + 4:head_end + 4 + size], self._buf[head_end + 4 + size:]
            try:
                self._handle(json.loads(body))
            except (ValueError, KeyError, TypeError):
                continue

    def _handle(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            then = self._waiting.pop(msg["id"], None)
            if then:
                then(msg.get("result"), msg.get("error"))
            return
        method = msg.get("method", "")
        if method == "textDocument/publishDiagnostics":
            p = msg.get("params", {})
            out = []
            for d in p.get("diagnostics", []):
                r = d.get("range", {})
                out.append({"line": r.get("start", {}).get("line", 0), "col": r.get("start", {}).get("character", 0),
                            "endLine": r.get("end", {}).get("line", 0), "endCol": r.get("end", {}).get("character", 0),
                            "severity": d.get("severity", 1), "message": d.get("message", ""), "source": d.get("source", "")})
            self.diagnostics.emit(p.get("uri", ""), out)
        elif "id" in msg:                                     # a request from the server: answer politely
            result = None
            if method == "workspace/configuration":
                result = [SERVER_SETTINGS.get((it.get("section") or "").split(".")[0]) for it in msg.get("params", {}).get("items", [])]
            elif method == "workspace/workspaceFolders":
                result = [{"uri": self.root.as_uri(), "name": self.root.name}]
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def stop(self) -> None:
        if self.alive and self.proc.state() != QProcess.NotRunning:
            if self.up:
                self._send({"jsonrpc": "2.0", "id": self._next, "method": "shutdown", "params": None})
                self._send({"jsonrpc": "2.0", "method": "exit", "params": None})
                self.proc.waitForFinished(800)
            if self.proc.state() != QProcess.NotRunning:
                self.proc.kill()
                self.proc.waitForFinished(500)


# ============================================================================================ one open file
class Doc:
    def __init__(self, path: str):
        self.path, self.text, self.saved = path, "", ""
        self.encoding, self.bom, self.crlf, self.mtime = "utf-8", False, False, 0.0
        self.read_only, self.why, self.lang, self.version = False, "", "Text", 1
        self.problems, self.marks, self.binary = [], {}, False

    @property
    def dirty(self) -> bool:
        return self.text != self.saved

    @property
    def uri(self) -> str:
        return Path(self.path).as_uri()

    def load(self) -> None:
        p = Path(self.path)
        with open(p, "rb") as f:
            head = f.read(8192)
        if b"\0" in head:
            self.binary, self.why, self.read_only = True, "This file isn't text, so Code can't show it.", True
            return
        if p.stat().st_size > TEXT_LIMIT:
            self.binary, self.why, self.read_only = True, "This file is too large to edit here (over 8 MB).", True
            return
        data = p.read_bytes()
        self.bom = data.startswith(b"\xef\xbb\xbf")
        try:
            text = data[3 if self.bom else 0:].decode("utf-8")
            self.encoding = "utf-8"
        except UnicodeDecodeError:
            text, self.encoding = data.decode("latin-1"), "latin-1"
        self.crlf = "\r\n" in text
        self.text = self.saved = text.replace("\r\n", "\n") if self.crlf else text
        self.mtime = p.stat().st_mtime
        self.lang = language_of(self.path, text[:200])
        if not os.access(p, os.W_OK):
            self.read_only, self.why = True, "You don't have permission to change this file."

    def save(self, force: bool = False) -> str:
        target = Path(os.path.realpath(self.path))
        if not force and target.exists() and self.mtime and abs(target.stat().st_mtime - self.mtime) > 0.001:
            return "changed"
        text = self.text.replace("\n", "\r\n") if self.crlf else self.text
        try:
            data = (b"\xef\xbb\xbf" if self.bom else b"") + text.encode(self.encoding)
        except UnicodeEncodeError:
            self.encoding = "utf-8"
            data = text.encode("utf-8")
        tmp = target.with_name(f".{target.name}.saving")
        try:
            tmp.write_bytes(data)
            if target.exists():
                shutil.copymode(target, tmp)
            os.replace(tmp, target)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            with open(target, "wb") as f:
                f.write(data)
        self.saved, self.mtime = self.text, target.stat().st_mtime
        return ""


def indent_of(text: str) -> str:
    """The file's own indentation: a tab, or 2 or 4 (or 8) spaces."""
    counts = {}
    for line in text.split("\n")[:2000]:
        if line.startswith("\t"):
            counts["\t"] = counts.get("\t", 0) + 1
        else:
            m = re.match(r"^( +)\S", line)
            if m:
                n = len(m.group(1))
                for size in (2, 4, 8):
                    if n % size == 0:
                        counts[size] = counts.get(size, 0) + (1 if size == 4 else 0.9 if size == 2 else 0.5)
    if not counts:
        return "    "
    best = max(counts, key=counts.get)
    return "\t" if best == "\t" else " " * best


def git(root: Path, *args, timeout: int = 20, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", **(env or {})))


def parse_status(out: str) -> tuple:
    """`git status --porcelain=v1 -b -z` -> (branch line, [{path, x, y, kind}])."""
    parts, branch, changes, i = out.split("\0"), "", [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("## "):
            branch = entry[3:]
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1                                            # the old name follows
        kind = "new" if (x, y) == ("?", "?") else "added" if x == "A" else "deleted" if "D" in (x, y) else "renamed" if x == "R" else "conflict" if "U" in (x, y) or (x, y) in (("A", "A"), ("D", "D")) else "changed"
        changes.append({"path": path, "x": x, "y": y, "kind": kind, "staged": x not in " ?", "unstaged": y != " "})
    return branch, changes


def parse_hunks(diff: str) -> dict:
    """`git diff -U0` -> {line (0-based): "add" | "mod" | "del"} for the gutter."""
    marks = {}
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        old_n = int(m.group(2)) if m.group(2) is not None else 1
        start, new_n = int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1
        if new_n == 0:
            marks[max(0, start - 1)] = "del"
        else:
            for k in range(new_n):
                marks[start - 1 + k] = "add" if old_n == 0 else "mod"
    return marks


def diff_rows(diff: str) -> list:
    """A unified diff as rows for the window: {text, kind: add/del/hunk/head/same, old, new}."""
    rows, old, new = [], 0, 0
    for line in diff.split("\n"):
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "rename ")):
            continue
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            rows.append({"text": m.group(3).strip() or "…", "kind": "hunk", "old": "", "new": ""})
        elif line.startswith("+"):
            rows.append({"text": line[1:], "kind": "add", "old": "", "new": str(new)})
            new += 1
        elif line.startswith("-"):
            rows.append({"text": line[1:], "kind": "del", "old": str(old), "new": ""})
            old += 1
        elif line.startswith(" "):
            rows.append({"text": line[1:], "kind": "same", "old": str(old), "new": str(new)})
            old += 1
            new += 1
    return rows


# ------------------------------------------------------------------------------------------- who wrote what, and when
def ago(ts: float, now: float = None) -> str:
    d = max(0, (now or time.time()) - ts)
    for size, unit in ((31536000, "year"), (2592000, "month"), (604800, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if d >= size:
            n = int(d // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def parse_blame(porcelain: str) -> list:
    """`git blame --porcelain` -> one entry a line: {sha, author, time, summary}."""
    commits, lines, cur = {}, [], None
    for raw in porcelain.split("\n"):
        if not raw:
            continue
        if raw.startswith("\t"):
            if cur:
                lines.append(cur)
            continue
        parts = raw.split(" ")
        if len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]) and len(parts) >= 3:
            sha = parts[0]
            info = commits.setdefault(sha, {"sha": sha, "author": "", "time": 0, "summary": ""})
            cur = info
        elif cur is not None:
            key, _, val = raw.partition(" ")
            if key == "author":
                cur["author"] = val
            elif key == "author-time":
                cur["time"] = int(val)
            elif key == "summary":
                cur["summary"] = val
    return lines


def lane_graph(commits: list) -> list:
    """Lanes for a commit graph (newest first): each commit gets its lane and the lines to draw to the next row."""
    lanes = []
    out = []
    for c in commits:
        sha, parents = c["sha"], c.get("parents") or []
        if sha in lanes:
            lane = lanes.index(sha)
        else:
            lanes.append(sha)
            lane = len(lanes) - 1
        before = list(lanes)
        lanes[lane] = parents[0] if parents else None
        for p in parents[1:]:
            if p not in lanes:
                lanes.append(p)
        # two lanes waiting for the same commit join
        seen = {}
        for k, x in enumerate(lanes):
            if x is None:
                continue
            if x in seen:
                lanes[k] = None
            else:
                seen[x] = k
        while lanes and lanes[-1] is None:
            lanes.pop()
        down = []                                              # from this row's lanes to the next row's
        for k, x in enumerate(before):
            if x is None:
                continue
            if k == lane:
                for p in parents:
                    if p in lanes:
                        down.append([k, lanes.index(p)])
            elif x in lanes:
                down.append([k, lanes.index(x)])
        out.append(dict(c, lane=lane, width=max(len(before), len(lanes), 1), down=down))
    return out


def parse_log(out: str) -> list:
    commits = []
    for line in out.split("\n"):
        f = line.split("\x1f")
        if len(f) >= 7:
            commits.append({"sha": f[0], "short": f[1], "author": f[2], "time": int(f[3] or 0), "subject": f[4], "parents": f[5].split(), "refs": f[6].strip()})
    return commits


def show_rows(text: str) -> list:
    """`git show` of a commit: a heading row for each file, then its changes."""
    rows = []
    for chunk in re.split(r"^(?=diff --git )", text, flags=re.M):
        m = re.match(r"diff --git a/(.+?) b/(.+)", chunk)
        if not m:
            continue
        rows.append({"text": m.group(2), "kind": "file", "old": "", "new": ""})
        rows += diff_rows(chunk)
    return rows


# ------------------------------------------------------------------------------------------- tests
def test_framework(root: Path) -> str:
    if root is None:
        return ""
    if (root / "Cargo.toml").exists() and shutil.which("cargo"):
        return "cargo"
    if (root / "go.mod").exists() and shutil.which("go"):
        return "go"
    py_tests = any(root.glob("test_*.py")) or any(root.glob("tests/**/test_*.py")) or any(root.glob("**/*_test.py"))
    if py_tests or (root / "pytest.ini").exists() or "[tool.pytest" in _read(root / "pyproject.toml"):
        return "pytest"
    return ""


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def test_line(root: Path, file: str, name: str) -> int:
    base = name.split("[")[0].split("::")[-1]
    text = _read(root / file)
    m = re.search(rf"^[ \t]*(?:async[ \t]+)?(?:def|fn|func)[ \t]+{re.escape(base)}\b", text, re.M)
    return text[:m.start()].count("\n") if m else 0


def parse_pytest_collect(out: str, root: Path) -> list:
    tests = []
    for line in out.splitlines():
        line = line.strip()
        if "::" not in line or line.startswith(("=", "<")) or " " in line.split("::")[0]:
            continue
        file = line.split("::")[0]
        name = line.split("::", 1)[1]
        tests.append({"id": line, "name": name.replace("::", " › "), "file": file, "line": test_line(root, file, name), "group": file})
    return tests


def parse_junit(xml: str) -> dict:
    """pytest's JUnit XML -> {test id: {status, message, seconds}}."""
    import xml.etree.ElementTree as ET
    out = {}
    try:
        tree = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for case in tree.iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        status, msg = "passed", ""
        for child in case:
            if child.tag in ("failure", "error"):
                status, msg = "failed", (child.get("message") or "") + "\n" + (child.text or "")
            elif child.tag == "skipped":
                status, msg = "skipped", child.get("message") or ""
        out[(cls, name)] = {"status": status, "message": msg.strip()[:4000], "seconds": float(case.get("time") or 0)}
    return out


def junit_for(results: dict, test_id: str) -> dict:
    """Find a pytest id (path/to/test_x.py::Class::test_y) among JUnit results keyed (classname, name)."""
    file, _, rest = test_id.partition("::")
    mod = file[:-3].replace("/", ".") if file.endswith(".py") else file
    parts = rest.split("::")
    name = parts[-1]
    cls = ".".join([mod] + parts[:-1])
    return results.get((cls, name)) or next((v for (c, n), v in results.items() if n == name and c.endswith(".".join(parts[:-1]) if parts[:-1] else mod.split(".")[-1])), None)


def parse_cargo(out: str) -> dict:
    res = {}
    for m in re.finditer(r"^test (\S+) \.\.\. (ok|FAILED|ignored)", out, re.M):
        res[m.group(1)] = {"status": {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)], "message": "", "seconds": 0.0}
    for m in re.finditer(r"^---- (\S+) stdout ----\n(.*?)(?=^---- |\Z|^failures:)", out, re.M | re.S):
        if m.group(1) in res:
            res[m.group(1)]["message"] = m.group(2).strip()[:4000]
    return res


def parse_go(out: str) -> dict:
    res = {}
    last = {}
    for line in out.splitlines():
        m = re.match(r"\s*--- (PASS|FAIL|SKIP): (\S+) \(([\d.]+)s\)", line)
        if m:
            res[m.group(2)] = {"status": {"PASS": "passed", "FAIL": "failed", "SKIP": "skipped"}[m.group(1)], "message": "\n".join(last.get(m.group(2), []))[:4000], "seconds": float(m.group(3))}
            continue
        m = re.match(r"=== RUN\s+(\S+)", line)
        if m:
            cur = m.group(1)
            last[cur] = []
        elif last:
            last[list(last)[-1]].append(line.strip())
    return res


def run_command(root: Path, doc_path: str, lang: str) -> str:
    """What Run does: the project's own way if it has one, otherwise run the file in front."""
    if root:
        if (root / ".huginn-run").is_file():
            return (root / ".huginn-run").read_text(encoding="utf-8").strip()
        if (root / "Cargo.toml").is_file():
            return "cargo run"
        if (root / "go.mod").is_file():
            return "go run ."
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            except (OSError, ValueError):
                scripts = {}
            for name in ("dev", "start"):
                if name in scripts:
                    return f"npm run {name}"
        if (root / "CMakeLists.txt").is_file():
            return "cmake -S . -B build && cmake --build build"
        if (root / "Makefile").is_file() or (root / "makefile").is_file():
            return "make"
        if (root / "manage.py").is_file():
            return "python3 manage.py runserver"
    if doc_path and lang in RUNNERS:
        return RUNNERS[lang].format(f=doc_path)
    return ""


def list_files(root: Path) -> list:
    """Every file in the project, relative paths: Git's own list (which honours .gitignore) when it's a repository."""
    if (root / ".git").exists() and shutil.which("git"):
        try:
            out = git(root, "ls-files", "-co", "--exclude-standard", "-z", timeout=20)
            if out.returncode == 0:
                return [p for p in out.stdout.split("\0") if p][:LIST_LIMIT]
        except (OSError, subprocess.SubprocessError):
            pass
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in HEAVY)
        rel = os.path.relpath(dirpath, root)
        for f in sorted(files):
            found.append(f if rel == "." else f"{rel}/{f}")
            if len(found) >= LIST_LIMIT:
                return found
    return found


def search_files(root: Path, query: str, case: bool, regex: bool, word: bool, cap: int = 2000) -> list:
    """Every line in the project matching `query`: [{path, line, col, length, text}]. Uses ripgrep when it's there."""
    if not query:
        return []
    hits = []
    if shutil.which("rg"):
        args = ["rg", "--json", "--max-columns", "400", "--max-columns-preview", "--max-filesize", "4M"]
        args += ["-s" if case else "-i"]
        if not regex:
            args.append("-F")
        if word:
            args.append("-w")
        args += ["-g", "!.git", "--", query, "."]
        try:
            proc = subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for raw in proc.stdout:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("type") != "match":
                    continue
                data = msg["data"]
                text = data["lines"].get("text", "").rstrip("\n")
                for sub in data.get("submatches", [])[:20]:
                    col = len(data["lines"].get("text", "").encode("utf-8")[:sub["start"]].decode("utf-8", "ignore"))
                    length = len(sub["match"].get("text", ""))
                    hits.append({"path": data["path"]["text"].removeprefix("./"), "line": data["line_number"] - 1, "col": col, "length": length, "text": text})
                if len(hits) >= cap:
                    proc.kill()
                    break
            proc.wait(timeout=5)
            return hits[:cap]
        except (OSError, subprocess.SubprocessError):
            hits = []
    flags = 0 if case else re.I
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error:
        return []
    for rel in list_files(root):
        p = root / rel
        try:
            if p.stat().st_size > 4 * 1024 * 1024:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").split("\n")):
            for m in pattern.finditer(line):
                if word and ((m.start() > 0 and (line[m.start() - 1].isalnum() or line[m.start() - 1] == "_")) or (m.end() < len(line) and (line[m.end()].isalnum() or line[m.end()] == "_"))):
                    continue
                hits.append({"path": rel, "line": n, "col": m.start(), "length": m.end() - m.start(), "text": line[:400]})
                if len(hits) >= cap:
                    return hits
    return hits


# ============================================================================================ the app
class Code(QObject):
    changed = Signal()            # tabs, status, problems, git
    treeChanged = Signal()
    textLoaded = Signal(int)      # the editor for tab n must take the file's text again
    jump = Signal(int, int, int)  # tab, line, column: move the cursor there
    completions = Signal(int, "QVariantList")   # tab, items
    hoverText = Signal(int, str)
    searchDone = Signal()
    said = Signal(str, bool)
    shown = Signal()
    _back = Signal(object)

    def __init__(self, demo: bool = False, target: str = "", shell_class=None, settings=None, trash=None):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._demo, self._shell_class, self._settings, self._trash = demo, shell_class, settings, trash
        self._root, self._docs, self._at = None, [], -1
        self._open_dirs, self._tree, self._files_cache = set(), [], None
        self._recent, self._size, self._wrap = [], 14, False
        self._results, self._searching, self._query = [], False, ""
        self._branch, self._changes, self._git = "", [], False
        self._servers, self._server_note = {}, {}
        self._term, self._busy = None, ""
        self._results_title = ""
        self._dbg = hd.Debugger(self)
        self._dbg.landed.connect(self._landed)
        self._dbg.said.connect(self.said.emit)
        self._dbg.changed.connect(self._dbg_changed)
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _p: self._soon.start())
        self._watch.fileChanged.connect(lambda _p: self._soon.start())         # an open file changed on disk
        self._soon = QTimer(self, singleShot=True, interval=400)
        self._soon.timeout.connect(self._refresh)
        self._lint = QTimer(self, singleShot=True, interval=500)
        self._lint.timeout.connect(self._push_changes)
        self._load_state()
        if demo:
            self._demo_fill()
        elif target:
            t = Path(target).expanduser()
            if t.is_dir():
                self.openFolder(str(t))
            elif t.exists():
                self._restore_last(keep_docs=False)
                self.openFile(str(t))
        else:
            self._restore_last()

    # ---------------------------------------------------------------- remembering
    def _load_state(self) -> None:
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._state = data if isinstance(data, dict) else {}
        self._recent = [r for r in self._state.get("recent", []) if isinstance(r, str)][:10]
        self._size = int(self._state.get("size", 14)) if str(self._state.get("size", 14)).isdigit() else 14
        self._wrap = bool(self._state.get("wrap", False))
        self._minimap = bool(self._state.get("minimap", True))

    def _keep(self) -> None:
        if self._demo:
            return
        if self._root:
            self._state.setdefault("projects", {})[str(self._root)] = {"open": [d.path for d in self._docs], "at": self._at, "dirs": sorted(self._open_dirs)[:200],
                                                                    "breakpoints": {k: v for k, v in self._dbg.all_breakpoints().items() if k.startswith(str(self._root))}}
        self._state.update(recent=self._recent, size=self._size, wrap=self._wrap, minimap=self._minimap, last=str(self._root) if self._root else "")
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE.with_suffix(".saving")
            tmp.write_text(json.dumps(self._state), encoding="utf-8")
            os.replace(tmp, STATE)
        except OSError:
            pass

    def _restore_last(self, keep_docs: bool = True) -> None:
        last = self._state.get("last")
        if last and Path(last).is_dir():
            self.openFolder(last, restore=keep_docs)

    def _demo_fill(self) -> None:
        demo = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "huginn-code-demo" / "aurora-watch"
        shutil.rmtree(demo, ignore_errors=True)
        (demo / "aurora").mkdir(parents=True)
        (demo / "tests").mkdir()
        (demo / "README.md").write_text("# Aurora Watch\n\nTells you when the northern lights are worth going out for.\n\n```\npython3 -m aurora --city Tromsø\n```\n", encoding="utf-8")
        (demo / "aurora" / "__init__.py").write_text('"""Aurora Watch."""\n__version__ = "0.3.0"\n', encoding="utf-8")
        (demo / "aurora" / "forecast.py").write_text('''"""Is tonight worth it? A score from the Kp index, the clouds and how dark it is."""
from dataclasses import dataclass

DARK_HOURS = range(20, 24)


@dataclass
class Sky:
    kp: float          # geomagnetic activity, 0 to 9
    clouds: int        # percent
    hour: int


def score(sky: Sky) -> int:
    """0 to 100: how likely you'll see it."""
    if sky.hour not in DARK_HOURS:
        return 0
    base = min(sky.kp / 6, 1.0) * 100
    return round(base * (1 - sky.clouds / 100))


def advice(sky: Sky) -> str:
    s = score(sky)
    if s > 60:
        return f"Go now: {s}% chance"
    return "Stay in tonight" if s < 20 else f"Maybe later ({s}%)"
''', encoding="utf-8")
        (demo / "tests" / "test_forecast.py").write_text("from aurora.forecast import Sky, score\n\n\ndef test_cloudy():\n    assert score(Sky(kp=5, clouds=100, hour=22)) == 0\n", encoding="utf-8")
        (demo / "pyproject.toml").write_text('[project]\nname = "aurora-watch"\nversion = "0.3.0"\n', encoding="utf-8")
        self.openFolder(str(demo), restore=False)
        self._open_dirs.update({str(demo / "aurora"), str(demo / "tests")})
        self._build_tree()
        self.openFile(str(demo / "aurora" / "forecast.py"))
        self.openFile(str(demo / "README.md"))
        self.select(0)
        self._branch, self._git = "main", True
        self._changes = [{"path": "aurora/forecast.py", "x": " ", "y": "M", "kind": "changed", "staged": False, "unstaged": True},
                         {"path": "tests/test_forecast.py", "x": "?", "y": "?", "kind": "new", "staged": False, "unstaged": True}]
        d = self._docs[0]
        d.marks = {14: "mod", 15: "mod", 22: "add", 23: "add"}
        d.problems = [{"line": 17, "col": 11, "endLine": 17, "endCol": 15, "severity": 2, "message": "'base' could be negative when kp is below zero", "source": "demo"}]
        d.text = d.text.replace("    s = score(sky)", "    s = score(sky)  # one number for the window")
        self.changed.emit()

    # ---------------------------------------------------------------- the project
    @Slot(str)
    def openFolder(self, path: str, restore: bool = True) -> None:
        try:                                                       # read before opening: opening saves the state again
            saved = ((self._state.get("projects") or {}).get(str(Path(path.replace("file://", "")).expanduser().resolve())) or {}).get("breakpoints") or {}
        except (OSError, RuntimeError):
            saved = {}
        self._open_folder(path, restore)
        if self._root:                                             # the project's breakpoints come back with it
            self._dbg.set_all(saved)
            self._keep()
            self.changed.emit()

    def _open_folder(self, path: str, restore: bool = True) -> None:
        root = Path(path.replace("file://", "")).expanduser().resolve()
        if not root.is_dir():
            self.said.emit("That folder isn't there any more.", True)
            return
        if self._root and root != self._root:
            if any(d.dirty for d in self._docs):
                self.said.emit("Save or close your changed files first.", True)
                return
            self._close_all()
        self._root = root
        self._recent = [str(root)] + [r for r in self._recent if r != str(root)]
        del self._recent[10:]
        saved = self._state.get("projects", {}).get(str(root), {}) if restore else {}
        self._open_dirs = {d for d in saved.get("dirs", []) if Path(d).is_dir()}
        self._files_cache = None
        self._build_tree()
        for p in saved.get("open", []):
            if Path(p).is_file():
                self.openFile(p, focus=False)
        if self._docs:
            self.select(max(0, min(saved.get("at", 0), len(self._docs) - 1)))
        self.refreshGit()
        self._keep()
        self.changed.emit()

    def _close_all(self) -> None:
        for d in self._docs:
            self._lsp_close(d)
        self._docs, self._at = [], -1
        for s in self._servers.values():
            s.stop()
        self._servers = {}

    @Slot()
    def closeFolder(self) -> None:
        if any(d.dirty for d in self._docs):
            self.said.emit("Save or close your changed files first.", True)
            return
        self._close_all()
        self._root, self._tree, self._branch, self._changes, self._git = None, [], "", [], False
        self._keep()
        self.treeChanged.emit()
        self.changed.emit()

    def _build_tree(self) -> None:
        rows = []
        if self._root:
            status = {}
            for c in self._changes:
                status[c["path"]] = c["kind"]
                parts = c["path"].split("/")
                for k in range(1, len(parts)):
                    status.setdefault("/".join(parts[:k]) + "/", "inside")

            def walk(folder: Path, depth: int) -> None:
                try:
                    entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
                except OSError:
                    return
                for e in entries:
                    if e.name == ".git":
                        continue
                    is_dir = e.is_dir()
                    rel = os.path.relpath(e.path, self._root)
                    open_ = is_dir and e.path in self._open_dirs
                    rows.append({"path": e.path, "name": e.name, "depth": depth, "dir": is_dir, "open": open_, "rel": rel,
                                 "git": status.get(rel + "/" if is_dir else rel, ""), "dim": e.name.startswith(".") or e.name in HEAVY,
                                 "lang": "" if is_dir else language_of(e.name)})
                    if open_:
                        walk(Path(e.path), depth + 1)
            walk(self._root, 0)
            dirs = [str(self._root)] + sorted(d for d in self._open_dirs if d.startswith(str(self._root)))
            old = set(self._watch.directories()) | set(self._watch.files())
            if old:
                self._watch.removePaths(list(old))
            self._watch.addPaths([d for d in dirs if Path(d).is_dir()][:300] + [d.path for d in self._docs if Path(d.path).is_file()][:200])
        self._tree = rows
        self.treeChanged.emit()

    def _refresh(self) -> None:
        self._files_cache = None
        if self._root:
            self._build_tree()
        else:
            missing = [d.path for d in self._docs if d.path not in self._watch.files() and Path(d.path).is_file()]
            if missing:
                self._watch.addPaths(missing)
        self.refreshGit()
        for i, d in enumerate(self._docs):                   # a file changed by something else, with nothing typed here: take it
            try:
                m = Path(d.path).stat().st_mtime
            except OSError:
                continue
            if d.mtime and abs(m - d.mtime) > 0.001 and not d.dirty:
                d.load()
                self.textLoaded.emit(i)

    @Slot(str)
    def toggle(self, path: str) -> None:
        if path in self._open_dirs:
            self._open_dirs = {d for d in self._open_dirs if not (d == path or d.startswith(path + os.sep))}
        else:
            self._open_dirs.add(path)
        self._build_tree()
        self._keep()

    @Slot(str, result="QVariantList")
    def browse(self, path: str) -> list:
        """Folders inside `path`, for picking a project."""
        base = Path(path or Path.home()).expanduser()
        try:
            return [{"name": e.name, "path": e.path, "git": os.path.isdir(os.path.join(e.path, ".git"))}
                    for e in sorted(os.scandir(base), key=lambda e: e.name.lower()) if e.is_dir() and not e.name.startswith(".")][:400]
        except OSError:
            return []

    @Slot(str, str, bool, result=str)
    def create(self, folder: str, name: str, is_dir: bool) -> str:
        name = name.strip()
        if not name:
            return "Type a name."
        if name in (".", "..") or "\0" in name or ".." in name.split("/"):
            return "That name can't be used."
        base = Path(folder or self._root or Path.home())
        target = (base / name).resolve()
        if self._root and not str(target).startswith(str(self._root)):
            return "That would be outside the project."
        if target.exists():
            return "Something with that name is already there."
        try:
            if is_dir:
                target.mkdir(parents=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
        except OSError as e:
            return f"Couldn't make it: {e.strerror or e}"
        self._open_dirs.add(str(target.parent))
        self._files_cache = None
        self._build_tree()
        if not is_dir:
            self.openFile(str(target))
        return ""

    @Slot(str, str, result=str)
    def rename(self, path: str, name: str) -> str:
        name = name.strip()
        if not name or "/" in name or name in (".", ".."):
            return "Type a new name (without slashes)."
        src = Path(path)
        dst = src.with_name(name)
        if dst.exists():
            return "Something with that name is already there."
        try:
            src.rename(dst)
        except OSError as e:
            return f"Couldn't rename it: {e.strerror or e}"
        for i, d in enumerate(self._docs):
            if d.path == str(src) or d.path.startswith(str(src) + os.sep):
                self._lsp_close(d)
                d.path = str(dst) + d.path[len(str(src)):]
                d.lang = language_of(d.path, d.text[:200])
                self._lsp_open(d)
        self._open_dirs = {str(dst) + p[len(str(src)):] if p == str(src) or p.startswith(str(src) + os.sep) else p for p in self._open_dirs}
        self._files_cache = None
        self._build_tree()
        self.changed.emit()
        return ""

    @Slot(str, result=str)
    def remove(self, path: str) -> str:
        """To the Trash, never deleted outright."""
        if any(d.dirty and (d.path == path or d.path.startswith(path + os.sep)) for d in self._docs):
            return "It has unsaved changes open; save or close them first."
        try:
            if self._trash:
                self._trash(path)
            else:
                subprocess.run(["gio", "trash", path], check=True, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            return f"Couldn't move it to the Trash: {e}"
        for i in reversed(range(len(self._docs))):
            d = self._docs[i]
            if d.path == path or d.path.startswith(path + os.sep):
                self._lsp_close(d)
                del self._docs[i]
        self._at = min(self._at, len(self._docs) - 1)
        self._files_cache = None
        self._build_tree()
        self.refreshGit()
        self.changed.emit()
        return ""

    @Slot(str)
    def reveal(self, path: str) -> None:
        import sys
        QProcess.startDetached(sys.executable, [str(Path(__file__).with_name("huginn_app.py")), "files", str(Path(path).parent if Path(path).is_file() else path)])

    # ---------------------------------------------------------------- open files
    @Slot(str)
    def openFile(self, path: str, focus: bool = True, line: int = -1, col: int = 0) -> None:
        path = str(Path(path.replace("file://", "")).expanduser().resolve())
        for i, d in enumerate(self._docs):
            if d.path == path:
                if focus:
                    self.select(i)
                if line >= 0:
                    self.jump.emit(i, line, col)
                return
        d = Doc(path)
        try:
            d.load()
        except OSError as e:
            self.said.emit(f"Couldn't open {Path(path).name}: {e.strerror or e}", True)
            return
        if self._root is None and not self._demo:
            pass
        self._docs.append(d)
        idx = len(self._docs) - 1
        if d.path not in self._watch.files():
            self._watch.addPath(d.path)
        self._marks(d)
        self._lsp_open(d)
        self._lint_python(d)
        if focus:
            self._at = idx
        elif self._at < 0:
            self._at = 0
        self.changed.emit()
        self.textLoaded.emit(idx)
        if line >= 0:
            self.jump.emit(idx, line, col)
        self._keep()

    @Slot(int)
    def select(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            self._at = i
            self.changed.emit()
            self._keep()

    @Slot(int, bool, result=str)
    def close(self, i: int, force: bool = False) -> str:
        """"" when closed, "dirty" when it has unsaved changes (ask, then call again with force)."""
        if not 0 <= i < len(self._docs):
            return ""
        d = self._docs[i]
        if d.dirty and not force:
            return "dirty"
        self._lsp_close(d)
        del self._docs[i]
        if not self._docs:
            self._at = -1
        elif self._at > i:
            self._at -= 1
        elif self._at == i:
            self._at = min(i, len(self._docs) - 1)
        self.changed.emit()
        self._keep()
        return ""

    @Slot(int, int)
    def move(self, i: int, to: int) -> None:
        if 0 <= i < len(self._docs) and 0 <= to < len(self._docs) and i != to:
            d = self._docs.pop(i)
            self._docs.insert(to, d)
            self._at = to
            self.changed.emit()

    @Slot(int, str)
    def edit(self, i: int, text: str) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        if text == d.text:                                    # colouring touches the document too: nothing was typed
            return
        delta = text.count("\n") - d.text.count("\n")
        if delta and self._dbg.lines_for(d.path):            # breakpoints below an added or removed line move with their code
            old, new = d.text.split("\n"), text.split("\n")
            first = next((k for k, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            self._dbg.shift(d.path, first, delta)
        was = d.dirty
        d.text = text
        d.version += 1
        self._pending = getattr(self, "_pending", set()) | {i}
        self._lint.start()
        if d.dirty != was:
            self.changed.emit()

    @Slot(int, result=str)
    def textOf(self, i: int) -> str:
        return self._docs[i].text if 0 <= i < len(self._docs) else ""

    @Slot(int, bool, result=str)
    def save(self, i: int, force: bool = False) -> str:
        """"" saved, "changed" (the file changed on disk since: ask, then force), "failed"."""
        if not 0 <= i < len(self._docs):
            return "failed"
        d = self._docs[i]
        if d.read_only:
            self.said.emit(d.why or "This file is read only.", True)
            return "failed"
        try:
            got = d.save(force)
        except OSError as e:
            self.said.emit(f"Couldn't save: {e.strerror or e}", True)
            return "failed"
        if got:
            return got
        client = self._client_for(d, start=False)
        if client:
            client.notify("textDocument/didSave", {"textDocument": {"uri": d.uri}, "text": d.text})
        self._marks(d)
        self.refreshGit()
        self.changed.emit()
        return ""

    @Slot(result=int)
    def saveAll(self) -> int:
        n = 0
        for i, d in enumerate(self._docs):
            if d.dirty and self.save(i, False) == "":
                n += 1
        return n

    @Slot(int)
    def reload(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            d = self._docs[i]
            try:
                d.load()
            except OSError:
                return
            self._marks(d)
            self.textLoaded.emit(i)
            self.changed.emit()

    @Slot()
    def newUntitled(self) -> None:
        folder = self._root or Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home())
        n, path = 1, folder / "untitled.txt"
        while path.exists():
            n += 1
            path = folder / f"untitled-{n}.txt"
        try:
            path.write_text("", encoding="utf-8")
        except OSError as e:
            self.said.emit(f"Couldn't make a file: {e.strerror or e}", True)
            return
        self._files_cache = None
        self._build_tree()
        self.openFile(str(path))

    # ---------------------------------------------------------------- what QML sees
    def _tab(self, d: Doc) -> dict:
        return {"path": d.path, "name": Path(d.path).name, "dirty": d.dirty, "lang": d.lang, "readOnly": d.read_only, "why": d.why,
                "rel": os.path.relpath(d.path, self._root) if self._root and d.path.startswith(str(self._root)) else d.path,
                "errors": sum(1 for p in d.problems if p["severity"] == 1), "binary": d.binary}

    def _get_status(self) -> dict:
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        if not d:
            return {}
        ind = indent_of(d.text)
        server = self._server_note.get(d.lang, "")
        return {"lang": d.lang, "encoding": ("UTF-8" if d.encoding == "utf-8" else "Latin-1") + (" with BOM" if d.bom else ""),
                "eol": "CRLF" if d.crlf else "LF", "indent": "Tab" if ind == "\t" else f"Spaces: {len(ind)}", "indentText": ind,
                "server": server, "comment": LANGS.get(d.lang, LANGS["Text"])[1], "block": list(LANGS.get(d.lang, LANGS["Text"])[2] or [])}

    def _get_problems(self) -> list:
        out = []
        for i, d in enumerate(self._docs):
            for p in d.problems:
                out.append(dict(p, tab=i, name=Path(d.path).name, path=d.path))
        return sorted(out, key=lambda p: (p["severity"], p["name"], p["line"]))

    tabs = Property("QVariantList", lambda self: [self._tab(d) for d in self._docs], notify=changed)
    current = Property(int, lambda self: self._at, notify=changed)
    tree = Property("QVariantList", lambda self: self._tree, notify=treeChanged)
    root = Property(str, lambda self: str(self._root) if self._root else "", notify=changed)
    rootName = Property(str, lambda self: self._root.name if self._root else "", notify=changed)
    recent = Property("QVariantList", lambda self: [{"path": r, "name": Path(r).name, "where": str(Path(r).parent).replace(str(Path.home()), "~")} for r in self._recent if Path(r).is_dir()], notify=changed)
    status = Property("QVariantMap", _get_status, notify=changed)
    problems = Property("QVariantList", _get_problems, notify=changed)
    branch = Property(str, lambda self: self._branch, notify=changed)
    isGit = Property(bool, lambda self: self._git, notify=changed)
    changes = Property("QVariantList", lambda self: self._changes, notify=changed)
    results = Property("QVariantList", lambda self: self._results, notify=searchDone)
    searching = Property(bool, lambda self: self._searching, notify=searchDone)
    size = Property(int, lambda self: self._size, notify=changed)
    wrap = Property(bool, lambda self: self._wrap, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    home = Property(str, lambda self: str(Path.home()), constant=True)
    debug = Property(QObject, lambda self: self._dbg, constant=True)
    minimap = Property(bool, lambda self: self._minimap, notify=changed)
    resultsTitle = Property(str, lambda self: self._results_title, notify=searchDone)

    @Slot(int, result="QVariantMap")
    def marksOf(self, i: int) -> dict:
        if not 0 <= i < len(self._docs):
            return {}
        return {str(k): v for k, v in self._docs[i].marks.items()}

    @Slot(int, result="QVariantList")
    def problemsOf(self, i: int) -> list:
        return self._docs[i].problems if 0 <= i < len(self._docs) else []

    @Slot(int)
    def setSize(self, n: int) -> None:
        self._size = max(9, min(32, n))
        self._keep()
        self.changed.emit()

    @Slot(bool)
    def setWrap(self, on: bool) -> None:
        self._wrap = on
        self._keep()
        self.changed.emit()

    @Slot(int, "QVariantMap")
    def style(self, i: int, payload) -> None:
        """Called by tab i's editor: colour its text as its language, in the theme's colours."""
        payload = dict(payload)
        doc_obj, colours = payload.get("doc"), dict(payload.get("colours") or {})
        if not 0 <= i < len(self._docs) or doc_obj is None:
            return
        d = self._docs[i]
        old = getattr(d, "styler", None)
        if old is not None:
            old.setDocument(None)
        d.styler = CodeStyler(doc_obj.textDocument(), d.lang, colours)

    # ---------------------------------------------------------------- finding things
    def _all_files(self) -> list:
        if self._files_cache is None:
            self._files_cache = list_files(self._root) if self._root else []
        return self._files_cache

    @Slot(str, result="QVariantList")
    def quickOpen(self, query: str) -> list:
        files = self._all_files()
        q = query.strip().replace(" ", "")
        if not q:
            recent = [os.path.relpath(d.path, self._root) for d in self._docs if self._root and d.path.startswith(str(self._root))]
            rest = [f for f in files if f not in recent]
            return [{"rel": f, "name": Path(f).name, "where": str(Path(f).parent) if str(Path(f).parent) != "." else ""} for f in (recent + rest)[:60]]
        scored = []
        for f in files:
            s = fuzzy(q, f)
            if s >= 0:
                scored.append((s, f))
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        return [{"rel": f, "name": Path(f).name, "where": str(Path(f).parent) if str(Path(f).parent) != "." else ""} for _, f in scored[:60]]

    @Slot(str, int, int)
    def openRel(self, rel: str, line: int = -1, col: int = 0) -> None:
        if Path(rel).is_absolute():
            self.openFile(rel, True, line, col)
        elif self._root:
            self.openFile(str(self._root / rel), True, line, col)

    @Slot(str, bool, bool, bool)
    def search(self, query: str, case: bool, regex: bool, word: bool) -> None:
        self._query = query
        self._results_title = ""
        if not self._root or not query.strip():
            self._results, self._searching = [], False
            self.searchDone.emit()
            return
        if regex:
            try:
                re.compile(query)
            except re.error:
                self._results, self._searching = [{"path": "", "line": -1, "col": 0, "length": 0, "text": "That pattern isn't valid."}], False
                self.searchDone.emit()
                return
        self._searching = True
        self.searchDone.emit()
        root, asked = self._root, query

        def go():
            hits = search_files(root, asked, case, regex, word)

            def done():
                if asked != self._query:
                    return
                self._results, self._searching = hits, False
                self.searchDone.emit()
            self._back.emit(done)
        threading.Thread(target=go, daemon=True).start()

    @Slot(str, str, bool, bool, bool, result=int)
    def replaceAll(self, query: str, replacement: str, case: bool, regex: bool, word: bool) -> int:
        """Replace in every file the last search found. Open files change in their tab (and can be undone there);
        files that aren't open are saved straight away. Returns how many places changed."""
        if not self._root or not query:
            return 0
        flags = 0 if case else re.I
        try:
            pat = re.compile((r"\b" if word else "") + (query if regex else re.escape(query)) + (r"\b" if word else ""), flags)
        except re.error:
            return 0
        count = 0
        for rel in sorted({h["path"] for h in self._results if h.get("path")}):
            path = str((self._root / rel).resolve())
            open_at = next((i for i, d in enumerate(self._docs) if d.path == path), -1)
            try:
                text = self._docs[open_at].text if open_at >= 0 else Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new, n = pat.subn(replacement if regex else replacement.replace("\\", "\\\\"), text)
            if not n:
                continue
            count += n
            if open_at >= 0:
                self._docs[open_at].text = new
                self.textLoaded.emit(open_at)
            else:
                d = Doc(path)
                try:
                    d.load()
                    d.text = new
                    d.save(True)
                except OSError:
                    continue
        self.changed.emit()
        self.search(query, case, regex, word)
        return count

    @Slot(int, result="QVariantList")
    def symbols(self, i: int) -> list:
        """Functions, classes and headings in tab i, found by their shape (the language server's list when it has one)."""
        if not 0 <= i < len(self._docs):
            return []
        d, out = self._docs[i], []
        patterns = {"Python": r"^\s*(?:async\s+)?(def|class)\s+(\w+)", "JavaScript": r"^\s*(?:export\s+)?(?:async\s+)?(function|class)\s+(\w+)",
                    "TypeScript": r"^\s*(?:export\s+)?(?:async\s+)?(function|class|interface|type|enum)\s+(\w+)", "Go": r"^(func|type)\s+(?:\([^)]*\)\s*)?(\w+)",
                    "Rust": r"^\s*(?:pub\s+)?(fn|struct|enum|trait|impl|mod)\s+(\w+)", "C": r"^(\w[\w\s\*]*?)\s+\**(\w+)\s*\([^;]*$", "C++": r"^(\w[\w\s\*:<>]*?)\s+\**([\w:~]+)\s*\([^;]*$",
                    "Shell": r"^\s*(function\s+)?(\w+)\s*\(\)", "Markdown": r"^(#{1,6})\s+(.+)", "QML": r"^\s*(function|property\s+\w+|signal)\s+(\w+)", "Java": r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(class|interface|enum|void|\w+)\s+(\w+)\s*[({]"}
        pat = patterns.get(d.lang)
        if not pat:
            return []
        for n, line in enumerate(d.text.split("\n")):
            m = re.match(pat, line)
            if m:
                kind = m.group(1).strip()
                out.append({"name": m.group(2).strip(), "kind": "heading" if d.lang == "Markdown" else kind.split()[0], "line": n, "depth": (len(line) - len(line.lstrip())) // 4 if d.lang != "Markdown" else len(kind) - 1})
        return out[:500]

    # ---------------------------------------------------------------- Git
    @Slot()
    def refreshGit(self) -> None:
        if self._demo:
            return
        if not self._root or not shutil.which("git"):
            self._git, self._branch, self._changes = False, "", []
            return
        try:
            out = git(self._root, "status", "--porcelain=v1", "-b", "-z", "--untracked-files=all", timeout=15)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            self._git, self._branch, self._changes = False, "", []
            self.changed.emit()
            return
        branch, changes = parse_status(out.stdout)
        top = git(self._root, "rev-parse", "--show-toplevel", timeout=5).stdout.strip()
        prefix = os.path.relpath(self._root, top) if top else "."
        if prefix != ".":                                     # the project is a folder inside a bigger repository
            changes = [dict(c, path=c["path"][len(prefix) + 1:]) for c in changes if c["path"].startswith(prefix + "/")]
        self._git, self._branch, self._changes = True, branch.split("...")[0].replace("No commits yet on ", ""), changes
        self._ahead = branch
        self._build_tree()
        self.changed.emit()

    def _marks(self, d: Doc) -> None:
        d.marks = {}
        if self._demo or not self._root or not shutil.which("git") or not d.path.startswith(str(self._root)):
            return
        try:
            out = git(Path(d.path).parent, "diff", "-U0", "--no-color", "--no-ext-diff", "HEAD", "--", Path(d.path).name, timeout=10)
            if out.returncode == 0:
                d.marks = parse_hunks(out.stdout)
            tracked = git(Path(d.path).parent, "ls-files", "--error-unmatch", "--", Path(d.path).name, timeout=5)
            if tracked.returncode != 0 and git(Path(d.path).parent, "rev-parse", timeout=5).returncode == 0:
                d.marks = {n: "add" for n in range(d.text.count("\n") + 1)}
        except (OSError, subprocess.SubprocessError):
            pass

    @Slot(str, bool, result="QVariantList")
    def diff(self, rel: str, staged: bool) -> list:
        if not self._root:
            return []
        try:
            args = ["diff", "--no-color", "--no-ext-diff", "-U3"] + (["--cached"] if staged else []) + ["--", rel]
            out = git(self._root, *args, timeout=15).stdout
            if not out.strip():
                change = next((c for c in self._changes if c["path"] == rel), None)
                if change and change["kind"] == "new":
                    text = (self._root / rel).read_text(encoding="utf-8", errors="replace")
                    return [{"text": line, "kind": "add", "old": "", "new": str(n + 1)} for n, line in enumerate(text.split("\n")[:4000])]
        except (OSError, subprocess.SubprocessError):
            return []
        return diff_rows(out)

    def _git_do(self, *args, then_say: str = "") -> str:
        if not self._root:
            return "Open a project first."
        try:
            out = git(self._root, *args, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            return str(e)
        self.refreshGit()
        for d in self._docs:
            self._marks(d)
        self.changed.emit()
        if out.returncode != 0:
            return (out.stderr or out.stdout).strip().split("\n")[-1][:300] or "Git said no."
        if then_say:
            self.said.emit(then_say, False)
        return ""

    @Slot(str, result=str)
    def stage(self, rel: str) -> str:
        return self._git_do("add", "--", rel)

    @Slot(str, result=str)
    def unstage(self, rel: str) -> str:
        return self._git_do("restore", "--staged", "--", rel)

    @Slot(result=str)
    def stageAll(self) -> str:
        return self._git_do("add", "-A")

    @Slot(str, result=str)
    def discard(self, rel: str) -> str:
        """Throw away the changes to a file (the window asks first). A new file goes to the Trash instead."""
        change = next((c for c in self._changes if c["path"] == rel), None)
        if change and change["kind"] == "new":
            return self.remove(str(self._root / rel))
        got = self._git_do("restore", "--staged", "--worktree", "--", rel)
        for i, d in enumerate(self._docs):
            if d.path == str((self._root / rel).resolve()):
                self.reload(i)
        return got

    @Slot(str, result=str)
    def commit(self, message: str) -> str:
        if not message.strip():
            return "Write a few words about what changed."
        if not any(c["staged"] for c in self._changes):
            self._git_do("add", "-A")
        return self._git_do("commit", "-m", message.strip(), then_say="Committed")

    @Slot()
    def initRepo(self) -> None:
        self._git_do("init", then_say="This folder is now a Git repository")

    @Slot(str)
    def sync(self, what: str) -> None:
        """Pull, then push (or just one), off the window's thread. Sign-in prompts can't appear, so they fail with a reason."""
        if not self._root or what not in ("pull", "push", "sync"):
            return
        self._busy = {"pull": "pulling", "push": "pushing", "sync": "syncing"}[what]
        self.changed.emit()
        root = self._root

        def go():
            msgs = []
            for step in (["pull", "--ff-only"], ["push"]) if what == "sync" else ([["pull", "--ff-only"]] if what == "pull" else [["push"]]):
                try:
                    out = git(root, *step, timeout=120)
                except (OSError, subprocess.SubprocessError) as e:
                    msgs.append((str(e), True))
                    break
                if out.returncode != 0:
                    err = (out.stderr or out.stdout).strip()
                    if "could not read Username" in err or "terminal prompts disabled" in err or "Authentication failed" in err:
                        err = "The server wants you to sign in. Run the same command in the terminal below once; Git can remember it after that."
                    msgs.append((err.split("\n")[-1][:300] if "sign in" not in err else err, True))
                    break
                msgs.append(({"pull": "Up to date with the server", "push": "Pushed"}[step[0]], False))

            def done():
                self._busy = ""
                self.refreshGit()
                for d in self._docs:
                    self._marks(d)
                for i, d in enumerate(self._docs):
                    if not d.dirty:
                        try:
                            if abs(Path(d.path).stat().st_mtime - d.mtime) > 0.001:
                                self.reload(i)
                        except OSError:
                            pass
                if msgs:
                    self.said.emit(*msgs[-1])
                self.changed.emit()
            self._back.emit(done)
        threading.Thread(target=go, daemon=True).start()

    # ---------------------------------------------------------------- terminal and Run
    def _get_term(self):
        if self._term is None and self._shell_class is not None and self._settings is not None and not self._demo:
            self._term = self._shell_class(self._settings, self._root)
        return self._term

    terminal = Property(QObject, _get_term, notify=changed)

    @Slot(result=str)
    def runCommand(self) -> str:
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        return run_command(self._root, d.path if d else "", d.lang if d else "")

    @Slot(str)
    def run(self, command: str) -> None:
        """Save everything, then type the command into the terminal below."""
        command = command.strip() or self.runCommand()
        if not command:
            self.said.emit("Nothing to run here. Put the command in a file called .huginn-run in the project.", True)
            return
        self.saveAll()
        term = self._get_term()
        if term is None:
            self.said.emit(f"Would run: {command}", False)
            return
        if self._root:
            term._send(f"cd {json.dumps(str(self._root))}\r".encode())
        term._send((command + "\r").encode("utf-8"))

    @Slot(str)
    def setRun(self, command: str) -> None:
        if self._root:
            try:
                (self._root / ".huginn-run").write_text(command.strip() + "\n", encoding="utf-8")
            except OSError as e:
                self.said.emit(f"Couldn't save it: {e.strerror or e}", True)

    # ---------------------------------------------------------------- language servers
    def _client_for(self, d: Doc, start: bool = True):
        lang = d.lang
        if lang in self._servers:
            c = self._servers[lang]
            return c if c and c.alive else None
        if not start or self._demo:
            return None
        info = LANGS.get(lang)
        if not info or not info[5]:
            return None
        argv = next((a for a in info[5] if shutil.which(a[0])), None)
        if not argv:
            self._servers[lang] = None
            self._server_note[lang] = ""
            return None
        root = self._root or Path(d.path).parent
        client = LspClient(argv, root, info[4], self)
        client.diagnostics.connect(self._got_diagnostics)
        client.failed.connect(lambda why, l=lang: (self._server_note.__setitem__(l, ""), self.said.emit(f"{l} helper: {why}", True)))
        client.ready.connect(lambda l=lang, name=argv[0]: (self._server_note.__setitem__(l, name), self.changed.emit()))
        self._servers[lang] = client
        self._server_note[lang] = "starting " + argv[0]
        return client

    def _lsp_open(self, d: Doc) -> None:
        if d.binary:
            return
        c = self._client_for(d)
        if c:
            c.notify("textDocument/didOpen", {"textDocument": {"uri": d.uri, "languageId": LANGS[d.lang][4], "version": d.version, "text": d.text}})

    def _lsp_close(self, d: Doc) -> None:
        c = self._client_for(d, start=False)
        if c:
            c.notify("textDocument/didClose", {"textDocument": {"uri": d.uri}})

    def _push_changes(self) -> None:
        for i in sorted(getattr(self, "_pending", set())):
            if 0 <= i < len(self._docs):
                d = self._docs[i]
                c = self._client_for(d, start=False)
                if c:
                    c.notify("textDocument/didChange", {"textDocument": {"uri": d.uri, "version": d.version}, "contentChanges": [{"text": d.text}]})
                else:
                    self._lint_python(d)
        self._pending = set()

    def _lint_python(self, d: Doc) -> None:
        """Without a language server, Python still gets its syntax checked as you type; JSON its validity."""
        if self._servers.get(d.lang):
            return
        before = d.problems
        if d.lang == "Python":
            try:
                compile(d.text, d.path, "exec", dont_inherit=True)
                d.problems = []
            except SyntaxError as e:
                d.problems = [{"line": max(0, (e.lineno or 1) - 1), "col": max(0, (e.offset or 1) - 1), "endLine": max(0, (e.lineno or 1) - 1), "endCol": max(0, (e.offset or 1)),
                               "severity": 1, "message": e.msg, "source": "python"}]
            except (ValueError, RecursionError):
                pass
        elif d.lang == "JSON" and d.path.endswith(".json"):
            try:
                json.loads(d.text or "null")
                d.problems = []
            except ValueError as e:
                d.problems = [{"line": getattr(e, "lineno", 1) - 1, "col": getattr(e, "colno", 1) - 1, "endLine": getattr(e, "lineno", 1) - 1, "endCol": getattr(e, "colno", 1),
                               "severity": 1, "message": getattr(e, "msg", str(e)), "source": "json"}]
        if d.problems != before:
            self.changed.emit()

    def _got_diagnostics(self, uri: str, items: list) -> None:
        for d in self._docs:
            if d.uri == uri:
                d.problems = items
                self.changed.emit()
                return

    @Slot(int, int, int)
    def complete(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            self.completions.emit(i, self._word_completions(d, line, col))
            return
        self._push_changes()

        def got(result, error):
            items = result.get("items", []) if isinstance(result, dict) else (result or [])
            out = []
            for it in items[:200]:
                edit = it.get("textEdit") or {}
                out.append({"label": it.get("label", ""), "insert": edit.get("newText") or it.get("insertText") or it.get("label", ""),
                            "detail": (it.get("detail") or "")[:80], "kind": it.get("kind", 1), "sort": it.get("sortText") or it.get("label", "")})
            out.sort(key=lambda x: x["sort"])
            self.completions.emit(i, out or self._word_completions(d, line, col))
        c.request("textDocument/completion", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    def _word_completions(self, d: Doc, line: int, col: int) -> list:
        """Without a language server: the words already in the file that start like this one."""
        lines = d.text.split("\n")
        here = lines[line][:col] if line < len(lines) else ""
        m = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", here)
        prefix = m.group() if m else ""
        if len(prefix) < 2:
            return []
        words = sorted({w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", d.text) if w.startswith(prefix) and w != prefix} | {w for w in LANGS.get(d.lang, LANGS["Text"])[3].split() if w.startswith(prefix) and w != prefix})
        return [{"label": w, "insert": w, "detail": "", "kind": 1, "sort": w} for w in words[:60]]

    @Slot(int, int, int)
    def definition(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            self._guess_definition(d, line, col)
            return
        self._push_changes()

        def got(result, error):
            loc = result[0] if isinstance(result, list) and result else result
            if not loc:
                self._guess_definition(d, line, col)
                return
            uri = loc.get("uri") or loc.get("targetUri")
            rng = loc.get("range") or loc.get("targetSelectionRange") or {}
            start = rng.get("start", {})
            path = QUrl(uri).toLocalFile()
            if path:
                self.openFile(path, True, start.get("line", 0), start.get("character", 0))
        c.request("textDocument/definition", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    def _guess_definition(self, d: Doc, line: int, col: int) -> None:
        lines = d.text.split("\n")
        if line >= len(lines):
            return
        text = lines[line]
        m = next((m for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text) if m.start() <= col <= m.end()), None)
        if not m:
            return
        name = m.group()
        pat = re.compile(rf"^\s*(?:async\s+)?(?:def|class|function|func|fn|struct|enum|interface|type|const|let|var)\s+{re.escape(name)}\b")
        for n, l in enumerate(lines):
            if pat.match(l):
                self.jump.emit(self._docs.index(d), n, l.find(name))
                return
        self.said.emit(f"Couldn't find where “{name}” is made.", True)

    @Slot(int, int, int)
    def hover(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            return

        def got(result, error):
            if not result:
                return
            contents = result.get("contents")
            if isinstance(contents, dict):
                text = contents.get("value", "")
            elif isinstance(contents, list):
                text = "\n\n".join(x.get("value", "") if isinstance(x, dict) else str(x) for x in contents)
            else:
                text = str(contents or "")
            if text.strip():
                self.hoverText.emit(i, text.strip()[:3000])
        c.request("textDocument/hover", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    @Slot(int)
    def format(self, i: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c or not c.caps.get("documentFormattingProvider"):
            self.said.emit("No formatter for this kind of file.", True)
            return
        self._push_changes()

        def got(result, error):
            if not result:
                self.said.emit("Already tidy.", False)
                return
            lines = d.text.split("\n")
            offsets = [0]
            for l in lines:
                offsets.append(offsets[-1] + len(l) + 1)

            def at(p):
                return offsets[min(p["line"], len(lines))] + p["character"]
            text = d.text
            for e in sorted(result, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
                text = text[:at(e["range"]["start"])] + e["newText"] + text[at(e["range"]["end"]):]
            d.text = text
            self.textLoaded.emit(self._docs.index(d))
            self.changed.emit()
        c.request("textDocument/formatting", {"textDocument": {"uri": d.uri}, "options": {"tabSize": len(indent_of(d.text).replace("\t", "    ")), "insertSpaces": indent_of(d.text) != "\t"}}, got)



    # ---------------------------------------------------------------- blame and history
    @Slot(int, result="QVariantList")
    def blame(self, i: int) -> list:
        """Who last changed each line of a file, and when: [{sha, short, author, when, summary, first}] a line; lines
        not committed yet say so. `first` marks where a run of lines from one commit starts."""
        if not (0 <= i < len(self._docs)) or not self._root or not self._git:
            return []
        d = self._docs[i]
        try:
            r = subprocess.run(["git", "-C", str(self._root), "blame", "--porcelain", "--contents", "-", "--", str(Path(d.path).relative_to(self._root))],
                               input=d.text, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        if r.returncode != 0:
            return []
        out, prev = [], None
        now = time.time()
        for b in parse_blame(r.stdout):
            mine = b["sha"].startswith("0000000")
            out.append({"sha": "" if mine else b["sha"], "short": "" if mine else b["sha"][:7], "author": "You" if mine else b["author"],
                        "when": "not committed" if mine else ago(b["time"], now), "summary": "" if mine else b["summary"], "first": b["sha"] != prev})
            prev = b["sha"]
        return out

    @Slot(str, result="QVariantList")
    def history(self, rel: str) -> list:
        """The project's commits (or one file's, following renames), newest first, with a lane graph to draw."""
        if not self._root or not self._git:
            return []
        args = ["log", "--format=%H%x1f%h%x1f%an%x1f%at%x1f%s%x1f%P%x1f%D", "-n", "300"]
        args += (["--follow", "--", rel] if rel else ["--all", "--date-order"])
        try:
            out = git(self._root, *args, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        now = time.time()
        rows = lane_graph(parse_log(out)) if not rel else [dict(c, lane=0, width=1, down=[[0, 0]]) for c in parse_log(out)]
        for c in rows:
            c["when"] = ago(c["time"], now)
        return rows

    @Slot(str, str, result="QVariantList")
    def commitRows(self, sha: str, rel: str) -> list:
        if not self._root or not re.fullmatch(r"[0-9a-f]{4,40}", sha or ""):
            return []
        try:
            out = git(self._root, "show", "--format=", "--no-color", "--no-ext-diff", "-U3", sha, *(["--", rel] if rel else []), timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return show_rows(out)

    @Slot(str, result="QVariantMap")
    def commitInfo(self, sha: str) -> dict:
        if not self._root or not re.fullmatch(r"[0-9a-f]{4,40}", sha or ""):
            return {}
        try:
            out = git(self._root, "show", "-s", "--format=%H%x1f%an%x1f%ae%x1f%at%x1f%B", sha, timeout=10).stdout
            stat = git(self._root, "show", "--format=", "--numstat", sha, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        f = out.split("\x1f")
        if len(f) < 5:
            return {}
        files = []
        for line in stat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                files.append({"path": parts[2], "added": parts[0], "removed": parts[1]})
        return {"sha": f[0], "author": f[1], "email": f[2], "when": time.strftime("%-d %b %Y, %H:%M", time.localtime(int(f[3] or 0))), "message": f[4].strip(), "files": files}

    # ---------------------------------------------------------------- tests
    testsChanged = Signal()

    def _tests_init(self) -> None:
        if not hasattr(self, "_tests"):
            self._tests, self._test_status, self._test_kind, self._test_busy, self._test_out, self._test_proc = [], {}, "", "", "", None

    @Slot()
    def discoverTests(self) -> None:
        """Find the project's tests (pytest, cargo test, go test) in the background."""
        self._tests_init()
        root = self._root
        kind = test_framework(root)
        self._test_kind = kind
        if not kind:
            self._tests = []
            self.testsChanged.emit()
            return
        self._test_busy = "Looking for tests…"
        self.testsChanged.emit()

        def work():
            found = []
            try:
                if kind == "pytest":
                    r = subprocess.run([sys.executable if self._python_has_pytest() else "python3", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                                       cwd=str(root), capture_output=True, text=True, timeout=120)
                    found = parse_pytest_collect(r.stdout, root)
                elif kind == "cargo":
                    r = subprocess.run(["cargo", "test", "--", "--list", "--format", "terse"], cwd=str(root), capture_output=True, text=True, timeout=600)
                    for line in r.stdout.splitlines():
                        if line.endswith(": test"):
                            name = line[:-6]
                            found.append({"id": name, "name": name.split("::")[-1], "file": "", "line": 0, "group": "::".join(name.split("::")[:-1]) or "crate"})
                elif kind == "go":
                    r = subprocess.run(["go", "test", "-list", ".", "./..."], cwd=str(root), capture_output=True, text=True, timeout=600)
                    pkg = ""
                    for line in r.stdout.splitlines():
                        if line.startswith(("ok ", "?   ")):
                            continue
                        if re.fullmatch(r"(Test|Example|Benchmark)\w*", line.strip()):
                            found.append({"id": line.strip(), "name": line.strip(), "file": "", "line": 0, "group": pkg or "package"})
            except (OSError, subprocess.SubprocessError):
                found = []
            self._back.emit(lambda: self._found_tests(found))
        threading.Thread(target=work, daemon=True).start()

    def _python_has_pytest(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("pytest") is not None

    def _found_tests(self, found: list) -> None:
        self._tests, self._test_busy = found, ""
        if self._root and self._test_kind != "pytest":
            for t in self._tests:                             # where each one is, for Rust and Go
                for f in list(self._root.rglob("*.rs" if self._test_kind == "cargo" else "*_test.go"))[:400]:
                    ln = test_line(self._root, str(f.relative_to(self._root)), t["name"])
                    if ln or re.search(rf"\b(fn|func)\s+{re.escape(t['name'])}\b", _read(f)):
                        t["file"], t["line"] = str(f.relative_to(self._root)), ln
                        if self._test_kind == "go":
                            t["group"] = str(f.relative_to(self._root))
                        break
        self.testsChanged.emit()

    @Slot("QVariantList")
    def runTests(self, ids) -> None:
        """Run some tests (or all, with an empty list); results come in when they're done."""
        self._tests_init()
        ids = ids.toVariant() if hasattr(ids, "toVariant") else list(ids)
        if self._test_busy or not self._test_kind or not self._root:
            return
        self.saveAll()
        kind, root = self._test_kind, self._root
        report = Path(tempfile.gettempdir()) / f"huginn-code-tests-{os.getpid()}.xml"
        if kind == "pytest":
            argv = [sys.executable if self._python_has_pytest() else "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"] + list(ids)
        elif kind == "cargo":
            argv = ["cargo", "test"] + ([ids[0], "--", "--exact"] if len(ids) == 1 else ["--"]) + ["--test-threads=1"]
        else:
            argv = ["go", "test", "-v", "./..."] + (["-run", "^(" + "|".join(re.escape(i) for i in ids) + ")$"] if ids else [])
        for t in self._tests:
            if not ids or t["id"] in ids:
                self._test_status[t["id"]] = {"status": "running", "message": "", "seconds": 0}
        self._test_busy, self._test_out = "Running tests…", ""
        self.testsChanged.emit()
        proc = QProcess(self)
        proc.setWorkingDirectory(str(root))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._test_proc = proc

        def read():
            self._test_out = (self._test_out + bytes(proc.readAll()).decode(errors="replace"))[-60000:]

        def done(code, _st):
            read()
            if kind == "pytest":
                res = parse_junit(_read(report))
                for t in self._tests:
                    if not ids or t["id"] in ids:
                        self._test_status[t["id"]] = junit_for(res, t["id"]) or {"status": "failed" if code else "passed", "message": "", "seconds": 0}
                report.unlink(missing_ok=True)
            else:
                res = parse_cargo(self._test_out) if kind == "cargo" else parse_go(self._test_out)
                for t in self._tests:
                    if not ids or t["id"] in ids:
                        self._test_status[t["id"]] = res.get(t["id"]) or {"status": "skipped", "message": "", "seconds": 0}
            self._test_busy, self._test_proc = "", None
            failed = sum(1 for v in self._test_status.values() if v.get("status") == "failed")
            passed = sum(1 for v in self._test_status.values() if v.get("status") == "passed")
            self.said.emit(f"{passed} passed" + (f", {failed} failed" if failed else ""), bool(failed))
            self.testsChanged.emit()
        proc.readyRead.connect(read)
        proc.finished.connect(done)
        proc.start(argv[0], argv[1:])

    @Slot()
    def stopTests(self) -> None:
        if getattr(self, "_test_proc", None) is not None:
            self._test_proc.kill()

    def _tests_view(self) -> list:
        self._tests_init()
        return [dict(t, **self._test_status.get(t["id"], {"status": "", "message": "", "seconds": 0})) for t in self._tests]

    tests = Property("QVariantList", _tests_view, notify=testsChanged)
    testKind = Property(str, lambda self: getattr(self, "_test_kind", ""), notify=testsChanged)
    testBusy = Property(str, lambda self: getattr(self, "_test_busy", ""), notify=testsChanged)
    testOutput = Property(str, lambda self: getattr(self, "_test_out", ""), notify=testsChanged)

    @Slot(str)
    def openTest(self, tid: str) -> None:
        t = next((x for x in getattr(self, "_tests", []) if x["id"] == tid), None)
        if t and t.get("file"):
            self.openRel(t["file"], int(t.get("line", 0)), 0)

    # ---------------------------------------------------------------- rename and references
    def _word_at(self, d: Doc, line: int, col: int) -> str:
        lines = d.text.split("\n")
        if line >= len(lines):
            return ""
        m = next((m for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", lines[line]) if m.start() <= col <= m.end()), None)
        return m.group() if m else ""

    @Slot(int, int, int, result=str)
    def wordAt(self, i: int, line: int, col: int) -> str:
        return self._word_at(self._docs[i], line, col) if 0 <= i < len(self._docs) else ""

    @Slot(int, int, int)
    def references(self, i: int, line: int, col: int) -> None:
        """Shift+F12: every place the name under the cursor is used, in the Search panel."""
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        name = self._word_at(d, line, col)
        if not name:
            return
        c = self._client_for(d, start=False)

        def by_words():
            # open files as they are in their tabs (maybe unsaved), the rest of the project as it is on disk
            opened = {x.path for x in self._docs}
            rest = [h for h in (search_files(self._root, name, True, False, True) if self._root else []) if str(self._root / h["path"]) not in opened]
            hits = []
            for x in sorted(self._docs, key=lambda x: x.path != d.path):
                if x.binary or (self._root and not x.path.startswith(str(self._root)) and x is not d):
                    continue
                hits += [{"path": x.path, "line": n, "col": m.start(), "length": len(name), "text": l[:400]} for n, l in enumerate(x.text.split("\n"))
                         for m in re.finditer(rf"\b{re.escape(name)}\b", l)]
            self._show_refs(name, hits + rest, exact=False)
        if c and not c.up:                                         # still starting: ask once it's ready
            self._once_ready(c, lambda: self.references(i, line, col), by_words)
            return
        if not c or not c.caps.get("referencesProvider"):
            by_words()
            return
        self._push_changes()

        def got(result, error):
            if error or not result:
                by_words()
                return
            hits, texts = [], {}
            for loc in result:
                path = QUrl(loc.get("uri", "")).toLocalFile()
                start = (loc.get("range") or {}).get("start", {})
                ln, col0 = start.get("line", 0), start.get("character", 0)
                if path not in texts:
                    doc = next((x for x in self._docs if x.path == path), None)
                    try:
                        texts[path] = (doc.text if doc else Path(path).read_text(encoding="utf-8", errors="replace")).split("\n")
                    except OSError:
                        texts[path] = []
                lines = texts[path]
                hits.append({"path": path, "line": ln, "col": col0, "length": len(name), "text": lines[ln][:400] if ln < len(lines) else ""})
            self._show_refs(name, sorted(hits, key=lambda h: (h["path"] != d.path, h["path"], h["line"])), exact=True)
        c.request("textDocument/references", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}, "context": {"includeDeclaration": True}}, got)

    def _show_refs(self, name: str, hits: list, exact: bool) -> None:
        if self._root:                                       # shown like search results: paths inside the project are short
            for h in hits:
                try:
                    h["path"] = str(Path(h["path"]).relative_to(self._root)) if Path(h["path"]).is_absolute() else h["path"]
                except ValueError:
                    pass
        self._results, self._searching = hits, False
        n = len(hits)
        self._results_title = f"{n} reference{'' if n == 1 else 's'} to “{name}”" + ("" if exact else " (by name)")
        self.searchDone.emit()

    @Slot(int, int, int, str)
    def renameSymbol(self, i: int, line: int, col: int, new: str) -> None:
        """F2: rename the thing under the cursor everywhere it's used (the language server knows where; without one,
        whole words in this file)."""
        new = new.strip()
        if not 0 <= i < len(self._docs) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new):
            self.said.emit("A name is letters, numbers and _, not starting with a number.", True)
            return
        d = self._docs[i]
        old = self._word_at(d, line, col)
        if not old or old == new:
            return
        c = self._client_for(d, start=False)

        def in_this_file():
            text, n = re.subn(rf"\b{re.escape(old)}\b", new, d.text)
            d.text = text
            d.version += 1
            self.textLoaded.emit(i)
            self.changed.emit()
            self.said.emit(f"Renamed {n} use{'s' if n != 1 else ''} in this file (no language helper to look further).", False)
        if c and not c.up:
            self._once_ready(c, lambda: self.renameSymbol(i, line, col, new), in_this_file)
            return
        if not c or not c.caps.get("renameProvider"):
            in_this_file()
            return
        self._push_changes()

        def got(result, error):
            if error or not result:
                if error:
                    self.said.emit(f"Couldn't rename: {str(error)[:160]}", True)
                    return
                in_this_file()
                return
            edits = {}
            for change in result.get("documentChanges") or []:
                if "textDocument" in change:
                    edits.setdefault(QUrl(change["textDocument"]["uri"]).toLocalFile(), []).extend(change.get("edits", []))
            for uri, es in (result.get("changes") or {}).items():
                edits.setdefault(QUrl(uri).toLocalFile(), []).extend(es)
            done = self.apply_edits(edits)
            self.said.emit(f"Renamed “{old}” to “{new}” in {done} file{'s' if done != 1 else ''}. Open files are changed but not saved.", False)
        c.request("textDocument/rename", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}, "newName": new}, got)

    def _once_ready(self, client, then, otherwise, wait: int = 8000) -> None:
        """Run `then` when a starting language server is ready, or `otherwise` if it takes too long."""
        done = []

        def go(fn):
            if done:
                return
            done.append(1)
            try:
                client.ready.disconnect(on_ready)
            except (RuntimeError, TypeError):
                pass
            fn()

        def on_ready():
            go(then)
        client.ready.connect(on_ready)
        QTimer.singleShot(wait, lambda: go(otherwise))

    def apply_edits(self, edits: dict) -> int:
        """LSP text edits per file: open files change in their tabs (unsaved); other files are rewritten on disk."""
        done = 0
        for path, es in edits.items():
            doc = next((x for x in self._docs if x.path == path), None)
            try:
                text = doc.text if doc else Path(path).read_text(encoding="utf-8")
            except OSError:
                continue
            lines = text.split("\n")
            offsets = [0]
            for l in lines:
                offsets.append(offsets[-1] + len(l) + 1)

            def at(p):
                return offsets[min(p["line"], len(lines))] + p["character"]
            for e in sorted(es, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
                text = text[:at(e["range"]["start"])] + e["newText"] + text[at(e["range"]["end"]):]
            if doc:
                doc.text = text
                doc.version += 1
                self.textLoaded.emit(self._docs.index(doc))
            else:
                try:
                    Path(path).write_text(text, encoding="utf-8")
                except OSError:
                    continue
            done += 1
        self.changed.emit()
        return done

    # ---------------------------------------------------------------- the minimap
    @Slot(bool)
    def setMinimap(self, on: bool) -> None:
        self._minimap = bool(on)
        self._keep()
        self.changed.emit()

    # ---------------------------------------------------------------- debugging
    def _dbg_changed(self) -> None:
        pass

    def _landed(self, path: str, line: int) -> None:
        """The program stopped here: show the file at that line."""
        if not path or not Path(path).exists():
            return
        i = next((k for k, d in enumerate(self._docs) if d.path == path), -1)
        if i < 0:
            self.openFile(path, True, line, 0)
        else:
            self.select(i)
            self.jump.emit(i, line, 0)

    @Slot(int, int)
    def toggleBreakpoint(self, i: int, line: int) -> None:
        if 0 <= i < len(self._docs) and self._docs[i].path:
            self._dbg.toggle(self._docs[i].path, line)
            self._keep()
            self.changed.emit()

    @Slot(int, result="QVariantList")
    def breakpointsOf(self, i: int) -> list:
        return self._dbg.lines_for(self._docs[i].path) if 0 <= i < len(self._docs) else []

    @Slot(str)
    def startDebug(self, program: str = "") -> None:
        """F5: run the current file (or the project's program) under the debugger. Asks for the program once for
        compiled languages (Code guesses the newest one in the build folders)."""
        if self._dbg.active:
            self._dbg.resume()
            return
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        if d is None:
            self.said.emit("Open the file to debug first.", True)
            return
        self.saveAll()
        root = self._root or Path(d.path).parent
        if program:
            try:
                (root / ".huginn-debug").write_text(program + "\n", encoding="utf-8")
            except OSError:
                pass
        program = program or hd.saved_program(root)
        try:
            argv, launch, name = hd.adapter_for(d.lang, d.path, root, program)
        except LookupError:
            self.askProgram.emit(hd.guess_program(root))
            return
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if self._demo:
            self.said.emit(f"Would debug {Path(d.path).name} with {name}.", False)
            return
        self._dbg.start(argv, launch, name, str(root))

    askProgram = Signal(str)

    # ---------------------------------------------------------------- one Code at a time
    def listen(self, path: str = "") -> bool:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = f"huginn-code-{os.getuid()}"
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            probe.write(("open\n" + (str(Path(path).expanduser().resolve()) if path else "")).encode("utf-8"))
            probe.waitForBytesWritten(1000)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(name)
        self._door = QLocalServer(self)
        self._door.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._door.listen(name)

        def came():
            sock = self._door.nextPendingConnection()

            def read():
                msg = bytes(sock.readAll()).decode("utf-8", "replace")
                target = msg.split("\n", 1)[1].strip() if "\n" in msg else ""
                if target:
                    if Path(target).is_dir():
                        self.openFolder(target)
                    else:
                        self.openFile(target)
                self.shown.emit()
            sock.readyRead.connect(read)
        self._door.newConnection.connect(came)
        return True

    def leaving(self) -> None:
        self._dbg.stop(quiet=True)
        self._keep()
        for s in self._servers.values():
            if s:
                s.stop()
        if self._term is not None:
            self._term.stop()


class MinimapProvider(QQuickImageProvider):
    """image://minimap/<tab>/<version>: the whole file drawn small, a line every two pixels, words as little bars,
    comments and strings in their own colours: for seeing where you are in a long file."""

    def __init__(self, code: "Code"):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.code = code

    def requestImage(self, ident, size, requested):
        try:
            i = int(ident.split("/")[0])
            d = self.code._docs[i]
        except (ValueError, IndexError):
            return QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        lines = d.text.split("\n")[:6000]
        w, step = 120, 2
        img = QImage(w, max(2, len(lines) * step), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        info = LANGS.get(d.lang)
        comment = info[1] if info else ""
        plain, faint, green, orange = QColor(170, 176, 190, 150), QColor(170, 176, 190, 90), QColor(110, 190, 120, 170), QColor(230, 160, 90, 170)
        p = QPainter(img)
        for n, line in enumerate(lines):
            text = line.expandtabs(4)
            stripped = text.lstrip()
            if not stripped:
                continue
            ink = green if comment and stripped.startswith(comment) else plain
            x = len(text) - len(stripped)
            for m in re.finditer(r"\S+", text[:w]):
                word = m.group()
                c = orange if word[:1] in "\"'`" else ink if ink is green or not word[:1].isalpha() or len(word) > 2 else faint
                p.fillRect(m.start(), n * step, len(word), step - 1 if step > 1 else 1, c)
            del x
        p.end()
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img
