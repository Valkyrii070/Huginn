"""Money: where your money goes, what's set aside, and a safety net for the months that go wrong.

The desktop side of Rune. Everything stays on this computer, in one file only you can read (no bank log-ins, no
servers): accounts are added by hand and their activity comes in from the statement files banks let you download
(CSV, OFX or QFX). Spending is sorted into categories by simple rules you can teach, and a few plain-spoken notes
say what changed, what repeats every month, and how many months of spending your savings would cover."""
import csv
import datetime as dt
import io
import json
import os
import re
import statistics
import uuid
from pathlib import Path

from PySide6.QtCore import Property, QLocale, QObject, QStandardPaths, QUrl, Signal, Slot

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn"
CATEGORIES = ["Income", "Housing", "Bills", "Groceries", "Eating out", "Transport", "Shopping", "Subscriptions", "Health", "Fun", "Savings", "Transfers", "Other"]
COLOURS = {"Income": "#3DDC6E", "Housing": "#7C9CFF", "Bills": "#22B8CF", "Groceries": "#FFC53D", "Eating out": "#FF7A59", "Transport": "#A855F7",
           "Shopping": "#FF4FC3", "Subscriptions": "#E86BD8", "Health": "#FB7185", "Fun": "#F59E0B", "Savings": "#10B981", "Transfers": "#94A3B8", "Other": "#CBD5E1"}
NOT_SPENDING = {"Income", "Savings", "Transfers"}
RULES = {          # words in a statement line -> category; your own rules are checked first
    "Income": ["salary", "payroll", "paycheck", "paycheque", "direct dep", "wages", "lønn", "lön", "gehalt"],
    "Housing": ["rent", "mortgage", "landlord", "hoa ", "property mgmt"],
    "Bills": ["electric", "energy", "water bill", "utility", "internet", "broadband", "comcast", "xfinity", "verizon", "at&t", "t-mobile", "vodafone", "insurance", "council tax", "telenor"],
    "Groceries": ["grocery", "groceries", "supermarket", "tesco", "sainsbury", "aldi", "lidl", "kroger", "safeway", "whole foods", "trader joe", "walmart", "costco", "rema", "kiwi", "coop", "ica ", "meny", "albert heijn", "edeka", "rewe", "carrefour"],
    "Eating out": ["restaurant", "cafe", "café", "coffee", "starbucks", "mcdonald", "burger", "pizza", "kebab", "sushi", "bar ", "pub ", "uber eats", "doordash", "deliveroo", "grubhub", "just eat", "foodora", "wolt"],
    "Transport": ["uber", "lyft", "taxi", "shell", "bp ", "exxon", "chevron", "esso", "circle k", "fuel", "petrol", "parking", "transit", "train", "rail", "metro", "bus ", "ruter", "vy ", "airline"],
    "Subscriptions": ["netflix", "spotify", "apple.com/bill", "icloud", "google storage", "youtube", "disney", "hulu", "hbo", "prime video", "amazon prime", "patreon", "xbox", "playstation", "steam"],
    "Shopping": ["amazon", "target", "ikea", "best buy", "ebay", "etsy", "zara", "h&m", "elkjøp", "clas ohlson"],
    "Health": ["pharmacy", "apotek", "cvs", "walgreens", "doctor", "dental", "dentist", "clinic", "hospital", "optician", "gym", "fitness"],
    "Fun": ["cinema", "theatre", "theater", "concert", "ticketmaster", "museum", "games", "bowling"],
    "Savings": ["to savings", "savings transfer", "save the change"],
    "Transfers": ["transfer", "zelle", "venmo", "vipps", "swish", "paypal", "revolut", "wise.com"],
}
DATE_HEADS = ("date", "transaction date", "posted", "posting date", "booking date", "value date", "datum", "dato", "trans. date")
TEXT_HEADS = ("description", "payee", "merchant", "name", "details", "narrative", "memo", "text", "transaction", "beskrivelse", "tekst", "verwendungszweck", "reference")
AMOUNT_HEADS = ("amount", "value", "sum", "beløp", "belopp", "betrag", "transaction amount")
OUT_HEADS = ("debit", "withdrawal", "withdrawals", "money out", "paid out", "out", "ut")
IN_HEADS = ("credit", "deposit", "deposits", "money in", "paid in", "in", "inn")


