"""Huginn Office's own converters for Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files.

These files are zip archives of XML in a published format (Office Open XML, ECMA-376). This module reads and writes
the everyday part of that format using only Python's standard library:

    Word        text, title and headings, bold / italic / underline, colour, size, alignment, bullet and numbered
                lists, simple tables (read only)
    Excel       the first sheet: numbers, text, dates, true/false and formulas
    PowerPoint  each slide's title, body text and speaker notes

Every reader also returns a plain-language list of what the file contained that was NOT carried over (pictures,
charts, tracked changes ...), so the app can tell the user instead of losing things silently.
"""
import datetime as dt
import html
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
MAX_PART = 64 * 1024 * 1024        # refuse absurdly large XML parts (zip bombs)


class ConvertError(Exception):
    pass


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _part(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART:
        raise ConvertError("The file is too large to open safely.")
    data = z.read(info)
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data[:4096]:
        raise ConvertError("The file contains constructs that aren't allowed in office documents.")
    return ET.fromstring(data)


def _open(path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as err:
        raise ConvertError(f"This isn't a readable office file ({err}).")


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    """Relationship id -> target path (resolved against the part's folder) for one package part."""
    folder, _, name = part.rpartition("/")
    root = _part(z, f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels")
    out = {}
    for rel in root if root is not None else []:
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        pieces = (target.lstrip("/") if target.startswith("/") else f"{folder}/{target}").split("/")
        stack = []
        for piece in pieces:
            if piece == "..":
                if stack:
                    stack.pop()
            elif piece not in ("", "."):
                stack.append(piece)
        out[rel.get("Id")] = ("/".join(stack), rel.get("Type", ""))
    return out


def _plural(n: int, one: str, many: str = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# =============================================================================================== Word
def docx_to_html(path) -> tuple:
    """Returns (html, dropped) where dropped is a list of plain-language notes."""
    with _open(path) as z:
        doc = _part(z, "word/document.xml")
        if doc is None:
            raise ConvertError("This doesn't look like a Word document.")
        numbering = _part(z, "word/numbering.xml")
        names = z.namelist()
    body = doc.find(_q(W, "body"))
    if body is None:
        raise ConvertError("The Word document has no text body.")

    # numId -> True when the list is numbered (anything other than a bullet)
    numbered = {}
    if numbering is not None:
        abstract = {}
        for an in numbering.findall(_q(W, "abstractNum")):
            lvl = an.find(_q(W, "lvl"))
            fmt = lvl.find(_q(W, "numFmt")) if lvl is not None else None
            abstract[an.get(_q(W, "abstractNumId"))] = (fmt.get(_q(W, "val")) if fmt is not None else "bullet") != "bullet"
        for num in numbering.findall(_q(W, "num")):
            ref = num.find(_q(W, "abstractNumId"))
            numbered[num.get(_q(W, "numId"))] = abstract.get(ref.get(_q(W, "val")) if ref is not None else None, False)

    def on(node, tag) -> bool:
        el = node.find(_q(W, tag)) if node is not None else None
        return el is not None and el.get(_q(W, "val"), "true") not in ("0", "false", "none")

    def runs(par) -> str:
        out = []
        for run in par.iter(_q(W, "r")):
            props = run.find(_q(W, "rPr"))
            text = []
            for child in run:
                if child.tag == _q(W, "t"):
                    text.append(html.escape(child.text or ""))
                elif child.tag == _q(W, "tab"):
                    text.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                elif child.tag in (_q(W, "br"), _q(W, "cr")):
                    text.append("<br/>")
            piece = "".join(text)
            if not piece:
                continue
            css = []
            if props is not None:
                colour = props.find(_q(W, "color"))
                if colour is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", colour.get(_q(W, "val"), "")):
                    css.append(f"color:#{colour.get(_q(W, 'val'))}")
                size = props.find(_q(W, "sz"))
                if size is not None and (size.get(_q(W, "val")) or "").isdigit():
                    css.append(f"font-size:{int(size.get(_q(W, 'val'))) / 2:g}pt")
            if css:
                piece = f'<span style="{";".join(css)}">{piece}</span>'
            if on(props, "b"):
                piece = f"<b>{piece}</b>"
            if on(props, "i"):
                piece = f"<i>{piece}</i>"
            if on(props, "u"):
                piece = f"<u>{piece}</u>"
            out.append(piece)
        return "".join(out)

    def paragraph(par) -> tuple:
        """(list kind or '', html)"""
        props = par.find(_q(W, "pPr"))
        style = align = ""
        list_kind = ""
        if props is not None:
            st = props.find(_q(W, "pStyle"))
            style = (st.get(_q(W, "val")) or "") if st is not None else ""
            jc = props.find(_q(W, "jc"))
            align = {"center": "center", "right": "right", "end": "right", "both": "justify"}.get(jc.get(_q(W, "val")) if jc is not None else "", "")
            num = props.find(_q(W, "numPr"))
            if num is not None:
                nid = num.find(_q(W, "numId"))
                key = nid.get(_q(W, "val")) if nid is not None else None
                if key and key != "0":
                    list_kind = "ol" if numbered.get(key, False) else "ul"
        if not list_kind and style.lower().startswith("list"):
            list_kind = "ol" if "number" in style.lower() else "ul"
        inner = runs(par)
        attr = f' align="{align}"' if align else ""
        low = style.lower().replace(" ", "")
        if list_kind:
            return list_kind, f"<li{attr}>{inner}</li>"
        if low == "title":
            return "", f"<h1{attr}>{inner}</h1>"
        m = re.fullmatch(r"heading([1-9])", low)
        if m:
            level = min(3, int(m.group(1)) + 1)
            return "", f"<h{level}{attr}>{inner}</h{level}>"
        return "", f"<p{attr}>{inner or '<br/>'}</p>"

    parts, open_list = [], ""
    tables = 0
    for child in body:
        if child.tag == _q(W, "p"):
            kind, markup = paragraph(child)
            if kind != open_list:
                if open_list:
                    parts.append(f"</{open_list}>")
                if kind:
                    parts.append(f"<{kind}>")
                open_list = kind
            parts.append(markup)
        elif child.tag == _q(W, "tbl"):
            if open_list:
                parts.append(f"</{open_list}>")
                open_list = ""
            tables += 1
            rows = []
            for row in child.findall(_q(W, "tr")):
                cells = ["<td>" + "".join(paragraph(p)[1] for p in cell.findall(_q(W, "p"))) + "</td>" for cell in row.findall(_q(W, "tc"))]
                rows.append("<tr>" + "".join(cells) + "</tr>")
            parts.append('<table border="1" cellspacing="0" cellpadding="6">' + "".join(rows) + "</table>")
    if open_list:
        parts.append(f"</{open_list}>")

    count = lambda tag: sum(1 for _ in doc.iter(_q(W, tag)))      # noqa: E731
    dropped = []
    pictures = count("drawing") + count("pict")
    if pictures:
        dropped.append(_plural(pictures, "picture or drawing", "pictures or drawings"))
    if count("ins") or count("del"):
        dropped.append("tracked changes (shown as if all were accepted)")
    if count("commentReference"):
        dropped.append(_plural(count("commentReference"), "comment"))
    if count("footnoteReference") or count("endnoteReference"):
        dropped.append("footnotes and endnotes")
    if any(n.startswith(("word/header", "word/footer")) for n in names):
        dropped.append("page headers and footers")
    if any(el.tag.endswith("}oMath") for el in doc.iter()):
        dropped.append("equations")
    if tables:
        dropped.append(f"table styling ({_plural(tables, 'table')} kept as plain grids)")
    dropped.append("fonts, page size and margins")
    return "<html><body>" + "".join(parts) + "</body></html>", dropped


CONTENT_TYPES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>%s</Types>'
ROOT_RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" Target="%s"/></Relationships>'


def _write(path, parts: dict) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))     # fixed time: same content, same file
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)


def blocks_to_docx(blocks: list, path) -> None:
    """Write a .docx. `blocks` is a list of dicts:
       {"style": title|heading|subheading|body, "align": left|center|right|justify, "list": ""|bullet|number,
        "runs": [{"text", "bold", "italic", "underline", "color" (#RRGGBB or ""), "size" (pt or 0)}]}"""
    style_id = {"title": "Title", "heading": "Heading1", "subheading": "Heading2"}
    jc = {"center": "center", "right": "right", "justify": "both"}
    body = []
    for block in blocks:
        ppr = ""
        if block.get("style") in style_id:
            ppr += f'<w:pStyle w:val="{style_id[block["style"]]}"/>'
        elif block.get("list"):
            ppr += '<w:pStyle w:val="ListParagraph"/>'
        if block.get("list"):
            ppr += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{1 if block["list"] == "bullet" else 2}"/></w:numPr>'
        if block.get("align") in jc:
            ppr += f'<w:jc w:val="{jc[block["align"]]}"/>'
        runs = []
        for run in block.get("runs", []):
            rpr = ("<w:b/>" if run.get("bold") else "") + ("<w:i/>" if run.get("italic") else "") + ('<w:u w:val="single"/>' if run.get("underline") else "")
            colour = (run.get("color") or "").lstrip("#")
            if re.fullmatch(r"[0-9A-Fa-f]{6}", colour) and colour.upper() not in ("000000", "15181C", "101317"):
                rpr += f'<w:color w:val="{colour.upper()}"/>'
            if run.get("size") and block.get("style", "body") == "body" and abs(run["size"] - 11) > 0.4:
                rpr += f'<w:sz w:val="{round(run["size"] * 2)}"/>'
            for n, line in enumerate(run.get("text", "").split(" ")):
                text = f'<w:t xml:space="preserve">{escape(line)}</w:t>'
                runs.append(f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}{"<w:br/>" if n else ""}{text}</w:r>')
        body.append(f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}{"".join(runs)}</w:p>')
    head = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>'
    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1247" w:right="1247" w:bottom="1247" w:left="1247" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'

    def para_style(sid, name, size, bold, before, after, level=None):
        outline = f'<w:outlineLvl w:val="{level}"/>' if level is not None else ""
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
                f'<w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="{after}"/>{outline}</w:pPr><w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size * 2}"/></w:rPr></w:style>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="Inter" w:hAnsi="Inter" w:cs="Inter"/><w:sz w:val="22"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              + para_style("Title", "Title", 26, True, 0, 200) + para_style("Heading1", "heading 1", 18, True, 280, 120, 0)
              + para_style("Heading2", "heading 2", 14, True, 220, 100, 1)
              + '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:contextualSpacing/></w:pPr></w:style></w:styles>')

    def abstract(aid, fmt, text):
        return (f'<w:abstractNum w:abstractNumId="{aid}"><w:multiLevelType w:val="hybridMultilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
                f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>')
    numbering = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="{W}">' + abstract(0, "bullet", "•") + abstract(1, "decimal", "%1.")
                 + '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
    ct = ('<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>')
    doc_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/styles" Target="styles.xml"/>'
                f'<Relationship Id="rId2" Type="{R}/numbering" Target="numbering.xml"/></Relationships>')
    _write(path, {"[Content_Types].xml": CONTENT_TYPES % ct, "_rels/.rels": ROOT_RELS % (PKG, R, "word/document.xml"),
                  "word/document.xml": head + "".join(body) + sect + "</w:body></w:document>", "word/_rels/document.xml.rels": doc_rels,
                  "word/styles.xml": styles, "word/numbering.xml": numbering})


