"""Huginn Office: the engines behind Writer, Sheets and Slides.

Each app keeps its work in an open, readable format (Writer: HTML, Sheets: JSON, Slides: JSON) and can export to
PDF and to the usual open formats.

Files from other suites (hybrid): .docx, .xlsx and .pptx are read and written by Huginn's own converters
(huginn_convert.py). Older or rarer formats (.doc, .odt, .rtf, .xls, .ods, .ppt, .odp) are first turned into the
modern format by LibreOffice running invisibly, if it is installed, and then read by the same converters. Either way
the file opens here, as a copy, and the app says what could not be carried over. LibreOffice's window never opens.
"""
import ast
import csv
import datetime as dt
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import (Property, QAbstractTableModel, QMarginsF, QModelIndex, QObject, QSizeF, QStandardPaths,
                            Qt, QTimer, QUrl, Signal, Slot)
import huginn_convert as convert
from PySide6.QtGui import (QDesktopServices, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocumentWriter, QTextListFormat)


def documents_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".saving")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def fresh_path(folder: Path, stem: str, ext: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}{ext}", 1
    while path.exists():
        n += 1
        path = folder / f"{stem} {n}{ext}"
    return path


def when(path: Path) -> str:
    stamp = dt.datetime.fromtimestamp(path.stat().st_mtime)
    return stamp.strftime("%H:%M") if stamp.date() == dt.date.today() else stamp.strftime("%b ") + str(stamp.day)



def note_recent(path: str) -> None:
    """Into the desktop's shared recent list (the start menu's app islands and Search everything read it)."""
    try:
        import huginn_recent
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.desktopFileName() or "huginn-writer"
        huginn_recent.note(path, app, f"python3 /usr/share/huginn-apps/huginn_app.py {app.replace('huginn-', '')} %u")
    except Exception:                                      # noqa: BLE001  (never in the way of opening the file)
        pass


