"""Code, round four: the parts that don't need a window. Snippets and their tab stops, merge conflicts, the scopes
for sticky scroll and the outline, and quick fixes for Python's commonest problems (an import not used, a name
never imported), for when the language server has none of its own."""
import re
import sys

# name: (what it is, the body). In a body, ${1:text} is the first place to type (with text there to start),
# $2 the second, $0 where the cursor ends; a tab is one step of the file's own indentation.
SNIPPETS = {
    "Python": {
        "def": ("Function", "def ${1:name}(${2}):\n\t${0:pass}"),
        "adef": ("Async function", "async def ${1:name}(${2}):\n\t${0:pass}"),
        "class": ("Class", "class ${1:Name}:\n\tdef __init__(self${2}):\n\t\t${0:pass}"),
        "dataclass": ("Data class", "@dataclass\nclass ${1:Name}:\n\t${2:field}: ${3:int}${0}"),
        "main": ("Run as a program", "def main():\n\t${1:pass}\n\n\nif __name__ == \"__main__\":\n\tmain()${0}"),
        "for": ("Loop over something", "for ${1:item} in ${2:items}:\n\t${0:pass}"),
        "enum": ("Loop with numbers", "for ${1:i}, ${2:item} in enumerate(${3:items}):\n\t${0:pass}"),
        "while": ("While", "while ${1:True}:\n\t${0:pass}"),
        "if": ("If", "if ${1:condition}:\n\t${0:pass}"),
        "with": ("With", "with open(${1:path}) as ${2:f}:\n\t${0:pass}"),
        "try": ("Try … except", "try:\n\t${1:pass}\nexcept ${2:Exception} as ${3:e}:\n\t${0:raise}"),
        "test": ("Test (pytest)", "def test_${1:name}():\n\t${0:assert True}"),
        "prop": ("Property", "@property\ndef ${1:name}(self):\n\treturn self._${1:name}${0}"),
    },
    "JavaScript": {
        "fn": ("Function", "function ${1:name}(${2}) {\n\t${0}\n}"),
        "afn": ("Arrow function", "const ${1:name} = (${2}) => {\n\t${0}\n};"),
        "for": ("Loop over something", "for (const ${1:item} of ${2:items}) {\n\t${0}\n}"),
        "fori": ("Counting loop", "for (let ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t${0}\n}"),
        "if": ("If", "if (${1:condition}) {\n\t${0}\n}"),
        "log": ("Print", "console.log(${1});${0}"),
        "imp": ("Import", "import { ${2:name} } from \"${1:module}\";${0}"),
        "try": ("Try … catch", "try {\n\t${1}\n} catch (${2:err}) {\n\t${0}\n}"),
        "cls": ("Class", "class ${1:Name} {\n\tconstructor(${2}) {\n\t\t${0}\n\t}\n}"),
    },
    "C": {
        "main": ("A program's start", "int main(int argc, char **argv)\n{\n\t${0}\n\treturn 0;\n}"),
        "for": ("Counting loop", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t${0}\n}"),
        "if": ("If", "if (${1:condition}) {\n\t${0}\n}"),
        "inc": ("Include", "#include <${1:stdio.h}>${0}"),
        "guard": ("Include guard", "#ifndef ${1:NAME_H}\n#define ${1:NAME_H}\n\n${0}\n\n#endif"),
        "struct": ("Structure", "typedef struct {\n\t${2:int field};\n} ${1:Name};${0}"),
        "pf": ("Print", "printf(\"${1:%d}\\n\", ${2});${0}"),
    },
    "Rust": {
        "fn": ("Function", "fn ${1:name}(${2}) {\n\t${0}\n}"),
        "pfn": ("Public function", "pub fn ${1:name}(${2}) -> ${3:()} {\n\t${0}\n}"),
        "test": ("Test", "#[test]\nfn ${1:name}() {\n\t${0}\n}"),
        "impl": ("impl", "impl ${1:Type} {\n\t${0}\n}"),
        "match": ("match", "match ${1:value} {\n\t${2:_} => ${0},\n}"),
        "for": ("Loop over something", "for ${1:item} in ${2:items} {\n\t${0}\n}"),
        "pl": ("Print", "println!(\"${1:{}}\", ${2});${0}"),
    },
    "Go": {
        "func": ("Function", "func ${1:name}(${2}) ${3}{\n\t${0}\n}"),
        "iferr": ("If there's an error", "if err != nil {\n\treturn ${1:err}\n}${0}"),
        "for": ("Loop over something", "for ${1:_}, ${2:item} := range ${3:items} {\n\t${0}\n}"),
        "main": ("A program's start", "func main() {\n\t${0}\n}"),
        "test": ("Test", "func Test${1:Name}(t *testing.T) {\n\t${0}\n}"),
        "pf": ("Print", "fmt.Println(${1})${0}"),
    },
    "Shell": {
        "sh": ("Start of a script", "#!/usr/bin/env bash\nset -euo pipefail\n\n${0}"),
        "if": ("If", "if [[ ${1:condition} ]]; then\n\t${0}\nfi"),
        "for": ("Loop over something", "for ${1:item} in ${2:items}; do\n\t${0}\ndone"),
        "fn": ("Function", "${1:name}() {\n\t${0}\n}"),
    },
    "Markdown": {
        "link": ("Link", "[${1:text}](${2:https://})${0}"),
        "img": ("Picture", "![${1:what it shows}](${2:path})${0}"),
        "code": ("Code block", "```${1:python}\n${0}\n```"),
        "table": ("Table", "| ${1:Heading} | ${2:Heading} |\n|---|---|\n| ${3} | ${0} |"),
        "todo": ("Task", "- [ ] ${0}"),
    },
    "HTML": {
        "html": ("A page", "<!DOCTYPE html>\n<html lang=\"${1:en}\">\n<head>\n\t<meta charset=\"utf-8\">\n\t<title>${2:Title}</title>\n</head>\n<body>\n\t${0}\n</body>\n</html>"),
        "a": ("Link", "<a href=\"${1}\">${0}</a>"),
        "div": ("Box", "<div class=\"${1}\">\n\t${0}\n</div>"),
    },
}
SNIPPETS["TypeScript"] = dict(SNIPPETS["JavaScript"], intf=("Interface", "interface ${1:Name} {\n\t${2:field}: ${3:string};${0}\n}"))
SNIPPETS["C++"] = dict(SNIPPETS["C"], cls=("Class", "class ${1:Name} {\npublic:\n\t${1:Name}();\n\t${0}\n};"),
                       cout=("Print", "std::cout << ${1} << std::endl;${0}"))