# ============================================================================================= reading statements
def parse_amount(text: str) -> int:
    """'1,234.56' '-12.30' '(12.30)' '12,30' '1.234,56 kr' '$ -5' -> cents. Raises ValueError."""
    s = str(text or "").strip()
    negative = s.startswith("(") and s.endswith(")") or "-" in s or "−" in s or s.lower().endswith(" dr")
    s = re.sub(r"[^\d.,]", "", s)
    if not s or not re.search(r"\d", s):
        raise ValueError("no number")
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        decimal = "," if re.search(r",\d{1,2}$", s) else ""
    elif "." in s:
        decimal = "." if re.search(r"\.\d{1,2}$", s) or s.count(".") == 1 and not re.search(r"\.\d{3}$", s) else ""
    else:
        decimal = ""
    whole, _, frac = s.rpartition(decimal) if decimal else (s, "", "")
    whole = re.sub(r"[.,]", "", whole) or "0"
    cents = int(whole) * 100 + int((frac + "00")[:2] if frac else 0)
    return -cents if negative else cents


def parse_date(text: str, day_first: bool = False):
    s = str(text or "").strip()
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s) or re.match(r"(\d{4})(\d\d)(\d\d)", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.match(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2,4})", s)
        if m:
            a, b, y = (int(x) for x in m.groups())
            d, mo = (a, b) if day_first else (b, a)
            y += 2000 if y < 100 else 0
        else:
            try:
                return dt.datetime.strptime(s[:11].strip(), "%d %b %Y").date()
            except ValueError:
                try:
                    return dt.datetime.strptime(s[:12].strip(), "%b %d, %Y").date()
                except ValueError:
                    return None
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _pick(heads: list, names: tuple):
    for want in names:
        for i, h in enumerate(heads):
            if h == want:
                return i
    for want in names:
        for i, h in enumerate(heads):
            if len(want) > 3 and want in h:
                return i
    return None


def read_csv(text: str) -> list:
    """A bank's CSV export as [{date, desc, amount}]. Raises ValueError when the columns can't be told apart."""
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    start = next((n for n, r in enumerate(rows[:15]) if _pick([c.strip().lower() for c in r], DATE_HEADS) is not None), None)
    if start is None:
        raise ValueError("Couldn't find the date column. The file needs a header row (Date, Description, Amount…).")
    heads = [c.strip().lower() for c in rows[start]]
    di, ti = _pick(heads, DATE_HEADS), _pick(heads, TEXT_HEADS)
    ai, oi, ii = _pick(heads, AMOUNT_HEADS), _pick(heads, OUT_HEADS), _pick(heads, IN_HEADS)
    if ai is not None and (ai in (oi, ii) or re.search(r"debit|credit|withdraw|deposit|\bout\b|\bin\b|paid", heads[ai])):
        ai = None                                    # "Debit Amount" / "Credit Amount": two columns, not one
    if ai is None and oi is None and ii is None:
        raise ValueError("Couldn't find the amounts. The file needs an Amount column, or Money in / Money out.")
    body = rows[start + 1:]
    firsts = [re.match(r"\s*(\d{1,2})[-/. ](\d{1,2})[-/. ]\d{2,4}", r[di]) for r in body if di < len(r)]
    day_first = any(m and int(m.group(1)) > 12 for m in firsts) or (not any(m and int(m.group(2)) > 12 for m in firsts) and QLocale().country() not in (QLocale.UnitedStates, QLocale.Philippines))
    out = []
    for r in body:
        if di >= len(r):
            continue
        day = parse_date(r[di], day_first)
        if not day:
            continue
        try:
            if ai is not None and ai < len(r) and r[ai].strip():
                cents = parse_amount(r[ai])
            else:
                spent = parse_amount(r[oi]) if oi is not None and oi < len(r) and r[oi].strip() else 0
                got = parse_amount(r[ii]) if ii is not None and ii < len(r) and r[ii].strip() else 0
                cents = abs(got) - abs(spent)
        except ValueError:
            continue
        desc = " ".join((r[ti] if ti is not None and ti < len(r) else "").split())
        out.append({"date": day.isoformat(), "desc": desc[:200] or "(no description)", "amount": cents})
    if not out:
        raise ValueError("No transactions could be read from that file.")
    return out