class Bridge:
    """LibreOffice as a file converter, run headless. Present only when `soffice` is installed."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")

    @classmethod
    def available(cls) -> bool:
        return bool(cls.exe)

    @classmethod
    def convert(cls, source: Path, target_format: str, out_dir: Path = None) -> Path:
        """Convert `source` to e.g. 'html', 'docx', 'csv', 'xlsx'. Returns the new file. Raises OSError on failure."""
        if not cls.exe:
            raise OSError("LibreOffice isn't installed, so this kind of file can't be converted.")
        out_dir = out_dir or Path(tempfile.mkdtemp(prefix="huginn-office-"))
        profile = Path(tempfile.mkdtemp(prefix="huginn-lo-profile-"))        # a private profile: never touches the user's
        try:
            done = subprocess.run([cls.exe, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                                   "--convert-to", target_format, "--outdir", str(out_dir), str(source)],
                                  capture_output=True, text=True, timeout=120)
        except subprocess.SubprocessError as err:
            raise OSError(f"The conversion didn't finish: {err}")
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        result = out_dir / (source.stem + "." + target_format.split(":")[0])
        if done.returncode != 0 or not result.is_file():
            raise OSError("LibreOffice couldn't convert this file.")
        return result


class FileList(QObject):
    """Shared by the three apps: the documents of one kind in the Documents folder, newest first."""
    changed = Signal()
    failed = Signal(str)
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (), (), (), "", "Untitled"
    imported = Signal(str, "QVariantList")       # original file name, what could not be carried over
    noteChanged = Signal()

    def __init__(self, target: Path = None):
        super().__init__()
        self._folder, self._path, self._dirty = documents_dir(), None, False
        self._saver = QTimer(self)
        self._saver.setSingleShot(True)
        self._saver.setInterval(800)
        self._saver.timeout.connect(self.save)
        self._extra = target if target and target.is_file() else None
        self._note_file, self._note_dropped = "", []
        self.imported.connect(self._remember)

    def _remember(self, name: str, dropped: list) -> None:
        self._note_file, self._note_dropped = name, list(dropped)
        self.noteChanged.emit()

    importedFile = Property(str, lambda self: self._note_file, notify=noteChanged)
    importedDropped = Property("QVariantList", lambda self: self._note_dropped, notify=noteChanged)

    @Slot()
    def dismissNote(self) -> None:
        self._remember("", [])

    def _kinds(self) -> tuple:
        return self.NATIVE + self.OWN + (self.VIA_BRIDGE if Bridge.available() else ())

    @property
    def FOREIGN(self) -> tuple:
        return self.OWN + self.VIA_BRIDGE

    def _modern(self, source: Path) -> Path:
        """The file in the modern format our converters read; older formats pass through LibreOffice first."""
        if source.suffix.lower() in self.OWN:
            return source
        return Bridge.convert(source, self.MODERN)

    @Property("QVariantList", notify=changed)
    def files(self):
        rows = [p for p in self._folder.iterdir() if p.is_file() and p.suffix.lower() in self._kinds()] if self._folder.is_dir() else []
        if self._extra and self._extra not in rows:
            rows.append(self._extra)
        rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": str(p), "name": p.stem, "when": when(p), "foreign": p.suffix.lower() in self.FOREIGN,
                 "kind": p.suffix.lstrip(".").upper()} for p in rows[:200]]

    current = Property(str, lambda self: str(self._path) if self._path else "", notify=changed)
    title = Property(str, lambda self: self._path.stem if self._path else "", notify=changed)
    saved = Property(bool, lambda self: not self._dirty, notify=changed)
    converter = Property(bool, lambda self: Bridge.available(), constant=True)
    folder = Property(str, lambda self: str(self._folder), constant=True)

    def touch(self) -> None:
        self._dirty = True
        self._saver.start()
        self.changed.emit()

    def save(self) -> None:           # each app writes its own format
        raise NotImplementedError

    @Slot(str)
    def reveal(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


# ============================================================================================== Writer
class Writer(FileList):
    """Word processor. The live text is the QML editor's document; formatting is applied to it from here."""
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".html", ".htm", ".md", ".txt"), (".docx",), (".odt", ".rtf", ".doc"), "docx", "Untitled"
    loaded = Signal()
    STYLES = {"title": (26, QFont.Bold, 1), "heading": (18, QFont.DemiBold, 2), "subheading": (14, QFont.DemiBold, 3), "body": (11, QFont.Normal, 0)}
    BASE_CSS = "body { font-family: 'Inter', sans-serif; font-size: 11pt; color: #15181C; }"

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._doc, self._quick, self._pending, self._words = None, None, None, 0
        self.changed.connect(self.wordsChanged)
        if self._extra:
            self.open(str(self._extra))

    wordsChanged = Signal()
    words = Property(int, lambda self: self._words, notify=wordsChanged)

    # -- the editor hands over its document once, then tells us about edits
    @Slot(QObject)
    def attach(self, quick_doc) -> None:
        self._quick = quick_doc                    # keep the editor's wrapper alive: the document belongs to it
        self._doc = quick_doc.textDocument()
        self._doc.setDefaultStyleSheet(self.BASE_CSS)
        font = QFont("Inter")
        font.setPointSizeF(11)
        self._doc.setDefaultFont(font)
        if self._pending is not None:
            self._fill(*self._pending)
            self._pending = None
        self._doc.contentsChanged.connect(self._edited)

    def _edited(self) -> None:
        self._words = len(self._doc.toPlainText().split())
        if self._path is not None and not self._loading:
            self.touch()
        else:
            self.changed.emit()

    _loading = False

    def _fill(self, kind: str, text: str) -> None:
        self._loading = True
        if kind == "md":
            self._doc.setMarkdown(text)
        elif kind == "txt":
            self._doc.setPlainText(text)
        else:
            self._doc.setHtml(text)
        self._doc.setModified(False)
        self._doc.clearUndoRedoStacks()
        self._loading = False
        self._words = len(self._doc.toPlainText().split())
        self.loaded.emit()
        self.changed.emit()

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source = Path(path)
        try:
            kind = source.suffix.lower()
            dropped = None
            if kind in self.FOREIGN:
                text, dropped = convert.docx_to_html(self._modern(source))
                kind, target = "html", fresh_path(source.parent, source.stem, ".html")    # edits go to a copy; the original is untouched
            else:
                text, target = source.read_text(encoding="utf-8", errors="replace"), source
                kind = "md" if kind == ".md" else "txt" if kind == ".txt" else "html"
        except (OSError, convert.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self._path, self._dirty = target, False
        if self._doc is None:
            self._pending = (kind, text)
        else:
            self._fill(kind, text)
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".html")
            path.write_text("", encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a document: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None or self._doc is None:
            return
        try:
            kind = self._path.suffix.lower()
            text = self._doc.toMarkdown() if kind == ".md" else self._doc.toPlainText() if kind == ".txt" else self._doc.toHtml()
            write_atomic(self._path, text)
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    # -- formatting
    def _cursor(self, start: int, end: int) -> QTextCursor:
        cursor = QTextCursor(self._doc)
        cursor.setPosition(max(0, min(start, self._doc.characterCount() - 1)))
        cursor.setPosition(max(0, min(end, self._doc.characterCount() - 1)), QTextCursor.KeepAnchor)
        return cursor

    # -- for Huginn AI: the text of a stretch (or all of it), and putting text in its place
    @Slot(int, int, result=str)
    def textOf(self, start: int, end: int) -> str:
        if self._doc is None:
            return ""
        if start == end:
            return self._doc.toPlainText()
        return self._cursor(start, end).selectedText().replace("\u2029", "\n").replace("\u2028", "\n")

    @Slot(int, int, str, result=int)
    def putText(self, start: int, end: int, text: str) -> int:
        """Replace a stretch (start == end: insert there) with text, keeping the formatting where it goes; one undo.
        Returns where the new text ends."""
        if self._doc is None:
            return start
        cursor = self._cursor(start, end)
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()
        return cursor.position()

    @Slot(int, int, str)
    def style(self, start: int, end: int, what: str) -> None:
        if self._doc is None:
            return
        cursor = self._cursor(start, end)
        cursor.beginEditBlock()
        now = cursor.charFormat()
        fmt = QTextCharFormat()
        if what == "bold":
            fmt.setFontWeight(QFont.Normal if now.fontWeight() >= QFont.DemiBold else QFont.Bold)
        elif what == "italic":
            fmt.setFontItalic(not now.fontItalic())
        elif what == "underline":
            fmt.setFontUnderline(not now.fontUnderline())
        elif what in ("bigger", "smaller"):
            size = now.fontPointSize() or 11
            fmt.setFontPointSize(max(7, min(96, size + (1 if what == "bigger" else -1))))
        elif what.startswith("#"):
            fmt.setForeground(Qt.GlobalColor.black)
            from PySide6.QtGui import QColor
            fmt.setForeground(QColor(what))
        elif what in ("left", "center", "right", "justify"):
            block = QTextBlockFormat()
            block.setAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}[what])
            cursor.mergeBlockFormat(block)
        elif what in self.STYLES:
            size, weight, level = self.STYLES[what]
            cursor.select(QTextCursor.BlockUnderCursor) if not cursor.hasSelection() else None
            block = QTextBlockFormat()
            block.setHeadingLevel(level)
            block.setTopMargin(14 if level else 0)
            block.setBottomMargin(6 if level else 4)
            cursor.mergeBlockFormat(block)
            fmt.setFontPointSize(size)
            fmt.setFontWeight(weight)
            cursor.mergeBlockCharFormat(fmt)
        elif what in ("bullet", "number"):
            current = cursor.currentList()
            wanted = QTextListFormat.ListDisc if what == "bullet" else QTextListFormat.ListDecimal
            if current is not None and current.format().style() == wanted:
                block = cursor.blockFormat()
                block.setObjectIndex(-1)
                block.setIndent(0)
                cursor.setBlockFormat(block)                # same button again: take the paragraphs out of the list
            else:
                cursor.createList(wanted)
        if fmt.propertyCount():
            if not cursor.hasSelection():
                cursor.select(QTextCursor.WordUnderCursor)
            cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()

    @Slot(int, result="QVariantMap")
    def state(self, position: int) -> dict:
        if self._doc is None:
            return {}
        cursor = self._cursor(position, position)
        char, block = cursor.charFormat(), cursor.blockFormat()
        level = block.headingLevel()
        align = block.alignment()
        lst = cursor.currentList()
        return {"bold": char.fontWeight() >= QFont.DemiBold, "italic": char.fontItalic(), "underline": char.fontUnderline(),
                "style": {1: "title", 2: "heading", 3: "subheading"}.get(level, "body"),
                "align": "center" if align & Qt.AlignHCenter else "right" if align & Qt.AlignRight else "justify" if align & Qt.AlignJustify else "left",
                "list": "" if lst is None else ("number" if lst.format().style() == QTextListFormat.ListDecimal else "bullet"),
                "size": round(char.fontPointSize() or 11)}

    def blocks(self) -> list:
        """The document as plain data (paragraphs of styled runs), which is what the Word writer takes."""
        out, block = [], self._doc.begin()
        while block.isValid():
            fmt, lst = block.blockFormat(), block.textList()
            align = fmt.alignment()
            entry = {"style": {1: "title", 2: "heading", 3: "subheading"}.get(fmt.headingLevel(), "body"),
                     "align": "center" if align & Qt.AlignHCenter else "right" if align & Qt.AlignRight else "justify" if align & Qt.AlignJustify else "left",
                     "list": "" if lst is None else ("number" if lst.format().style() == QTextListFormat.ListDecimal else "bullet"), "runs": []}
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    char = fragment.charFormat()
                    brush = char.foreground()
                    entry["runs"].append({"text": fragment.text(), "bold": char.fontWeight() >= QFont.DemiBold, "italic": char.fontItalic(),
                                          "underline": char.fontUnderline(), "size": char.fontPointSize(),
                                          "color": brush.color().name() if brush.style() != Qt.NoBrush else ""})
                it += 1
            out.append(entry)
            block = block.next()
        return out

    # -- export
    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        """kind: pdf | odt | md | docx. Writes beside the document and returns the new file's path ('' on failure)."""
        if self._doc is None or self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, "." + kind)
            if kind == "pdf":
                pdf = QPdfWriter(str(out))
                pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(22, 22, 22, 22), QPageLayout.Millimeter))
                pdf.setTitle(self._path.stem)
                copy = self._doc.clone()
                copy.print_(pdf)
            elif kind == "odt":
                writer = QTextDocumentWriter(str(out), b"odf")
                if not writer.write(self._doc):
                    raise OSError("the document couldn't be written")
            elif kind == "md":
                out.write_text(self._doc.toMarkdown(), encoding="utf-8")
            elif kind == "docx":
                convert.blocks_to_docx(self.blocks(), out)
            else:
                return ""
        except (OSError, convert.ConvertError) as err:
            self.failed.emit(f"Couldn't export: {getattr(err, 'strerror', None) or err}")
            return ""
        return str(out)


