"""
Highlight videos from the sports' own YouTube channels (UFC, Formula 1, the boxing promoters...),
for the games and events TheSportsDB has no video for.

Each channel's list of full-length uploads (its public feed, no key needed) is read every half hour.
The feed only holds the last 15 uploads, so what was seen is kept here for a week. Only videos that
look like highlights, full fights or full matches are kept; previews, interviews and old classics
are left out. The apps match the videos to their games themselves (by teams, fighters or event name).

Saved in sportsdb/highlights.json next to TheSportsDB's list:
  "yt":   [{"v": "<YouTube id>", "t": "<title>", "at": <published, epoch seconds>, "s": "<sport>", "c": "<channel>", "d": 1?}]
  "ytat": {"<channel>": "<last read, ISO>"}
"d": 1 marks a day's highlights of a whole tournament (darts: "Day Six Highlights"), not one game.
"""
import datetime as dt
import html
import re
import urllib.request

FEED = "https://www.youtube.com/feeds/videos.xml?playlist_id=UULF%s"
KEEP_DAYS = 8
READ_EVERY_MINUTES = 30

# name, channel id, sport (the apps' Sport names), how titles are picked:
#   "hl"   titles that say highlights / full fight / full match...
#   "any"  any title (the channel's uploads after a fight are the fights), minus the left-out kinds
#   "day"  a tournament's day highlights (marked "d")
CHANNELS = [
    ("UFC", "UCvgfXK4nTYKudb0rFR6noLA", "FIGHTING", "hl"),
    ("Zuffa Boxing", "UCDncyGaGt5KumYowsnYUXKg", "FIGHTING", "any"),
    ("Top Rank", "UCbzRzJNHx7ZLlJML9BjZQVQ", "FIGHTING", "hl"),
    ("Matchroom Boxing", "UC7LReVje9aPB4B6XAsXX8WQ", "FIGHTING", "any"),
    ("DAZN Boxing", "UCurvRE5fGcdUgCYWgh-BDsg", "FIGHTING", "hl"),
    ("Queensberry", "UCP3MOjimNiqqkhBcuXzO0RA", "FIGHTING", "hl"),
    ("PBC", "UCWXYAGB9SadlL6p5Bb66wWw", "FIGHTING", "hl"),
    ("Formula 1", "UCB_qr75-ydFVKSF9Dmo6izg", "RACING", "hl"),
    ("NASCAR", "UCuN9hYw2RpoAW8rZ3VK3isA", "RACING", "hl"),
    ("IndyCar", "UCy1F61QvUUQXAXi2Voa_fUw", "RACING", "hl"),
    ("MotoGP", "UC8pYaQzbBBXg9GIOHRvTmDQ", "RACING", "hl"),
    ("WWE", "UCJ5v_MCY6GNUBTO8-D3XoAg", "WRESTLING", "hl"),
    ("AEW", "UCFN4JkGP_bVhAdBsoV9xftA", "WRESTLING", "hl"),
    ("PGA Tour", "UCKwGZZMrhNYKzucCtTPY2Nw", "GOLF", "hl"),
    ("DP World Tour", "UCvZwbZt6YZQ4wj_7qyjPDZw", "GOLF", "hl"),
    ("Tennis TV", "UCbcxFkd6B9xUU54InHv4Tig", "TENNIS", "hl"),
    ("WTA", "UCaBIVVpHjq6j3tSyxwTE-8Q", "TENNIS", "hl"),
    ("PDC", "UCRvCwDp_1DwOlOpnlJf9iYw", "DARTS", "day"),
    ("WST", "UC5lTEvtwu6SR3LMSmU9VZ2Q", "SNOOKER", "hl"),
    ("ICC", "UCt2JXOLNxqry7B_4rRZME3Q", "CRICKET", "hl"),
    ("World Rugby", "UCE28rwYoaV7jvU6GVzdu_GQ", "RUGBY", "hl"),
    ("NRL", "UC33-OkQ6VCYk8xtml8Pk4-g", "RUGBY", "hl"),
    ("AFL", "UCxAeHdLDAatFV_vt95MSO-g", "AUSSIE_RULES", "hl"),
    ("CBS Sports Golazo", "UCET00YnetHT7tOpu12v8jxg", "FOOTBALL", "hl"),
    ("LALIGA", "UCTv-XvfzLX3i4IGWAm4sbmA", "FOOTBALL", "hl"),
    ("Bundesliga", "UC6UL29enLNe4mqwTfAyeNuw", "FOOTBALL", "hl"),
    ("Serie A", "UCBJeMCIeLQos7wacox4hmLQ", "FOOTBALL", "hl"),
    ("Ligue 1", "UCQsH5XtIc9hONE1BQjucM0g", "FOOTBALL", "hl"),
    ("MLS", "UCSZbXT5TLLW_i-5W8FZpFsg", "FOOTBALL", "hl"),
    ("EHF Home of Handball", "UC5F7T3y7PF_1A3JvHfgm5rQ", "HANDBALL", "hl"),
]