def snippet_parse(body: str, unit: str = "    ", indent: str = "") -> dict:
    """A snippet's body -> {text, stops}: the text to put in (tabs as the file's indentation, lines after the first
    at the line's own indent), and where to type, in order: [[start, end], …] with the end ($0) last. A number used
    again (${1:i} three times) is the same stop: those places are listed with it in "same"."""
    out, stops, i, n = [], {}, 0, len(body)
    text_len = 0

    def put(s):
        nonlocal text_len
        out.append(s)
        text_len += len(s)
    while i < n:
        ch = body[i]
        if ch == "\\" and i + 1 < n and body[i + 1] in "$}\\":
            put(body[i + 1])
            i += 2
            continue
        if ch == "\n":
            put("\n" + indent)
            i += 1
            continue
        if ch == "\t":
            put(unit)
            i += 1
            continue
        if ch == "$":
            m = re.match(r"\$(\d+)|\$\{(\d+)(?::((?:[^}\\]|\\.)*))?\}|\$\{(\d+)\|([^|]*)\|\}", body[i:])
            if m:
                num = int(m.group(1) or m.group(2) or m.group(4))
                default = m.group(3) if m.group(2) else (m.group(5).split(",")[0] if m.group(4) else "")
                default = re.sub(r"\\(.)", r"\1", default or "")
                if num in stops and not default:
                    default = stops[num]["text"]
                start = text_len
                put(default)
                stops.setdefault(num, {"text": default, "at": []})["at"].append([start, text_len])
                i += m.end()
                continue
        put(ch)
        i += 1
    order = sorted(k for k in stops if k > 0) + ([0] if 0 in stops else [])
    text = "".join(out)
    if 0 not in stops:
        order.append(0)
        stops[0] = {"text": "", "at": [[len(text), len(text)]]}
    return {"text": text, "stops": [stops[k]["at"][0] for k in order], "same": [stops[k]["at"][1:] for k in order]}


def snippet_items(lang: str, prefix: str) -> list:
    """Completion items for the snippets whose names start like the word being typed."""
    out = []
    for name, (what, body) in (SNIPPETS.get(lang) or {}).items():
        if prefix and name.startswith(prefix):
            out.append({"label": name, "insert": body, "snippet": body, "detail": what, "kind": 15, "sort": "~" + name})
    return out