# ============================================================================================== Sheets
REF = re.compile(r"\$?([A-Za-z]{1,2})\$?([0-9]{1,4})")
ERRORS = ("#DIV/0!", "#REF!", "#NAME?", "#CYCLE!", "#VALUE!", "#ERROR!")


def col_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def parse_ref(ref: str) -> tuple:
    m = REF.fullmatch(ref.strip())
    if not m:
        raise KeyError(ref)
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)) - 1, col - 1


class SheetError(Exception):
    pass


class Engine:
    """The spreadsheet's arithmetic: raw cell text in, values out. No Qt here, so it can be tested on its own."""
    ROWS, COLS = 200, 26
    NAMES = frozenset({"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "ROUND", "ABS", "SQRT", "IF", "AND", "OR", "NOT",
                       "LEN", "UPPER", "LOWER", "CONCAT", "TODAY", "TRUE", "FALSE"})

    def __init__(self):
        self.raw = {}             # (row, col) -> text as typed
        self._cache = {}

    def set(self, row: int, col: int, text: str) -> None:
        text = text.strip()
        if text:
            self.raw[(row, col)] = text
        else:
            self.raw.pop((row, col), None)
        self._cache.clear()

    def value(self, row: int, col: int, _stack: tuple = ()):
        key = (row, col)
        if key in self._cache:
            return self._cache[key]
        if key in _stack:
            raise SheetError("#CYCLE!")
        text = self.raw.get(key, "")
        if not text:
            result = ""
        elif text.startswith("="):
            try:
                result = self._formula(text[1:], _stack + (key,))
            except SheetError as err:
                result = str(err)
            except ZeroDivisionError:
                result = "#DIV/0!"
            except (ValueError, TypeError, OverflowError):
                result = "#VALUE!"
            except RecursionError:
                result = "#CYCLE!"
        else:
            result = self._literal(text)
        if not _stack or not (isinstance(result, str) and result == "#CYCLE!"):
            self._cache[key] = result
        return result

    @staticmethod
    def _literal(text: str):
        cleaned = text.replace(",", "").strip()
        percent = cleaned.endswith("%")
        try:
            number = float(cleaned.rstrip("%"))
            return number / 100 if percent else number
        except ValueError:
            return text

    def _formula(self, source: str, stack: tuple):
        if len(source) > 500:
            raise SheetError("#ERROR!")
        expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", source)                         # 50% means 0.5
        expr = expr.replace("^", "**").replace("<>", "!=")
        expr = re.sub(r"(?<![<>!=])=(?!=)", "==", expr)                                   # a single = means "equals"
        expr = re.sub(r"\$?([A-Za-z]{1,2})\$?([0-9]{1,4})\s*:\s*\$?([A-Za-z]{1,2})\$?([0-9]{1,4})",
                      lambda m: f'RANGE_("{m.group(1)}{m.group(2)}","{m.group(3)}{m.group(4)}")', expr)
        expr = re.sub(r'(?<![A-Za-z0-9_"])\$?([A-Za-z]{1,2})\$?([0-9]{1,4})(?![A-Za-z0-9_(])', lambda m: f'CELL_("{m.group(1)}{m.group(2)}")', expr)
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            raise SheetError("#ERROR!")

        def cell(ref):
            try:
                r, c = parse_ref(ref)
            except KeyError:
                raise SheetError("#REF!")
            if not (0 <= r < self.ROWS and 0 <= c < self.COLS):
                raise SheetError("#REF!")
            v = self.value(r, c, stack)
            if isinstance(v, str) and v in ERRORS:
                raise SheetError(v)
            return v

        def span(a, b):
            try:
                (r1, c1), (r2, c2) = parse_ref(a), parse_ref(b)
            except KeyError:
                raise SheetError("#REF!")
            if max(r1, r2) >= self.ROWS or max(c1, c2) >= self.COLS:
                raise SheetError("#REF!")
            out = []
            for r in range(min(r1, r2), max(r1, r2) + 1):
                for c in range(min(c1, c2), max(c1, c2) + 1):
                    if (r, c) in self.raw:
                        out.append(cell(col_name(c) + str(r + 1)))
            return out

        def flat(args):
            for a in args:
                if isinstance(a, list):
                    yield from a
                else:
                    yield a

        def nums(args):
            return [float(v) for v in flat(args) if isinstance(v, (int, float)) and not isinstance(v, bool)]

        def num(v):
            if v == "" or v is None:
                return 0.0
            if isinstance(v, (int, float)):
                return float(v)
            raise SheetError("#VALUE!")

        funcs = {
            "SUM": lambda *a: math.fsum(nums(a)), "AVERAGE": lambda *a: (math.fsum(nums(a)) / len(nums(a))) if nums(a) else (_ for _ in ()).throw(ZeroDivisionError()),
            "MIN": lambda *a: min(nums(a)) if nums(a) else 0.0, "MAX": lambda *a: max(nums(a)) if nums(a) else 0.0,
            "COUNT": lambda *a: float(len(nums(a))), "COUNTA": lambda *a: float(sum(1 for v in flat(a) if v != "")),
            "ROUND": lambda v, d=0: round(num(v) + 0.0, int(num(d))), "ABS": lambda v: abs(num(v)), "SQRT": lambda v: math.sqrt(num(v)),
            "IF": lambda c, a, b="": a if c else b, "AND": lambda *a: all(flat(a)), "OR": lambda *a: any(flat(a)), "NOT": lambda v: not v,
            "LEN": lambda v: float(len(str(v))), "UPPER": lambda v: str(v).upper(), "LOWER": lambda v: str(v).lower(),
            "CONCAT": lambda *a: "".join(Engine.show(v) for v in flat(a)), "TODAY": lambda: dt.date.today().isoformat(),
            "TRUE": lambda: True, "FALSE": lambda: False,
            "CELL_": cell, "RANGE_": span,
        }
        ops = {ast.Add: lambda a, b: num(a) + num(b), ast.Sub: lambda a, b: num(a) - num(b), ast.Mult: lambda a, b: num(a) * num(b),
               ast.Div: lambda a, b: num(a) / num(b), ast.Pow: lambda a, b: num(a) ** num(b), ast.Mod: lambda a, b: num(a) % num(b)}
        cmps = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
                ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b}

        def walk(node):
            if isinstance(node, ast.Expression):
                return walk(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
                return float(node.value) if isinstance(node.value, (int, float)) and not isinstance(node.value, bool) else node.value
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)) and abs(node.right.value) > 512:
                    raise SheetError("#VALUE!")
                return ops[type(node.op)](walk(node.left), walk(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                return -num(walk(node.operand)) if isinstance(node.op, ast.USub) else num(walk(node.operand))
            if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in cmps:
                return cmps[type(node.ops[0])](walk(node.left), walk(node.comparators[0]))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
                name = node.func.id.upper() if not node.func.id.endswith("_") else node.func.id
                if name not in funcs:
                    raise SheetError("#NAME?")
                return funcs[name](*[walk(a) for a in node.args])
            if isinstance(node, ast.Name):
                if node.id.upper() in ("TRUE", "FALSE"):
                    return node.id.upper() == "TRUE"
                raise SheetError("#NAME?")
            raise SheetError("#ERROR!")
        result = walk(tree)
        if isinstance(result, bool):
            return "TRUE" if result else "FALSE"
        if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
            raise SheetError("#VALUE!")
        return result

    @staticmethod
    def show(value) -> str:
        if isinstance(value, float):
            if value == int(value) and abs(value) < 1e15:
                return f"{int(value):,}"
            return f"{value:,.6f}".rstrip("0").rstrip(".") if abs(value) >= 1e-4 else f"{value:.4g}"
        return str(value)

    def to_rows(self, values: bool) -> list:
        if not self.raw:
            return []
        rows, cols = max(r for r, _ in self.raw) + 1, max(c for _, c in self.raw) + 1
        return [[(self.show(self.value(r, c)) if values else self.raw.get((r, c), "")) for c in range(cols)] for r in range(rows)]


class Grid(QAbstractTableModel):
    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine

    def rowCount(self, parent=QModelIndex()):
        return Engine.ROWS

    def columnCount(self, parent=QModelIndex()):
        return Engine.COLS

    def roleNames(self):
        return {Qt.DisplayRole: b"display", Qt.UserRole: b"number", Qt.UserRole + 1: b"problem", Qt.UserRole + 2: b"formula"}

    def data(self, index, role=Qt.DisplayRole):
        value = self.engine.value(index.row(), index.column())
        if role == Qt.DisplayRole:
            return Engine.show(value)
        if role == Qt.UserRole:
            return isinstance(value, float)
        if role == Qt.UserRole + 1:
            return isinstance(value, str) and value in ERRORS
        if role == Qt.UserRole + 2:
            return self.engine.raw.get((index.row(), index.column()), "").startswith("=")
        return None

    def refresh(self):
        self.dataChanged.emit(self.index(0, 0), self.index(Engine.ROWS - 1, Engine.COLS - 1))


class Sheets(FileList):
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".hsheet", ".csv"), (".xlsx",), (".ods", ".xls"), "xlsx", "Untitled Sheet"

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._engine = Engine()
        self._grid = Grid(self._engine)
        # A file holds one or more sheets. The one in front IS the engine's cells (the same dict), so nothing is copied
        # back and forth when you switch.
        self._sheets, self._at = [{"name": "Sheet 1", "cells": self._engine.raw}], 0
        self.changed.connect(self.sheetsChanged)
        if self._extra:
            self.open(str(self._extra))

    grid = Property(QObject, lambda self: self._grid, constant=True)
    sheetsChanged = Signal()   # a property of this class must be announced by a signal of this class
    sheetNames = Property("QVariantList", lambda self: [sh["name"] for sh in self._sheets], notify=sheetsChanged)
    sheetIndex = Property(int, lambda self: self._at, notify=sheetsChanged)
    # A CSV file is one table of plain values: it cannot hold a second sheet.
    oneSheetOnly = Property(bool, lambda self: self._path is not None and self._path.suffix.lower() == ".csv", notify=sheetsChanged)

    def _front(self, index: int) -> None:
        self._at = index
        self._engine.raw = self._sheets[index]["cells"]
        self._engine._cache.clear()
        self._grid.refresh()

    def _set_sheets(self, sheets: list, at: int = 0) -> None:
        """sheets: [(name, rows)] with rows[r][c] the text of a cell."""
        self._sheets = []
        for name, rows in sheets[:self.MAX_SHEETS] or [("Sheet 1", [])]:
            cells = {}
            for r, row in enumerate(rows[:Engine.ROWS]):
                for c, text in enumerate(row[:Engine.COLS]):
                    if str(text).strip():
                        cells[(r, c)] = str(text).strip()
            self._sheets.append({"name": self._fresh_name(str(name)), "cells": cells})
        self._front(max(0, min(at, len(self._sheets) - 1)))

    MAX_SHEETS = 24

    def _fresh_name(self, wanted: str, skip: int = -1) -> str:
        wanted = " ".join(wanted.split())[:31] or "Sheet"
        taken = {sh["name"].lower() for i, sh in enumerate(self._sheets) if i != skip}
        name, n = wanted, 2
        while name.lower() in taken:
            name, n = f"{wanted[:27]} {n}", n + 1
        return name

    @Slot(int)
    def selectSheet(self, index: int) -> None:
        if 0 <= index < len(self._sheets) and index != self._at:
            self._front(index)
            self.changed.emit()

    @Slot()
    def addSheet(self) -> None:
        if self._path is None or self.oneSheetOnly or len(self._sheets) >= self.MAX_SHEETS:
            return
        n = len(self._sheets) + 1
        self._sheets.append({"name": self._fresh_name(f"Sheet {n}"), "cells": {}})
        self._front(len(self._sheets) - 1)
        self.touch()

    @Slot(int, str)
    def renameSheet(self, index: int, name: str) -> None:
        if 0 <= index < len(self._sheets) and name.strip() and name.strip() != self._sheets[index]["name"]:
            self._sheets[index]["name"] = self._fresh_name(name, skip=index)
            self.touch()

    @Slot(int)
    def removeSheet(self, index: int) -> None:
        if len(self._sheets) < 2 or not 0 <= index < len(self._sheets):
            return
        del self._sheets[index]
        self._front(min(self._at if index > self._at else max(0, self._at - 1) if index < self._at else index, len(self._sheets) - 1))
        self.touch()

    @Slot(int, result=str)
    def column(self, index: int) -> str:
        return col_name(index)

    @Slot(int, int, result=str)
    def raw(self, row: int, col: int) -> str:
        return self._engine.raw.get((row, col), "")

    @Slot(int, int, str)
    def put(self, row: int, col: int, text: str) -> None:
        if self._engine.raw.get((row, col), "") == text.strip():
            return
        self._engine.set(row, col, text)
        self._grid.refresh()
        if self._path is not None:
            self.touch()

    @Slot(int, result=str)
    def columnSummary(self, col: int) -> str:
        values = [v for (r, c) in list(self._engine.raw) if c == col for v in [self._engine.value(r, c)] if isinstance(v, float)]
        if len(values) < 2:
            return ""
        return f"Column {col_name(col)}:  sum {Engine.show(math.fsum(values))}   average {Engine.show(round(math.fsum(values) / len(values), 4))}   count {len(values)}"

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source = Path(path)
        try:
            kind, target, dropped = source.suffix.lower(), source, None
            at = 0
            if kind in self.FOREIGN:
                book, sheets, dropped = self._modern(source), [], []
                names = convert.xlsx_sheet_names(book)
                for i, name in enumerate(names[:self.MAX_SHEETS]):
                    rows, lost = convert.xlsx_to_rows(book, Engine.ROWS, Engine.COLS, Engine.NAMES, index=i, every=True)
                    sheets.append((name, rows))
                    dropped += [item for item in lost if item not in dropped]
                if len(names) > self.MAX_SHEETS:
                    dropped.append(f"{len(names) - self.MAX_SHEETS} sheets past the first {self.MAX_SHEETS}")
                target = fresh_path(source.parent, source.stem, ".hsheet")
            elif kind == ".csv":
                text = source.read_text(encoding="utf-8-sig", errors="replace")
                sheets = [("Sheet 1", list(csv.reader(io.StringIO(text), csv.Sniffer().sniff(text[:2000], ",;\t") if text.strip() else csv.excel)))]
            else:
                data = json.loads(source.read_text(encoding="utf-8"))
                found = data.get("sheets") if isinstance(data.get("sheets"), list) else [{"name": "Sheet 1", "cells": data.get("cells", {})}]   # the first format had one sheet
                sheets, at = [], int(data.get("front", 0) or 0)
                for entry in found:
                    rows = [[""] * Engine.COLS for _ in range(Engine.ROWS)]
                    for ref, text in (entry.get("cells") or {}).items():
                        r, c = parse_ref(ref)
                        if r < Engine.ROWS and c < Engine.COLS:
                            rows[r][c] = text
                    sheets.append((entry.get("name") or "Sheet", rows))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error, convert.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self._set_sheets(sheets, at)
        self._path, self._dirty = target, False
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".hsheet")
            path.write_text('{"format": "huginn-sheet-2", "sheets": [{"name": "Sheet 1", "cells": {}}]}', encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a sheet: {err.strerror or err}")
            return
        self.open(str(path))

    def _csv(self, values: bool) -> str:
        out = io.StringIO()
        csv.writer(out).writerows(self._engine.to_rows(values))
        return out.getvalue()

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            if self._path.suffix.lower() == ".csv":
                write_atomic(self._path, self._csv(values=False))
            else:
                sheets = [{"name": sh["name"], "cells": {col_name(c) + str(r + 1): text for (r, c), text in sorted(sh["cells"].items())}} for sh in self._sheets]
                write_atomic(self._path, json.dumps({"format": "huginn-sheet-2", "front": self._at, "sheets": sheets}, indent=1, ensure_ascii=False))
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    @Slot(str, result=str)
    def export(self, kind: str) -> str:
        """kind: csv (the values you see, of the sheet in front) | xlsx (every sheet; formulas kept, with their results alongside)."""
        if self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, "." + kind)
            if kind == "csv":
                out.write_text(self._csv(values=True), encoding="utf-8")
            elif kind == "xlsx":
                book = []
                for sh in self._sheets:
                    engine = self._engine if sh["cells"] is self._engine.raw else Engine()
                    engine.raw = sh["cells"]
                    book.append((sh["name"], engine.to_rows(values=False), engine.value))
                convert.sheets_to_xlsx(book, out)
            else:
                return ""
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)