# ============================================================================================== Excel
DATE_FORMATS = set(range(14, 23)) | {45, 46, 47}
CELL = re.compile(r"([A-Z]{1,3})([0-9]+)")


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_sheet_names(path) -> list:
    """The names of a workbook's sheets, in order."""
    with _open(path) as z:
        book = _part(z, "xl/workbook.xml")
        if book is None:
            raise ConvertError("This doesn't look like an Excel workbook.")
        return [sh.get("name") or f"Sheet {i + 1}" for i, sh in enumerate(book.findall(f"{_q(S, 'sheets')}/{_q(S, 'sheet')}"))]


def xlsx_to_rows(path, max_rows: int = 200, max_cols: int = 26, known_functions: frozenset = frozenset(), index: int = 0, every: bool = False) -> tuple:
    """Returns (rows, dropped) for one sheet (`index`). rows[r][c] is the text to put in the cell: a value, or '=formula'.
    `every`: the caller is opening all the sheets, so the others are not reported as left out."""
    with _open(path) as z:
        book = _part(z, "xl/workbook.xml")
        if book is None:
            raise ConvertError("This doesn't look like an Excel workbook.")
        rels = _rels(z, "xl/workbook.xml")
        sheets = book.findall(f"{_q(S, 'sheets')}/{_q(S, 'sheet')}")
        if not sheets:
            raise ConvertError("The workbook has no sheets.")
        if not 0 <= index < len(sheets):
            raise ConvertError("The workbook has no such sheet.")
        target = rels.get(sheets[index].get(_q(R, "id")), (f"xl/worksheets/sheet{index + 1}.xml", ""))[0]
        sheet = _part(z, target)
        if sheet is None:
            raise ConvertError("A sheet couldn't be read.")
        shared_root, styles = _part(z, "xl/sharedStrings.xml"), _part(z, "xl/styles.xml")
        names = z.namelist()
    shared = ["".join(t.text or "" for t in si.iter(_q(S, "t"))) for si in shared_root.findall(_q(S, "si"))] if shared_root is not None else []
    date_styles = set()
    if styles is not None:
        custom = {int(f.get("numFmtId")): f.get("formatCode", "") for f in styles.iter(_q(S, "numFmt")) if (f.get("numFmtId") or "").isdigit()}
        xfs = styles.find(_q(S, "cellXfs"))
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId", "0") or 0)
            code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fid, "")).lower()
            if fid in DATE_FORMATS or (code and any(ch in code for ch in "yd") and "0" not in code and "#" not in code):
                date_styles.add(i)

    rows, clipped, shared_formulas, unknown, across = [], 0, 0, set(), 0
    for cell in sheet.iter(_q(S, "c")):
        m = CELL.fullmatch(cell.get("r", ""))
        if not m:
            continue
        r, c = int(m.group(2)) - 1, _col(m.group(1))
        kind, v, f = cell.get("t", "n"), cell.find(_q(S, "v")), cell.find(_q(S, "f"))
        raw = v.text if v is not None and v.text is not None else ""
        if kind == "s":
            value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
        elif kind == "inlineStr":
            value = "".join(t.text or "" for t in cell.iter(_q(S, "t")))
        elif kind == "b":
            value = "TRUE" if raw == "1" else "FALSE"
        elif raw and (cell.get("s") or "").isdigit() and int(cell.get("s")) in date_styles:
            try:
                moment = dt.datetime(1899, 12, 30) + dt.timedelta(days=float(raw))
                value = moment.date().isoformat() if float(raw) == int(float(raw)) else moment.strftime("%Y-%m-%d %H:%M")
            except (ValueError, OverflowError):
                value = raw
        else:
            value = raw
        if f is not None:
            if f.text:
                value = "=" + f.text
                across += "!" in f.text
                unknown |= {name for name in re.findall(r"([A-Za-z][A-Za-z0-9.]*)\s*\(", f.text) if known_functions and name.upper() not in known_functions}
            else:
                shared_formulas += 1          # a copied-down formula stored only once: keep its result
        if value == "":
            continue
        if r >= max_rows or c >= max_cols:
            clipped += 1
            continue
        while len(rows) <= r:
            rows.append([])
        rows[r] += [""] * (c + 1 - len(rows[r]))
        rows[r][c] = value

    dropped = []
    if across:
        dropped.append(f"{_plural(across, 'formula')} that reads from another sheet (shown as an error)")
    if len(sheets) > 1 and not every:
        dropped.append(f"{_plural(len(sheets) - 1, 'other sheet')} (only “{sheets[0].get('name', 'the first')}” was opened)")
    charts = sum(1 for n in names if n.startswith("xl/charts/chart"))
    if charts:
        dropped.append(_plural(charts, "chart"))
    if any(n.startswith("xl/media/") for n in names):
        dropped.append("pictures")
    if any(n.startswith("xl/pivotTables/") for n in names):
        dropped.append("pivot tables")
    merged = sum(1 for _ in sheet.iter(_q(S, "mergeCell")))
    if merged:
        dropped.append(f"{_plural(merged, 'merged cell group')} (shown unmerged)")
    if sum(1 for _ in sheet.iter(_q(S, "conditionalFormatting"))):
        dropped.append("conditional formatting")
    if shared_formulas:
        dropped.append(f"{_plural(shared_formulas, 'copied-down formula')} (kept as their results)")
    if unknown:
        dropped.append("formulas using " + ", ".join(sorted(unknown)[:6]) + " (they will show an error until those functions exist here)")
    if clipped:
        dropped.append(f"{_plural(clipped, 'cell')} beyond row {max_rows} or column {max_cols}")
    dropped.append("cell colours, fonts, borders and number formats")
    return rows, dropped


