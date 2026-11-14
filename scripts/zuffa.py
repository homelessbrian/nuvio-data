#!/usr/bin/env python3
"""
Zuffa Boxing's fight cards, for the app's Boxing page.

TheSportsDB lists Zuffa Boxing events late (sometimes only after the night) and without the
fights on the card, so its cards are read from Wikipedia as well: the "<year> in Zuffa Boxing"
pages (every card with its fights, and the results once in) and the "Zuffa Boxing" page's list
of events (dates and headliners, for a card the year page doesn't cover yet). Three requests a
day at most.

merge(events, today, keep_from, keep_to, old_events) adds them to a boxing league's events:
a card TheSportsDB already has (same day give or take one, named Zuffa or with both headliners
in its name) keeps TheSportsDB's id and start time and gains the fight card; any other card is
added with its date (the time isn't known, so the app shows "time to be confirmed"). When
Wikipedia can't be read, the cards from the last run are kept.

Only the Python standard library is used. Run on its own to print what it finds.
"""
import datetime as dt
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

RAW = "https://en.wikipedia.org/w/index.php?title=%s&action=raw"
HEADERS = {"User-Agent": "NuvioData/1.0 (https://github.com/homelessbrian/nuvio-data; schedule reader)"}
MAIN_PAGE = "Zuffa Boxing"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
PARTICLES = {"de", "del", "la", "los", "las", "da", "dos", "van", "von", "der", "di", "le"}
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def fetch(title):
    """A page's wikitext, or None (missing page, or Wikipedia not answering)."""
    url = RAW % urllib.parse.quote(title.replace(" ", "_"))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(20 if e.code == 429 else 5)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5)
    return None


# ------------------------------------------------------------------ wikitext to plain text