# ---------------------------------------------------------------- merge conflicts
def conflicts(text: str) -> list:
    """The conflicts Git left in a file: [{start, mid, base, end, ours, theirs}] as line numbers (base when
    merge.conflictStyle is diff3), and what each side said."""
    lines, out, k = text.split("\n"), [], 0
    while k < len(lines):
        if lines[k].startswith("<<<<<<<"):
            start, base, mid, end = k, -1, -1, -1
            j = k + 1
            while j < len(lines):
                if lines[j].startswith("|||||||") and mid < 0:
                    base = j
                elif lines[j].startswith("=======") and mid < 0:
                    mid = j
                elif lines[j].startswith(">>>>>>>") and mid >= 0:
                    end = j
                    break
                elif lines[j].startswith("<<<<<<<"):
                    break
                j += 1
            if mid > 0 and end > 0:
                ours = lines[start + 1:(base if base > 0 else mid)]
                out.append({"start": start, "base": base, "mid": mid, "end": end, "ours": "\n".join(ours), "theirs": "\n".join(lines[mid + 1:end]),
                            "oursName": lines[start][7:].strip() or "ours", "theirsName": lines[end][7:].strip() or "theirs"})
                k = end + 1
                continue
        k += 1
    return out


def resolve_text(text: str, which: str, only: int = -1) -> tuple:
    """The file with its conflicts (all, or number `only`) settled: "ours", "theirs" or "both" (ours, then theirs).
    -> (new text, how many were settled)."""
    lines = text.split("\n")
    found = conflicts(text)
    done = 0
    for n, c in reversed(list(enumerate(found))):
        if only >= 0 and n != only:
            continue
        ours = lines[c["start"] + 1:(c["base"] if c["base"] > 0 else c["mid"])]
        theirs = lines[c["mid"] + 1:c["end"]]
        keep = ours if which == "ours" else theirs if which == "theirs" else ours + theirs
        lines[c["start"]:c["end"] + 1] = keep
        done += 1
    return "\n".join(lines), done


# ---------------------------------------------------------------- scopes: the outline and sticky scroll
def scopes(text: str, symbols: list) -> list:
    """Each symbol with where it ends: the line before the next one that isn't blank or a comment and is no more
    indented than its own first line (a closing brace on its own still belongs to it)."""
    lines = text.split("\n")
    ind = []
    for l in lines:
        s = l.lstrip()
        ind.append(len(l.expandtabs(4)) - len(s.expandtabs(4)) if s else -1)
    out = []
    for sym in symbols:
        k = sym["line"]
        if not 0 <= k < len(lines):
            continue
        base = ind[k] if ind[k] >= 0 else 0
        end = k
        j = k + 1
        while j < len(lines):
            s = lines[j].strip()
            if ind[j] >= 0 and ind[j] <= base and not s.startswith(("#", "//")):
                if s[:1] in ")]}" or s.startswith(("end", "fi", "done", "esac")):
                    end = j
                break
            if ind[j] >= 0:
                end = j
            j += 1
        out.append(dict(sym, end=end, indent=base))
    return out


def enclosing(scoped: list, line: int) -> list:
    """The scopes a line is inside, outermost first (for sticky scroll)."""
    inside = [s for s in scoped if s["line"] < line <= s["end"]]
    inside.sort(key=lambda s: (s["indent"], s["line"]))
    return inside


# ---------------------------------------------------------------- quick fixes for Python
STD = set(getattr(sys, "stdlib_module_names", ())) | {"os", "sys", "re", "json", "math", "time", "datetime", "random", "subprocess", "pathlib", "typing",
                                                    "collections", "itertools", "functools", "shutil", "tempfile", "logging", "argparse", "dataclasses"}
FROM = {"Path": "pathlib", "dataclass": "dataclasses", "field": "dataclasses", "defaultdict": "collections", "Counter": "collections",
        "OrderedDict": "collections", "namedtuple": "collections", "deque": "collections", "partial": "functools", "lru_cache": "functools",
        "wraps": "functools", "reduce": "functools", "datetime": "datetime", "date": "datetime", "timedelta": "datetime", "Optional": "typing",
        "List": "typing", "Dict": "typing", "Any": "typing", "Union": "typing", "Callable": "typing", "Iterable": "typing", "Enum": "enum",
        "ABC": "abc", "abstractmethod": "abc", "contextmanager": "contextlib", "suppress": "contextlib", "sleep": "time", "glob": "glob",
        "pprint": "pprint", "dedent": "textwrap", "deepcopy": "copy", "copy": "copy", "sqrt": "math", "pi": "math", "floor": "math", "ceil": "math"}


def _import_line(lines: list) -> int:
    """Where a new import goes: after the module's docstring, __future__ imports and the imports already there."""
    k, n = 0, len(lines)
    while k < n and (not lines[k].strip() or lines[k].startswith("#!") or lines[k].startswith("# -*-")):
        k += 1
    if k < n and lines[k].lstrip().startswith(('"""', "'''")):
        q = lines[k].lstrip()[:3]
        if lines[k].count(q) >= 2 and len(lines[k].strip()) > 3:
            k += 1
        else:
            k += 1
            while k < n and q not in lines[k]:
                k += 1
            k += 1
    last = -1
    for j in range(k, min(n, k + 400)):
        s = lines[j]
        if re.match(r"(import\s|from\s+\S+\s+import\s)", s):
            last = j
            while last + 1 < n and (lines[last].rstrip().endswith(("(", ",", "\\")) and not lines[last].rstrip().endswith(")")):
                last += 1
        elif s.strip() and not s.startswith("#") and last >= 0:
            break
        elif s.strip() and not s.startswith(("#", "import", "from")) and last < 0:
            break
    return last + 1 if last >= 0 else k