def rows_to_xlsx(rows: list, path, cached=None) -> None:
    """Write a workbook with one sheet (see sheets_to_xlsx)."""
    sheets_to_xlsx([("Sheet1", rows, cached)], path)


def sheets_to_xlsx(sheets: list, path) -> None:
    """Write a workbook. `sheets` is a list of (name, rows, cached): rows[r][c] is cell text ('=A1+1', '12.5', 'hello');
    `cached(r, c)` may return a formula's current value so other programs can show it before recalculating."""
    parts, names = {}, []
    for name, rows, cached in sheets:
        clean = re.sub(r"[\[\]:*?/\\]", " ", str(name)).strip()[:31] or f"Sheet{len(names) + 1}"     # what Excel allows in a sheet's name
        while clean.lower() in [n.lower() for n in names]:
            clean = clean[:28] + f" {len(names) + 1}"
        names.append(clean)
        parts[f"xl/worksheets/sheet{len(names)}.xml"] = _sheet_xml(rows, cached)
    book = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{S}" xmlns:r="{R}"><sheets>'
            + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
            + '</sheets><calcPr fullCalcOnLoad="1"/></workbook>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{S}"><fonts count="1"><font><sz val="11"/><name val="Inter"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    ct = ('<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(names)))
          + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
    rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">'
            + "".join(f'<Relationship Id="rId{i + 1}" Type="{R}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names)))
            + f'<Relationship Id="rId{len(names) + 1}" Type="{R}/styles" Target="styles.xml"/></Relationships>')
    parts.update({"[Content_Types].xml": CONTENT_TYPES % ct, "_rels/.rels": ROOT_RELS % (PKG, R, "xl/workbook.xml"), "xl/workbook.xml": book,
                  "xl/_rels/workbook.xml.rels": rels, "xl/styles.xml": styles})
    _write(path, parts)