def plain(s):
    s = s or ""
    s = re.sub(r"<ref[^>/]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    # {{Abbr|TKO|Technical knockout}} -> TKO; {{NA}} and other templates -> nothing.
    s = re.sub(r"\{\{\s*abbr\s*\|([^|}]*)\|[^}]*\}\}", r"\1", s, flags=re.I)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return " ".join(s.split()).strip()


def cell(s):
    """A table cell without its formatting part ("align=center| TKO" -> "TKO")."""
    s = s.strip()
    m = re.match(r'^[a-z\-]+\s*=\s*"?[^|"]*"?\s*(?:[a-z\-]+\s*=\s*"?[^|"]*"?\s*)*\|(?!\|)(.*)$', s, flags=re.I | re.S)
    if m and "[[" not in s.split("|", 1)[0] and "{{" not in s.split("|", 1)[0]:
        s = m.group(1)
    return plain(s)


def parse_date(text):
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", plain(text))
    if not m or m.group(1).lower() not in MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def place(text):
    """"[[Copper Box Arena]], [[London]], England, U.K." -> venue, city, country."""
    parts = [p.strip() for p in plain(text).split(",") if p.strip()]
    if not parts:
        return {}
    out = {"venue": parts[0]}
    if len(parts) >= 2:
        out["city"] = parts[1]
    if len(parts) >= 3:
        country = parts[-1]
        if country in ("U.S.", "US", "USA", "U.S.A."):
            country = "United States"
        elif country in ("U.K.", "UK"):
            country = parts[-2] if len(parts) >= 4 else "United Kingdom"
        out["country"] = country
    return out


def surname(name):
    """"Shane Mosley Jr." -> "Mosley"; "Edwin De Los Santos" -> "De Los Santos"."""
    words = [w for w in plain(name).split() if w.lower() not in SUFFIXES]
    if not words:
        return plain(name)
    i = len(words) - 1
    while i > 1 and words[i - 1].lower() in PARTICLES:
        i -= 1
    return " ".join(words[i:])


# ------------------------------------------------------------------ the pages

def infobox(text, field):
    m = re.search(r"^\s*\|\s*%s\s*=(.*)$" % re.escape(field), text, flags=re.I | re.M)
    return m.group(1).strip() if m else ""


def card_rows(text):
    """The fights in a section's card table: (weight, fighter, word, fighter, method, round, time)."""
    m = re.search(r"\{\|.*?(?:\n\|\}|\Z)", text, flags=re.S)
    if not m:
        return []
    rows = []
    for block in re.split(r"\n\|-[^\n]*", m.group(0)):
        lines = [ln for ln in block.split("\n") if ln.startswith("|") and not ln.startswith("|}") and not ln.startswith("{|")]
        if not lines:
            continue
        cells = []
        for ln in lines:
            cells += ln[1:].split("||")
        cells = [cell(c) for c in cells]
        if len(cells) < 4 or not cells[1] or not cells[3]:
            continue
        rows.append((cells + [""] * 8)[:8])
    return rows


def fight_line(row, done):
    weight, a, word, b, method, rnd, clock = [x.strip() for x in row[:7]]
    rnd_clean = rnd.replace("–", "-").strip()
    w = word.lower().rstrip(".")
    if done and w in ("def", "defeated"):
        name = "%s def. %s" % (a, b)
        m = re.match(r"^(\d+)\s*/\s*(\d+)$", rnd_clean)
        if m:
            detail = "%s R%s" % (method or "Win", m.group(1)) + (" %s" % clock if clock else "")
        else:
            detail = method + (" (%s)" % rnd_clean if rnd_clean.isdigit() else "")
    elif done and w in ("drew", "draw", "nc", "no contest"):
        name = "%s v %s" % (a, b)
        detail = (method or ("Draw" if w.startswith("dr") else "No contest")) + (" (%s)" % rnd_clean if rnd_clean.isdigit() else "")
    else:
        name = "%s v %s" % (a, b)
        m = re.search(r"(\d+)", rnd_clean)
        detail = ", ".join(x for x in (weight, ("%s rds" % m.group(1)) if m else "") if x)
    return {"pos": "", "name": name, "detail": detail.strip() or None}


def year_page_events(text):
    """Every card on a "<year> in Zuffa Boxing" page."""
    out = []
    sections = re.split(r"\n==(?!=)\s*(.*?)\s*==\s*\n", "\n" + text)
    for i in range(1, len(sections) - 1, 2):
        title, body = plain(sections[i]), sections[i + 1]
        if "infobox boxingmatch" not in body.lower():
            continue
        day = parse_date(infobox(body, "fight date"))
        if not day:
            continue
        f1, f2 = infobox(body, "fighter1"), infobox(body, "fighter2")
        result = plain(infobox(body, "result"))
        card = body.split("=== Card ===", 1)[1] if "=== Card ===" in body else body.split("===Card===", 1)[-1]
        rows = card_rows(card)
        done = bool(result) or any(r[2].lower().rstrip(".") in ("def", "defeated", "drew", "draw", "nc") for r in rows)
        if not f1 and rows:
            f1, f2 = rows[0][1], rows[0][3]
        out.append({
            "title": title, "day": day, "where": place(infobox(body, "location")),
            "head": (plain(f1), plain(f2)) if f1 and f2 else None,
            "results": [fight_line(r, done) for r in rows],
        })
    return out


def list_events(text):
    """The "Zuffa Boxing" page's list of events: name, headliners, date, place."""
    m = re.search(r"==\s*List of events\s*==(.*?)\n\|\}", text, flags=re.S)
    if not m:
        return []
    out = []
    for block in re.split(r"\n\|-[^\n]*", m.group(1)):
        cells = []
        for ln in block.split("\n"):
            if ln.startswith("|") and not ln.startswith("|}") and not ln.startswith("{|"):
                cells += ln[1:].split("||")
        cells = [c for c in cells if c.strip()]
        # A row: [No.], event, headline fight, titles, date, place, ref.
        date_i = next((k for k, c in enumerate(cells) if parse_date(c) and not re.search(r"<ref|cite", c, re.I)), None)
        if date_i is None or date_i < 3:
            continue
        name = cell(cells[date_i - 3])
        head = cell(cells[date_i - 2])
        if re.match(r"^\d+$", name) or not name:
            continue
        sides = re.split(r"\s+vs?\.?\s+", head)
        out.append({
            "title": name, "day": parse_date(cells[date_i]),
            "where": place(cell(cells[date_i + 1])) if date_i + 1 < len(cells) else {},
            "head": (sides[0], sides[1]) if len(sides) == 2 else None,
            "results": [],
        })
    return out


def event_name(title, head):
    t = re.sub(r"\s+", " ", title).strip()
    if not t.lower().startswith("zuffa"):
        t = "Zuffa Boxing"
    else:
        # "Zuffa Boxing 03" -> "Zuffa Boxing 3" (as the broadcasts say it).
        t = re.sub(r"^(Zuffa Boxing)\s+0*(\d+)", r"\1 \2", t, flags=re.I)
    if head:
        return "%s: %s vs %s" % (t, surname(head[0]), surname(head[1]))
    return t


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", s).split()) + " "


def read_cards(today):
    """Zuffa's cards from Wikipedia (None when Wikipedia couldn't be read at all)."""
    cards, got_any = {}, False
    for year in sorted({today.year, (today + dt.timedelta(days=120)).year, (today - dt.timedelta(days=10)).year}):
        text = fetch("%d in Zuffa Boxing" % year)
        if text is None:
            continue
        got_any = True
        for c in year_page_events(text):
            cards[c["day"].isoformat() + norm(c["title"])] = c
    text = fetch(MAIN_PAGE)
    if text is not None:
        got_any = True
        for c in list_events(text):
            if not c["day"] or not c["head"]:
                continue
            # Already on a year page (same day, or the same headliners within a day): skip.
            dup = any(abs((c["day"] - o["day"]).days) <= 1 and (
                norm(c["title"]) == norm(o["title"]) or (o["head"] and norm(surname(c["head"][0])) in norm(" ".join(o["head"])))
            ) for o in cards.values())
            if not dup:
                cards[c["day"].isoformat() + norm(c["title"])] = c
    if not got_any:
        return None
    out = []
    for c in sorted(cards.values(), key=lambda x: x["day"]):
        ev = {
            "id": "zuffa:%s:%s" % (c["day"].isoformat(), norm(c["title"]).strip().replace(" ", "-")),
            "name": event_name(c["title"], c["head"]),
            "start": "%sT00:00:00Z" % c["day"].isoformat(), "hasTime": False, "zuffa": True,
        }
        ev.update(c["where"])
        if c["results"]:
            ev["results"] = c["results"]
        ev["_head"] = c["head"]
        out.append(ev)
    return out


def same_card(tsdb_ev, z):
    try:
        a = dt.date.fromisoformat(tsdb_ev["start"][:10])
        b = dt.date.fromisoformat(z["start"][:10])
    except (KeyError, ValueError):
        return False
    if abs((a - b).days) > 1:
        return False
    text = norm(tsdb_ev.get("name"))
    head = z.get("_head")
    if head and norm(surname(head[0])) in text and norm(surname(head[1])) in text:
        return True
    num = re.search(r"Zuffa Boxing (\d+)", z["name"])
    if num and re.search(r" zuffa boxing 0*%s " % num.group(1), text):
        return True
    return " zuffa " in text and not head


def merge(events, today, keep_from, keep_to, old_events=None, log=print):
    """[events] (a boxing league's, in the app's file format) with Zuffa's cards added."""
    cards = read_cards(today)
    if cards is None:
        kept = [e for e in (old_events or []) if e.get("zuffa") and keep_from <= e.get("start", "")[:10] <= keep_to]
        log("Zuffa Boxing: Wikipedia couldn't be read; kept %d card(s) from last time." % len(kept))
        have = {e.get("id") for e in events}
        return events + [e for e in kept if e.get("id") not in have], "Wikipedia not reachable: %d kept" % len(kept)
    out = [dict(e) for e in events]
    added = merged = 0
    for z in cards:
        if not (keep_from <= z["start"][:10] <= keep_to):
            continue
        match = next((e for e in out if same_card(e, z)), None)
        if match is not None:
            # TheSportsDB's copy: its id and time stay; it gains the name, place and fight card.
            match["name"] = z["name"]
            for k in ("venue", "city", "country"):
                if z.get(k) and not match.get(k):
                    match[k] = z[k]
            if z.get("results"):
                match["results"] = z["results"]
            match["zuffa"] = True
            merged += 1
        else:
            out.append({k: v for k, v in z.items() if not k.startswith("_")})
            added += 1
    for e in out:
        e.pop("_head", None)
    out.sort(key=lambda x: (x.get("start", ""), x.get("name", "")))
    note = "%d added, %d joined with TheSportsDB's" % (added, merged)
    log("Zuffa Boxing: " + note)
    return out, note


if __name__ == "__main__":
    today = dt.date.today()
    cards = read_cards(today)
    if cards is None:
        print("Wikipedia couldn't be read.")
        sys.exit(1)
    for c in cards:
        c.pop("_head", None)
    print(json.dumps(cards, ensure_ascii=False, indent=1))