# ============================================================================================== Slides
class Slides(FileList):
    NATIVE, OWN, VIA_BRIDGE, MODERN, STEM = (".hslides",), (".pptx",), (".odp", ".ppt"), "pptx", "Untitled Talk"
    LAYOUTS = ("title", "content", "section", "blank")
    THEMES = ("realm", "paper", "night")

    def __init__(self, target: Path = None):
        super().__init__(target)
        self._deck = {"theme": "realm", "slides": []}
        self._index = 0
        self.changed.connect(self.deckChanged)
        if self._extra:
            self.open(str(self._extra))

    deckChanged = Signal()        # a subclass property needs a signal declared in the same class
    slides = Property("QVariantList", lambda self: self._deck["slides"], notify=deckChanged)
    theme = Property(str, lambda self: self._deck["theme"], notify=deckChanged)
    index = Property(int, lambda self: self._index, notify=deckChanged)
    count = Property(int, lambda self: len(self._deck["slides"]), notify=deckChanged)

    @Slot(str)
    def open(self, path: str) -> None:
        note_recent(path)
        if self._dirty:
            self.save()
        source, target, dropped = Path(path), Path(path), None
        try:
            if source.suffix.lower() in self.FOREIGN:
                found, dropped = convert.pptx_to_slides(self._modern(source))
                data, target = {"theme": "realm", "slides": found}, fresh_path(source.parent, source.stem, ".hslides")
            else:
                data = json.loads(source.read_text(encoding="utf-8"))
            slides = [{"layout": s.get("layout", "content") if s.get("layout") in self.LAYOUTS else "content",
                       "title": str(s.get("title", "")), "body": str(s.get("body", "")), "notes": str(s.get("notes", ""))}
                      for s in data.get("slides", []) if isinstance(s, dict)]
        except (OSError, ValueError, AttributeError, convert.ConvertError) as err:
            self.failed.emit(f"Couldn't open “{source.name}”: {getattr(err, 'strerror', None) or err}")
            return
        self._deck = {"theme": data.get("theme") if data.get("theme") in self.THEMES else "realm", "slides": slides or [self._blank("title")]}
        self._path, self._dirty, self._index = target, False, 0
        if target != source:
            self.touch()
            self.imported.emit(source.name, dropped or [])
        self.changed.emit()

    @staticmethod
    def _blank(layout: str) -> dict:
        return {"layout": layout, "title": "", "body": "", "notes": ""}

    @Slot()
    def create(self) -> None:
        if self._dirty:
            self.save()
        try:
            path = fresh_path(self._folder, self.STEM, ".hslides")
            path.write_text(json.dumps({"theme": "realm", "slides": [self._blank("title")]}), encoding="utf-8")
        except OSError as err:
            self.failed.emit(f"Couldn't create a presentation: {err.strerror or err}")
            return
        self.open(str(path))

    @Slot()
    def save(self) -> None:
        if not self._dirty or self._path is None:
            return
        try:
            write_atomic(self._path, json.dumps({"format": "huginn-slides-1", **self._deck}, indent=1, ensure_ascii=False))
            self._dirty = False
        except OSError as err:
            self.failed.emit(f"Couldn't save: {err.strerror or err}")
        self.changed.emit()

    @Slot(int)
    def select(self, index: int) -> None:
        if 0 <= index < len(self._deck["slides"]) and index != self._index:
            self._index = index
            self.changed.emit()

    @Slot(str)
    def add(self, layout: str) -> None:
        if self._path is None:
            return
        self._deck["slides"].insert(self._index + 1, self._blank(layout if layout in self.LAYOUTS else "content"))
        self._index += 1
        self.touch()

    @Slot()
    def remove(self) -> None:
        if len(self._deck["slides"]) > 1:
            del self._deck["slides"][self._index]
            self._index = min(self._index, len(self._deck["slides"]) - 1)
            self.touch()

    @Slot(int)
    def move(self, delta: int) -> None:
        target = self._index + delta
        if 0 <= target < len(self._deck["slides"]):
            s = self._deck["slides"]
            s[self._index], s[target] = s[target], s[self._index]
            self._index = target
            self.touch()

    @Slot(int, str, str)
    def write(self, index: int, field: str, text: str) -> None:
        if 0 <= index < len(self._deck["slides"]) and field in ("title", "body", "notes", "layout") and self._deck["slides"][index][field] != text:
            if field == "layout" and text not in self.LAYOUTS:
                return
            self._deck["slides"][index][field] = text
            self.touch()

    @Slot(str)
    def setTheme(self, name: str) -> None:
        if name in self.THEMES and name != self._deck["theme"]:
            self._deck["theme"] = name
            self.touch()

    @Slot(result=str)
    def exportPowerPoint(self) -> str:
        if self._path is None:
            return ""
        self.save()
        try:
            out = fresh_path(self._path.parent, self._path.stem, ".pptx")
            convert.slides_to_pptx(self._deck["slides"], out, self._deck["theme"])
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)

    @Slot(result=str)
    def scratch(self) -> str:
        """A temporary folder for the slide pictures an export is made from."""
        return tempfile.mkdtemp(prefix="huginn-slides-")

    @Slot("QVariantList", result=str)
    def pdf(self, pictures: list) -> str:
        """Bind one picture per slide into a PDF beside the presentation. Returns its path ('' on failure)."""
        if self._path is None or not pictures:
            return ""
        try:
            out = fresh_path(self._path.parent, self._path.stem, ".pdf")
            writer = QPdfWriter(str(out))
            writer.setPageSize(QPageSize(QSizeF(338.67, 190.5), QPageSize.Millimeter))          # 16:9
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            writer.setResolution(144)
            writer.setTitle(self._path.stem)
            painter = QPainter(writer)
            for n, picture in enumerate(pictures):
                image = QImage(str(picture))
                if image.isNull():
                    painter.end()
                    raise OSError("a slide picture is missing")
                if n:
                    writer.newPage()
                painter.drawImage(painter.viewport(), image)
            painter.end()
            shutil.rmtree(Path(str(pictures[0])).parent, ignore_errors=True)
        except OSError as err:
            self.failed.emit(f"Couldn't export: {err.strerror or err}")
            return ""
        return str(out)