def _sheet_xml(rows: list, cached=None) -> str:
    def ref(r, c):
        name, n = "", c + 1
        while n:
            n, rem = divmod(n - 1, 26)
            name = chr(65 + rem) + name
        return f"{name}{r + 1}"
    out = []
    for r, row in enumerate(rows):
        cells = []
        for c, text in enumerate(row):
            text = str(text)
            if text == "":
                continue
            if text.startswith("=") and len(text) > 1:
                value = cached(r, c) if cached else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    cells.append(f'<c r="{ref(r, c)}"><f>{escape(text[1:])}</f><v>{value!r}</v></c>')
                elif isinstance(value, str) and value and not value.startswith("#"):
                    cells.append(f'<c r="{ref(r, c)}" t="str"><f>{escape(text[1:])}</f><v>{escape(value)}</v></c>')
                else:
                    cells.append(f'<c r="{ref(r, c)}"><f>{escape(text[1:])}</f></c>')
                continue
            try:
                number = float(text.replace(",", ""))
                if number != number or number in (float("inf"), float("-inf")):
                    raise ValueError
                cells.append(f'<c r="{ref(r, c)}"><v>{number!r}</v></c>')
            except ValueError:
                cells.append(f'<c r="{ref(r, c)}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>')
        if cells:
            out.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{S}"><sheetData>{"".join(out)}</sheetData></worksheet>'