def python_fixes(text: str, problems: list, line: int, modules: set = frozenset()) -> list:
    """Quick fixes for the problems on a line: [{title, edits: [[start line, start col, end line, end col, text]]}].
    "'os' imported but unused": take it out (the whole line, or just that name from a list). "undefined name 'X'":
    import it, when it's a standard module, a common name from one, or a module of the project."""
    lines, out = text.split("\n"), []
    for p in problems:
        if not p["line"] <= line <= p.get("endLine", p["line"]):
            continue
        msg = p.get("message", "")
        m = re.search(r"'([\w.]+)(?: as \w+)?' imported but unused", msg)
        if m and p["line"] < len(lines):
            full = m.group(1)
            row = lines[p["line"]]
            name = full.split(".")[-1] if re.match(r"\s*from\s", row) else full
            fm = re.match(r"(\s*from\s+\S+\s+import\s+)(\(?)(.*?)(\)?)\s*$", row)
            if fm and "," in fm.group(3):
                names = [x.strip() for x in fm.group(3).split(",") if x.strip()]
                keep = [x for x in names if x.split(" as ")[0].strip() != name]
                if len(keep) < len(names):
                    new = fm.group(1) + fm.group(2) + ", ".join(keep) + fm.group(4)
                    out.append({"title": f"Take out the unused import of {name}", "edits": [[p["line"], 0, p["line"], len(row), new]]})
                    continue
            im = re.match(r"(\s*import\s+)(.*)$", row)
            if im and "," in im.group(2):
                names = [x.strip() for x in im.group(2).split(",")]
                keep = [x for x in names if x.split(" as ")[0].strip() != full]
                out.append({"title": f"Take out the unused import of {full}", "edits": [[p["line"], 0, p["line"], len(row), im.group(1) + ", ".join(keep)]]})
                continue
            out.append({"title": f"Take out the unused import of {name}", "edits": [[p["line"], 0, p["line"] + 1, 0, ""]]})
            continue
        m = re.search(r"undefined name '(\w+)'", msg)
        if m:
            name = m.group(1)
            at = _import_line(lines)
            if name in STD or name in modules:
                out.append({"title": f"import {name}", "edits": [[at, 0, at, 0, f"import {name}\n"]]})
            if name in FROM:
                mod = FROM[name]
                existing = next((k for k, l in enumerate(lines) if re.match(rf"from\s+{re.escape(mod)}\s+import\s+[^(]*$", l)), -1)
                if existing >= 0:
                    row = lines[existing]
                    out.append({"title": f"Add {name} to “{row.strip()}”", "edits": [[existing, 0, existing, len(row), row.rstrip() + f", {name}"]]})
                else:
                    out.append({"title": f"from {mod} import {name}", "edits": [[at, 0, at, 0, f"from {mod} import {name}\n"]]})
    seen, unique = set(), []
    for f in out:
        if f["title"] not in seen:
            seen.add(f["title"])
            unique.append(f)
    return unique


def edits_to_offsets(text: str, edits: list) -> list:
    """[[line, col, end line, end col, text]] -> [[start, end, text]] as offsets into text."""
    starts, k = [0], 0
    for l in text.split("\n"):
        k += len(l) + 1
        starts.append(k)
    last = len(text)

    def at(line, col):
        return min(last, starts[min(line, len(starts) - 1)] + col) if line < len(starts) - 1 else last
    return [[at(a, b), at(c, d), t] for a, b, c, d, t in edits]


def u16(text: str, offset: int) -> int:
    """A character offset as Qt counts it (UTF-16: characters past U+FFFF are two)."""
    head = text[:offset]
    return offset + sum(1 for ch in head if ord(ch) > 0xFFFF)


def trim_text(text: str, lang: str) -> str:
    """Spaces at the ends of lines taken away (not Markdown's two-space line breaks) and one newline at the end."""
    if not text:
        return text
    if lang == "Markdown":
        lines = [l.rstrip() + "  " if l.endswith("  ") and l.strip() else l.rstrip() for l in text.split("\n")]
    else:
        lines = [l.rstrip() for l in text.split("\n")]
    while len(lines) > 1 and lines[-1] == "" and lines[-2] == "":
        lines.pop()
    out = "\n".join(lines)
    return out if out.endswith("\n") else out + "\n"