def read_ofx(text: str) -> list:
    """OFX / QFX (Quicken, Money and most banks' "download for Quicken"), SGML or XML."""
    out = []
    for block in re.findall(r"(?is)<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", text):
        def field(name):
            m = re.search(rf"(?is)<{name}>\s*([^<\r\n]*)", block)
            return m.group(1).strip() if m else ""
        day = parse_date(field("DTPOSTED")[:8])
        try:
            cents = parse_amount(field("TRNAMT"))
        except ValueError:
            continue
        if not day:
            continue
        desc = field("NAME") or field("MEMO")
        out.append({"date": day.isoformat(), "desc": " ".join(desc.split())[:200] or "(no description)", "amount": cents, "fitid": field("FITID"),
                    "note": field("MEMO") if field("NAME") else ""})
    if not out:
        raise ValueError("No transactions were found in that file.")
    return out


def merchant(desc: str) -> str:
    """'CARD PAYMENT TO TESCO STORES 3297 ON 12-11-26' -> 'Tesco Stores'."""
    s = re.sub(r"(?i)^(card payment to|payment to|pos( purchase)?|purchase( at)?|debit card purchase|visa|mastercard|contactless|dd|direct debit|so|bgc|fpi|fpo)\b[\s:*-]*", "", desc or "")
    s = re.sub(r"(?i)\b(on|ref|reference)\b.*$", "", s)
    s = re.sub(r"[#*]\S*|\b\w*\d[\w\-/.:]*\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -*.,")
    if s.isupper():
        s = re.sub(r"(^|\s)(\w)", lambda m: m.group(1) + m.group(2).upper(), s.lower())
    return s[:60] or desc[:60]


def guess_category(desc: str, cents: int, mine: dict) -> str:
    low = f" {desc.lower()} "
    for word, cat in sorted(mine.items(), key=lambda kv: -len(kv[0])):
        if word and word in low:
            return cat
    for cat, words in RULES.items():
        if any(w in low for w in words):
            if cat == "Income" and cents < 0:
                continue
            return cat
    return "Income" if cents > 0 else "Other"


def recurring(txns: list, today: dt.date = None) -> list:
    """Charges that come back every month at about the same amount: [{name, amount, last, count}]."""
    today = today or dt.date.today()
    groups = {}
    for t in txns:
        if t["amount"] < 0 and t.get("category") not in NOT_SPENDING:
            groups.setdefault(merchant(t["desc"]).lower(), []).append(t)
    out = []
    for key, rows in groups.items():
        rows = sorted(rows, key=lambda t: t["date"])
        if len(rows) < 3:
            continue
        days = [dt.date.fromisoformat(t["date"]) for t in rows]
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        amounts = [-t["amount"] for t in rows]
        typical = statistics.median(amounts)
        if all(25 <= g <= 36 for g in gaps[-3:]) and all(abs(a - typical) <= typical * 0.12 + 50 for a in amounts[-3:]) and (today - days[-1]).days <= 40:
            out.append({"name": merchant(rows[-1]["desc"]), "amount": int(typical), "last": days[-1].isoformat(), "count": len(rows)})
    return sorted(out, key=lambda r: -r["amount"])


def month_of(day: str) -> str:
    return day[:7]


def months_back(today: dt.date, n: int) -> list:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if not m:
            y, m = y - 1, 12
    return list(reversed(out))