# ========================================================================================= PowerPoint
def _shape_text(shape) -> str:
    lines = []
    for par in shape.iter(_q(A, "p")):
        line = []
        for node in par:
            if node.tag == _q(A, "r"):
                t = node.find(_q(A, "t"))
                line.append(t.text or "" if t is not None else "")
            elif node.tag == _q(A, "br"):
                line.append("\n")
            elif node.tag == _q(A, "fld"):
                t = node.find(_q(A, "t"))
                line.append(t.text or "" if t is not None else "")
        lines.append("".join(line))
    return "\n".join(lines).strip()


def pptx_to_slides(path) -> tuple:
    """Returns (slides, dropped); each slide is {"layout", "title", "body", "notes"}."""
    with _open(path) as z:
        pres = _part(z, "ppt/presentation.xml")
        if pres is None:
            raise ConvertError("This doesn't look like a PowerPoint presentation.")
        rels = _rels(z, "ppt/presentation.xml")
        order = [rels[s.get(_q(R, "id"))][0] for s in pres.iter(_q(P, "sldId")) if s.get(_q(R, "id")) in rels]
        slides, pictures, graphics, animated, boxes = [], 0, 0, 0, 0
        for part in order[:500]:
            root = _part(z, part)
            if root is None:
                continue
            title, body, centred = "", [], False
            for shape in root.iter(_q(P, "sp")):
                ph = shape.find(f"{_q(P, 'nvSpPr')}/{_q(P, 'nvPr')}/{_q(P, 'ph')}")
                kind = ph.get("type", "body") if ph is not None else None
                text = _shape_text(shape)
                if kind in ("title", "ctrTitle"):
                    title, centred = text, centred or kind == "ctrTitle"
                elif kind in ("dt", "ftr", "sldNum"):
                    continue
                elif text:
                    body.append(text)
                    boxes += kind is None
            pictures += sum(1 for _ in root.iter(_q(P, "pic")))
            graphics += sum(1 for _ in root.iter(_q(P, "graphicFrame")))
            animated += root.find(_q(P, "timing")) is not None
            notes = ""
            for target, kind in _rels(z, part).values():
                if kind.endswith("/notesSlide"):
                    nroot = _part(z, target)
                    for shape in nroot.iter(_q(P, "sp")) if nroot is not None else []:
                        ph = shape.find(f"{_q(P, 'nvSpPr')}/{_q(P, 'nvPr')}/{_q(P, 'ph')}")
                        if ph is not None and ph.get("type") == "body":
                            notes = _shape_text(shape)
            text = "\n".join(body)
            layout = "title" if centred else "content" if text else "section" if title else "blank"
            slides.append({"layout": layout, "title": title, "body": text, "notes": notes})
    if not slides:
        raise ConvertError("The presentation has no slides.")
    dropped = []
    if pictures:
        dropped.append(_plural(pictures, "picture"))
    if graphics:
        dropped.append(_plural(graphics, "chart, table or diagram", "charts, tables or diagrams"))
    if animated:
        dropped.append(f"animations and transitions on {_plural(animated, 'slide')}")
    if boxes:
        dropped.append(f"the position of {_plural(boxes, 'free text box', 'free text boxes')} (their text was added to the slide body)")
    dropped.append("the design: colours, fonts, backgrounds and layout positions")
    return slides, dropped