WANTED = re.compile(r"highlight|full fight|full match|full card|full race|extended|condensed|sintesi|resumen|"
                    r"r[eé]sum[eé]|zusammenfassung|every shot|all goals|goals? (?:and|&) highlights", re.I)
DAY = re.compile(r"\bday\b.*highlight|highlight.*\bday\b|\bsession\b.*highlight", re.I)
LEFT_OUT = re.compile(r"preview|press conference|presser|media day|weigh[- ]?in|face to face|face-off|faceoff|"
                      r"predict|reacts?\b|reaction|interview|podcast|promo\b|hype|cold open|on this day|#onthisday|"
                      r"classic (?:highlights|fight|match|game)|all-time classic|free fight|#fullmatchfriday|throwback|rewind|season review|year in review|"
                      r"top \d+|best of|greatest|all[- ]time|story of|documentary|behind the|inside the|"
                      r"\blive\b|watch along|stream|marathon", re.I)


def _title_ok(title, how):
    if LEFT_OUT.search(title):
        return False
    if how == "any":
        return True
    if how == "day":
        return bool(WANTED.search(title))
    return bool(WANTED.search(title))


def _read(channel_id):
    req = urllib.request.Request(FEED % channel_id[2:], headers={"User-Agent": "Mozilla/5.0 nuvio-data"})
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        vid = re.search(r"<yt:videoId>([A-Za-z0-9_-]{11})</yt:videoId>", entry)
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        pub = re.search(r"<published>(.*?)</published>", entry)
        if not (vid and title and pub):
            continue
        try:
            at = dt.datetime.fromisoformat(pub.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append((vid.group(1), html.unescape(title.group(1)).strip(), int(at.timestamp())))
    return out


def update(old, now, time_left, log):
    """The channels' highlight list: [old] is the file's last content. Returns (yt, ytat, read)."""
    kept = {}
    cut = int((now - dt.timedelta(days=KEEP_DAYS)).replace(tzinfo=dt.timezone.utc).timestamp())
    for r in old.get("yt") or []:
        if isinstance(r, dict) and r.get("v") and (r.get("at") or 0) >= cut:
            kept[r["v"]] = r
    read_at = dict(old.get("ytat") or {})
    read = 0
    failed = []
    for name, cid, sport, how in CHANNELS:
        if time_left() < 30:
            break
        last = read_at.get(name)
        if last:
            try:
                age = now - dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ")
                if age < dt.timedelta(minutes=READ_EVERY_MINUTES):
                    continue
            except ValueError:
                pass
        try:
            videos = _read(cid)
        except Exception as e:  # a channel that doesn't answer keeps what it had
            failed.append("%s (%s)" % (name, e.__class__.__name__))
            continue
        read += 1
        read_at[name] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        for vid, title, at in videos:
            if at < cut or not _title_ok(title, how):
                continue
            row = {"v": vid, "t": title, "at": at, "s": sport, "c": name}
            if how == "day" and DAY.search(title):
                row["d"] = 1
            kept[vid] = row
    if failed:
        log("YouTube channels not read: " + ", ".join(failed))
    names = {c[0] for c in CHANNELS}
    yt = sorted(kept.values(), key=lambda r: -r["at"])
    return yt, {k: v for k, v in read_at.items() if k in names}, read