# ============================================================================================= the app
class Money(QObject):
    changed = Signal()
    said = Signal(str, bool)

    def __init__(self, demo: bool = False, target=None):
        super().__init__()
        self._demo, self._file = demo, DATA_HOME / "money.json"
        self._accounts, self._txns, self._budgets, self._goals, self._rules = [], [], {}, [], {}
        self._view, self._query, self._account, self._category = "overview", "", "", ""
        locale = QLocale()
        self._symbol = locale.currencySymbol(QLocale.CurrencySymbol) or "$"
        self._today = dt.date.today()
        if demo:
            self._demo_fill()
        else:
            self._load()
            if target and Path(str(target)).is_file():
                self.importFile(str(target), "")

    # ---- keeping (a file only you can read)
    def _load(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self._accounts = [a for a in data.get("accounts", []) if isinstance(a, dict) and a.get("id")]
        self._txns = [t for t in data.get("txns", []) if isinstance(t, dict) and t.get("id") and isinstance(t.get("amount"), int)]
        self._budgets = {k: int(v) for k, v in (data.get("budgets") or {}).items() if k in CATEGORIES and isinstance(v, (int, float)) and v > 0}
        self._goals = [g for g in data.get("goals", []) if isinstance(g, dict) and g.get("id")]
        self._rules = {k: v for k, v in (data.get("rules") or {}).items() if v in CATEGORIES}
        self._symbol = data.get("symbol") or self._symbol

    def _keep(self) -> None:
        if self._demo:
            return
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            part = self._file.with_name(".money.json.saving")
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump({"accounts": self._accounts, "txns": self._txns, "budgets": self._budgets, "goals": self._goals, "rules": self._rules, "symbol": self._symbol}, out)
            os.replace(part, self._file)
        except OSError as err:
            self.said.emit(f"Couldn't save: {err.strerror or err}", True)

    def _demo_fill(self) -> None:
        import random
        rnd = random.Random(7)
        self._symbol = "$"
        self._accounts = [{"id": "a1", "name": "Everyday", "kind": "spending", "opening": 184000}, {"id": "a2", "name": "Rainy-day savings", "kind": "savings", "opening": 420000}]
        today = self._today
        rows = []
        for back in range(5, -1, -1):
            y, m = today.year, today.month - back
            while m < 1:
                y, m = y - 1, m + 12
            def day(d):
                return dt.date(y, m, min(d, 28))
            if day(1) > today:
                continue
            plan = [(1, "PAYROLL NORDLYS DESIGN AS", 412000), (2, "RENT TO HARBOUR HOMES", -142000), (5, "NETFLIX.COM", -1549), (6, "SPOTIFY P1A2B3", -1199),
                    (9, "CITY ELECTRIC CO", -rnd.randint(6800, 9400)), (12, "VERIZON WIRELESS", -6500), (15, "TRANSFER TO SAVINGS", -40000)]
            plan += [(d, rnd.choice(["TESCO STORES 3297", "ALDI 112", "TRADER JOE'S #551"]), -rnd.randint(3200, 9800)) for d in (3, 8, 13, 19, 24)]
            plan += [(d, rnd.choice(["STARBUCKS 0921", "BLUE DOOR CAFE", "PIZZA NAPOLI"]), -rnd.randint(450, 3600 if back else 5200)) for d in (4, 7, 11, 16, 21, 26)]
            plan += [(d, rnd.choice(["SHELL OIL 5739", "CITY TRANSIT"]), -rnd.randint(1800, 5200)) for d in (10, 22)]
            plan += [(18, "AMAZON MKTPLACE", -rnd.randint(1500, 9000)), (20, "CVS PHARMACY", -rnd.randint(900, 2600))]
            for d, desc, cents in plan:
                if day(d) <= today:
                    rows.append({"id": uuid.uuid4().hex[:12], "account": "a1", "date": day(d).isoformat(), "desc": desc, "amount": cents, "category": guess_category(desc, cents, {})})
                    if desc == "TRANSFER TO SAVINGS":
                        rows.append({"id": uuid.uuid4().hex[:12], "account": "a2", "date": day(d).isoformat(), "desc": "TRANSFER FROM EVERYDAY", "amount": 40000, "category": "Savings"})
        for r in rows:
            if r["desc"] == "TRANSFER TO SAVINGS":
                r["category"] = "Savings"
        self._txns = rows
        self._budgets = {"Groceries": 35000, "Eating out": 12000, "Transport": 10000, "Shopping": 8000}
        self._goals = [{"id": "g1", "name": "Trip to Tromsø", "target": 250000, "saved": 96000, "due": f"{today.year + 1}-02-15"},
                       {"id": "g2", "name": "New laptop", "target": 180000, "saved": 151000, "due": ""}]

    # ---- sums
    def fmt(self, cents: int, sign: bool = False) -> str:
        whole = QLocale().toString(abs(cents) / 100, "f", 2)
        text = f"{self._symbol}{whole}" if len(self._symbol) <= 1 else f"{whole} {self._symbol}"
        return ("−" if cents < 0 else "+" if sign and cents > 0 else "") + text

    def _balance(self, aid: str) -> int:
        acc = next((a for a in self._accounts if a["id"] == aid), {})
        return int(acc.get("opening", 0)) + sum(t["amount"] for t in self._txns if t["account"] == aid)

    def _spent(self, month: str, category: str = "") -> int:
        return -sum(t["amount"] for t in self._txns if month_of(t["date"]) == month and t["amount"] < 0 and t.get("category") not in NOT_SPENDING
                    and (not category or t.get("category") == category))

    def _monthly_spending(self) -> int:
        """The usual month's spending: the average of the last three full months (fewer if that's all there is)."""
        months = months_back(self._today, 4)[:-1]
        full = [self._spent(m) for m in months if any(month_of(t["date"]) == m for t in self._txns)]
        return int(sum(full) / len(full)) if full else self._spent(months_back(self._today, 1)[0])

    def _savings(self) -> int:
        return sum(self._balance(a["id"]) for a in self._accounts if a.get("kind") == "savings")

    # ---- what QML sees
    def _get_accounts(self) -> list:
        return [{"id": a["id"], "name": a["name"], "kind": a.get("kind", "spending"), "balance": self.fmt(self._balance(a["id"])), "cents": self._balance(a["id"]),
                 "count": sum(1 for t in self._txns if t["account"] == a["id"])} for a in self._accounts]

    def _get_overview(self) -> dict:
        month = months_back(self._today, 1)[0]
        income = sum(t["amount"] for t in self._txns if month_of(t["date"]) == month and t["amount"] > 0 and t.get("category") == "Income")
        spent = self._spent(month)
        usual = self._monthly_spending()
        savings = self._savings()
        cover = savings / usual if usual > 0 else 0
        total = sum(self._balance(a["id"]) for a in self._accounts)
        return {"total": self.fmt(total), "spent": self.fmt(spent), "income": self.fmt(income), "left": self.fmt(income - spent), "leftCents": income - spent,
                "month": self._today.strftime("%B"), "savings": self.fmt(savings), "cover": round(cover, 1), "coverShare": min(1.0, cover / 3) if cover else 0,
                "usual": self.fmt(usual), "target": self.fmt(usual * 3), "hasData": bool(self._txns), "hasAccounts": bool(self._accounts)}

    def _get_categories(self) -> list:
        """This month's spending by category, with budgets."""
        month = months_back(self._today, 1)[0]
        days_in = (dt.date(self._today.year + self._today.month // 12, self._today.month % 12 + 1, 1) - dt.timedelta(days=1)).day
        share_of_month = self._today.day / days_in
        out = []
        for cat in CATEGORIES:
            if cat in NOT_SPENDING:
                continue
            spent, budget = self._spent(month, cat), self._budgets.get(cat, 0)
            if not spent and not budget:
                continue
            out.append({"name": cat, "colour": COLOURS[cat], "spent": self.fmt(spent), "cents": spent, "budget": self.fmt(budget) if budget else "", "budgetCents": budget,
                        "share": spent / budget if budget else 0, "over": bool(budget) and spent > budget, "pace": bool(budget) and spent > budget * share_of_month * 1.15 and spent <= budget})
        biggest = max([c["cents"] for c in out] + [1])
        for c in out:
            c["bar"] = c["cents"] / biggest
        return sorted(out, key=lambda c: -c["cents"])

    def _get_months(self) -> list:
        """Six months of money in and money out, for the bars."""
        rows = []
        for m in months_back(self._today, 6):
            got = sum(t["amount"] for t in self._txns if month_of(t["date"]) == m and t["amount"] > 0 and t.get("category") == "Income")
            rows.append({"month": dt.date.fromisoformat(m + "-01").strftime("%b"), "in": got, "out": self._spent(m), "inText": self.fmt(got), "outText": self.fmt(self._spent(m))})
        top = max([max(r["in"], r["out"]) for r in rows] + [1])
        for r in rows:
            r["inBar"], r["outBar"] = r["in"] / top, r["out"] / top
        return rows

    def _get_txns(self) -> list:
        words = self._query.lower().split()
        acc = {a["id"]: a["name"] for a in self._accounts}
        rows = [t for t in self._txns if (not self._account or t["account"] == self._account) and (not self._category or t.get("category") == self._category)
                and all(w in (t["desc"] + " " + t.get("note", "") + " " + t.get("category", "")).lower() for w in words)]
        rows.sort(key=lambda t: (t["date"], t["id"]), reverse=True)
        return [{"id": t["id"], "date": dt.date.fromisoformat(t["date"]).strftime("%-d %b"), "day": t["date"], "name": merchant(t["desc"]), "desc": t["desc"], "amount": self.fmt(t["amount"], True),
                 "cents": t["amount"], "category": t.get("category", "Other"), "colour": COLOURS.get(t.get("category", "Other"), "#CBD5E1"), "account": acc.get(t["account"], "")} for t in rows[:800]]

    def _get_goals(self) -> list:
        out = []
        for g in self._goals:
            target, saved = int(g.get("target", 0)), int(g.get("saved", 0))
            months = ""
            if g.get("due") and saved < target:
                try:
                    due = dt.date.fromisoformat(g["due"])
                    n = max(1, (due.year - self._today.year) * 12 + due.month - self._today.month)
                    months = f"{self.fmt((target - saved) // n)} a month to make it by {due.strftime('%B %Y')}"
                except ValueError:
                    pass
            out.append({"id": g["id"], "name": g["name"], "target": self.fmt(target), "saved": self.fmt(saved), "share": min(1.0, saved / target) if target else 0,
                        "done": saved >= target > 0, "plan": months, "due": g.get("due", "")})
        return out

    def _get_notes(self) -> list:
        """The guidance: a few short, plain notes, most useful first."""
        notes = []
        if not self._txns:
            return notes
        o = self._get_overview()
        usual = self._monthly_spending()
        if usual > 0:
            cover = self._savings() / usual
            if cover < 1:
                notes.append({"kind": "safety", "title": "Build a safety net", "text": f"Your savings would cover {cover:.1f} months of your usual spending. Aim for one month first ({self.fmt(usual)}), then three."})
            elif cover < 3:
                notes.append({"kind": "safety", "title": f"{cover:.1f} months covered", "text": f"Your savings would carry you {cover:.1f} months. Three months ({self.fmt(usual * 3)}) is a sturdy safety net."})
            else:
                notes.append({"kind": "good", "title": f"{cover:.1f} months covered", "text": "Your savings would carry you through more than three months of usual spending. Well done."})
        month, last = months_back(self._today, 2)[1], months_back(self._today, 2)[0]
        day = self._today.day
        moves = []
        for cat in CATEGORIES:
            if cat in NOT_SPENDING:
                continue
            now = -sum(t["amount"] for t in self._txns if t["date"][:7] == month and int(t["date"][8:10]) <= day and t["amount"] < 0 and t.get("category") == cat)
            before = -sum(t["amount"] for t in self._txns if t["date"][:7] == last and int(t["date"][8:10]) <= day and t["amount"] < 0 and t.get("category") == cat)
            if before > 2000 and now > before * 1.25 and now - before > 1500:
                moves.append((now - before, cat, now, before))
        noted = None
        if moves:
            gap, cat, now, before = max(moves)
            noted = cat
            notes.append({"kind": "watch", "title": f"More on {cat.lower()}", "text": f"{self.fmt(now)} so far this month, against {self.fmt(before)} by this day last month."})
        for c in self._get_categories():
            if c["over"]:
                notes.append({"kind": "watch", "title": f"Over budget: {c['name'].lower()}", "text": f"{c['spent']} spent of {c['budget']}."})
            elif c["pace"] and c["name"] != noted:          # (one note a category: "more on" already says it)
                notes.append({"kind": "watch", "title": f"Going fast: {c['name'].lower()}", "text": f"{c['spent']} of {c['budget']} with the month not over."})
        subs = recurring(self._txns, self._today)
        if subs:
            total = sum(s["amount"] for s in subs)
            names = ", ".join(s["name"] for s in subs[:4]) + ("…" if len(subs) > 4 else "")
            notes.append({"kind": "repeat", "title": f"{len(subs)} monthly charges", "text": f"{self.fmt(total)} a month: {names}. Worth a look for any you no longer use."})
        if o["leftCents"] > 0 and self._today.day >= 20:
            notes.append({"kind": "good", "title": f"{o['left']} left this month", "text": "Moving some of it to savings now makes it count before the month ends."})
        return notes[:5]

    accounts = Property("QVariantList", _get_accounts, notify=changed)
    overview = Property("QVariantMap", _get_overview, notify=changed)
    categories = Property("QVariantList", _get_categories, notify=changed)
    months = Property("QVariantList", _get_months, notify=changed)
    txns = Property("QVariantList", _get_txns, notify=changed)
    goals = Property("QVariantList", _get_goals, notify=changed)
    notes = Property("QVariantList", _get_notes, notify=changed)
    subscriptions = Property("QVariantList", lambda self: [dict(s, amountText=self.fmt(s["amount"])) for s in recurring(self._txns, self._today)], notify=changed)
    view = Property(str, lambda self: self._view, notify=changed)
    allCategories = Property("QVariantList", lambda self: [{"name": c, "colour": COLOURS[c]} for c in CATEGORIES], constant=True)
    filterAccount = Property(str, lambda self: self._account, notify=changed)
    filterCategory = Property(str, lambda self: self._category, notify=changed)
    symbol = Property(str, lambda self: self._symbol, notify=changed)

    @Slot(str)
    def setView(self, name: str) -> None:
        self._view = name if name in ("overview", "activity", "plan") else "overview"
        self.changed.emit()

    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text
        self.changed.emit()

    @Slot(str, str)
    def filter(self, account: str, category: str) -> None:
        self._account = account if any(a["id"] == account for a in self._accounts) else ""
        self._category = category if category in CATEGORIES else ""
        self.changed.emit()

    # ---- accounts
    @Slot(str, str, str, result=str)
    def addAccount(self, name: str, kind: str, opening: str) -> str:
        name = " ".join(name.split())[:60]
        if not name:
            return "Give the account a name, like Everyday or Savings."
        try:
            cents = parse_amount(opening) if opening.strip() else 0
        except ValueError:
            return "The balance isn't a number."
        self._accounts.append({"id": uuid.uuid4().hex[:10], "name": name, "kind": "savings" if kind == "savings" else "spending", "opening": cents})
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str, str, str, result=str)
    def editAccount(self, aid: str, name: str, kind: str) -> str:
        acc = next((a for a in self._accounts if a["id"] == aid), None)
        name = " ".join(name.split())[:60]
        if not acc or not name:
            return "Give it a name."
        acc.update(name=name, kind="savings" if kind == "savings" else "spending")
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str)
    def removeAccount(self, aid: str) -> None:
        self._accounts = [a for a in self._accounts if a["id"] != aid]
        self._txns = [t for t in self._txns if t["account"] != aid]
        if self._account == aid:
            self._account = ""
        self._keep()
        self.changed.emit()

    @Slot(str, str, result=str)
    def setBalance(self, aid: str, text: str) -> str:
        """Match the bank: the balance today is this, so the starting balance is whatever makes it so."""
        acc = next((a for a in self._accounts if a["id"] == aid), None)
        try:
            want = parse_amount(text)
        except ValueError:
            return "That isn't an amount."
        if acc:
            acc["opening"] = want - sum(t["amount"] for t in self._txns if t["account"] == aid)
            self._keep()
            self.changed.emit()
        return ""

    # ---- statements
    @Slot(result="QVariantList")
    def statementChoices(self) -> list:
        out = []
        for folder in (Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or Path.home() / "Downloads"),
                       Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")):
            try:
                files = [p for p in folder.iterdir() if p.suffix.lower() in (".csv", ".ofx", ".qfx") and p.is_file()]
            except OSError:
                continue
            for p in sorted(files, key=lambda p: -p.stat().st_mtime)[:25]:
                out.append({"name": p.name, "path": str(p), "where": folder.name, "when": dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%-d %b")})
        return out

    @Slot(str, str)
    def importFile(self, path: str, aid: str) -> None:
        path = QUrl(path).toLocalFile() if str(path).startswith("file:") else str(path)
        try:
            raw = Path(path).read_bytes()[:30_000_000]
            text = raw.decode("utf-8") if not raw.startswith(b"\xff\xfe") else raw.decode("utf-16")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        except OSError as err:
            self.said.emit(f"Couldn't read it: {err.strerror or err}", True)
            return
        try:
            rows = read_ofx(text) if re.search(r"(?i)<OFX>|OFXHEADER", text[:3000]) else read_csv(text)
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if not aid or not any(a["id"] == aid for a in self._accounts):
            if not self._accounts:
                self._accounts.append({"id": uuid.uuid4().hex[:10], "name": "Everyday", "kind": "spending", "opening": 0})
            aid = self._accounts[0]["id"]
        seen = {(t["account"], t.get("fitid") or f"{t['date']}|{t['amount']}|{t['desc']}") for t in self._txns}
        added = 0
        for r in rows:
            key = (aid, r.get("fitid") or f"{r['date']}|{r['amount']}|{r['desc']}")
            if key in seen:
                continue
            seen.add(key)
            self._txns.append(dict(r, id=uuid.uuid4().hex[:12], account=aid, category=guess_category(r["desc"], r["amount"], self._rules)))
            added += 1
        self._keep()
        self.changed.emit()
        name = next(a["name"] for a in self._accounts if a["id"] == aid)
        skipped = len(rows) - added
        self.said.emit(f"Added {added} transactions to {name}." + (f" {skipped} were already here." if skipped else ""), False)

    # ---- teaching it
    @Slot(str, str, bool)
    def recategorise(self, tid: str, category: str, always: bool) -> None:
        t = next((x for x in self._txns if x["id"] == tid), None)
        if not t or category not in CATEGORIES:
            return
        t["category"] = category
        if always:
            word = merchant(t["desc"]).lower()
            if len(word) >= 3:
                self._rules[word] = category
                for other in self._txns:
                    if word in other["desc"].lower() and other["id"] != tid:
                        other["category"] = category
                self.said.emit(f"From now on, {merchant(t['desc'])} counts as {category}.", False)
        self._keep()
        self.changed.emit()

    @Slot(str, str, str, str, result=str)
    def addTxn(self, aid: str, day: str, desc: str, amount: str) -> str:
        """Cash spent, or anything the bank file doesn't have."""
        if not any(a["id"] == aid for a in self._accounts):
            return "Add an account first."
        when = parse_date(day) if day.strip() else self._today
        if not when:
            return "The date isn't right. Use 2026-11-14."
        try:
            cents = parse_amount(amount)
        except ValueError:
            return "The amount isn't a number. Use a minus for money going out, like -12.50."
        desc = " ".join(desc.split())[:200] or "Cash"
        self._txns.append({"id": uuid.uuid4().hex[:12], "account": aid, "date": when.isoformat(), "desc": desc, "amount": cents, "category": guess_category(desc, cents, self._rules)})
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str)
    def removeTxn(self, tid: str) -> None:
        self._txns = [t for t in self._txns if t["id"] != tid]
        self._keep()
        self.changed.emit()

    # ---- budgets and goals
    @Slot(str, str, result=str)
    def setBudget(self, category: str, amount: str) -> str:
        if category not in CATEGORIES or category in NOT_SPENDING:
            return "Pick a spending category."
        if not amount.strip():
            self._budgets.pop(category, None)
        else:
            try:
                cents = abs(parse_amount(amount))
            except ValueError:
                return "That isn't an amount."
            self._budgets[category] = cents
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str, str, str, result=str)
    def addGoal(self, name: str, target: str, due: str) -> str:
        name = " ".join(name.split())[:60]
        try:
            cents = abs(parse_amount(target))
        except ValueError:
            return "The amount isn't a number."
        if not name or not cents:
            return "Give the goal a name and an amount."
        day = parse_date(due) if due.strip() else None
        if due.strip() and not day:
            return "The date isn't right. Use 2027-06-01."
        self._goals.append({"id": uuid.uuid4().hex[:10], "name": name, "target": cents, "saved": 0, "due": day.isoformat() if day else ""})
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str, str, result=str)
    def putAside(self, gid: str, amount: str) -> str:
        """Money set aside for a goal (or taken back, with a minus)."""
        g = next((x for x in self._goals if x["id"] == gid), None)
        try:
            cents = parse_amount(amount)
        except ValueError:
            return "That isn't an amount."
        if g:
            g["saved"] = max(0, int(g.get("saved", 0)) + cents)
            self._keep()
            self.changed.emit()
            if g["saved"] >= g["target"]:
                self.said.emit(f"{g['name']}: there! The whole {self.fmt(g['target'])} is set aside.", False)
        return ""

    @Slot(str)
    def removeGoal(self, gid: str) -> None:
        self._goals = [g for g in self._goals if g["id"] != gid]
        self._keep()
        self.changed.emit()