PALETTES = {"realm": ("0F2624", "ECEFF3", "43D9B8"), "night": ("101317", "ECEFF3", "7CC4FF"), "paper": ("FFFFFF", "101317", "0A8071")}


def slides_to_pptx(slides: list, path, theme: str = "realm") -> None:
    """Write a .pptx with one title+body slide per entry, coloured after the Slides theme."""
    back, ink, accent = PALETTES.get(theme, PALETTES["realm"])
    ns = f'xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"'
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    tree_open = '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'

    def box(sid, name, ph, x, y, w, h, paragraphs, size, bold=False, centre=False, with_xfrm=True):
        runs = "".join(f'<a:p>{"<a:pPr algn=" + chr(34) + "ctr" + chr(34) + "/>" if centre else ""}<a:r><a:rPr lang="en-US" sz="{size * 100}"{" b=" + chr(34) + "1" + chr(34) if bold else ""} dirty="0">'
                       f'<a:solidFill><a:srgbClr val="{ink}"/></a:solidFill></a:rPr><a:t>{escape(line)}</a:t></a:r></a:p>' for line in paragraphs) or "<a:p/>"
        xfrm = f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>' if with_xfrm else ""
        return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr>'
                f'<p:spPr>{xfrm}</p:spPr><p:txBody><a:bodyPr{" anchor=" + chr(34) + "ctr" + chr(34) if centre else ""}><a:normAutofit/></a:bodyPr><a:lstStyle/>{runs}</p:txBody></p:sp>')
    bg = f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{back}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
    colour_map = '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    W_, H_ = 12192000, 6858000
    title_ph, body_ph = '<p:ph type="title"/>', '<p:ph type="body" idx="1"/>'
    master = (f'{head}<p:sldMaster {ns}><p:cSld>{bg}{tree_open}'
              + box(2, "Title", title_ph, 838200, 500000, W_ - 1676400, 1200000, ["Title"], 36, True)
              + box(3, "Body", body_ph, 838200, 1900000, W_ - 1676400, 4300000, ["Text"], 22)
              + f'</p:spTree></p:cSld>{colour_map}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
              '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="3600" b="1"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="2200"/></a:lvl1pPr></p:bodyStyle><p:otherStyle/></p:txStyles></p:sldMaster>')
    layout = (f'{head}<p:sldLayout {ns} type="obj" preserve="1"><p:cSld name="Title and Content">{tree_open}'
              + box(2, "Title", title_ph, 0, 0, 0, 0, ["Title"], 36, True, with_xfrm=False) + box(3, "Body", body_ph, 0, 0, 0, 0, ["Text"], 22, with_xfrm=False)
              + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    font = '<a:latin typeface="Inter"/><a:ea typeface=""/><a:cs typeface=""/>'
    fill3 = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    line3 = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
    theme_xml = (f'{head}<a:theme xmlns:a="{A}" name="Huginn"><a:themeElements><a:clrScheme name="Huginn">'
                 f'<a:dk1><a:srgbClr val="101317"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="0F2624"/></a:dk2><a:lt2><a:srgbClr val="ECEFF3"/></a:lt2>'
                 f'<a:accent1><a:srgbClr val="{accent}"/></a:accent1><a:accent2><a:srgbClr val="7B61FF"/></a:accent2><a:accent3><a:srgbClr val="FF8A4C"/></a:accent3>'
                 '<a:accent4><a:srgbClr val="7CC4FF"/></a:accent4><a:accent5><a:srgbClr val="FFC857"/></a:accent5><a:accent6><a:srgbClr val="FF7AB8"/></a:accent6>'
                 f'<a:hlink><a:srgbClr val="{accent}"/></a:hlink><a:folHlink><a:srgbClr val="7B61FF"/></a:folHlink></a:clrScheme>'
                 f'<a:fontScheme name="Huginn"><a:majorFont>{font}</a:majorFont><a:minorFont>{font}</a:minorFont></a:fontScheme>'
                 f'<a:fmtScheme name="Huginn"><a:fillStyleLst>{fill3}</a:fillStyleLst><a:lnStyleLst>{line3}</a:lnStyleLst>'
                 '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
                 f'<a:bgFillStyleLst>{fill3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    parts, slide_ids, pres_rels, overrides = {}, [], [], []
    notes_any = False
    for n, slide in enumerate(slides, 1):
        centred = slide.get("layout") in ("title", "section")
        shapes = ""
        if slide.get("layout") != "blank" or slide.get("title"):
            shapes += box(2, "Title", title_ph, 838200, 2300000 if centred else 500000, W_ - 1676400, 1500000 if centred else 1200000,
                          [slide.get("title", "")], 44 if centred else 36, True, centred)
        if slide.get("body") or slide.get("layout") == "content":
            lines = slide.get("body", "").split("\n") if slide.get("body") else []
            shapes += box(3, "Body", body_ph, 838200, 3900000 if centred else 1900000, W_ - 1676400, 1500000 if centred else 4300000, lines, 22, False, centred)
        parts[f"ppt/slides/slide{n}.xml"] = f'{head}<p:sld {ns}><p:cSld>{bg}{tree_open}{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
        rel = f'<Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        parts[f"ppt/slides/_rels/slide{n}.xml.rels"] = f'{head}<Relationships xmlns="{PKG}">{rel}</Relationships>'
        slide_ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n + 1}"/>')
        pres_rels.append(f'<Relationship Id="rId{n + 1}" Type="{R}/slide" Target="slides/slide{n}.xml"/>')
        overrides.append(f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
        notes_any = notes_any or bool(slide.get("notes"))
    theme_rel = len(slides) + 2
    parts["ppt/presentation.xml"] = (f'{head}<p:presentation {ns}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                                     f'<p:sldIdLst>{"".join(slide_ids)}</p:sldIdLst><p:sldSz cx="{W_}" cy="{H_}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    parts["ppt/_rels/presentation.xml.rels"] = (f'{head}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
                                                + "".join(pres_rels) + f'<Relationship Id="rId{theme_rel}" Type="{R}/theme" Target="theme/theme1.xml"/></Relationships>')
    parts["ppt/slideMasters/slideMaster1.xml"] = master
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = (f'{head}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                                                             f'<Relationship Id="rId2" Type="{R}/theme" Target="../theme/theme1.xml"/></Relationships>')
    parts["ppt/slideLayouts/slideLayout1.xml"] = layout
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = f'{head}<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>'
    parts["ppt/theme/theme1.xml"] = theme_xml
    ct = ('<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>' + "".join(overrides))
    ordered = {"[Content_Types].xml": CONTENT_TYPES % ct, "_rels/.rels": ROOT_RELS % (PKG, R, "ppt/presentation.xml")}
    ordered.update(parts)
    _write(path, ordered)
