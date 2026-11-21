#!/usr/bin/env python3
"""
Series Tracker - add a series name, get the data, feed Power BI.

SETUP (one time)
  1. Free TMDB account -> Settings -> API -> copy the "API Key (v3 auth)".
  2. Either set env var TMDB_API_KEY, or paste the key into a file named
     tmdb_key.txt next to this script.
  3. Python 3.8+. No extra packages needed.

USAGE
  python tracker.py add "Breaking Bad"            # search, pick, fetch, asks what you watched
  python tracker.py watched "Breaking Bad" --seasons all --times 2
  python tracker.py watched "Money Heist" --seasons 1-3 --times 1
  python tracker.py watched "Dark" --seasons 2 --episodes 6   # partly watched season
  python tracker.py watched "Dark" --seasons 1 --lang Hindi   # watched in a dubbed language
  python tracker.py update                        # check ongoing series for new seasons/episodes
  python tracker.py bulk my_series.txt            # import many (one per line, see below)
  python tracker.py list                          # summary in the terminal
  python tracker.py export                        # rewrite the CSVs for Power BI

BULK FILE FORMAT (one series per line, extras optional):
  Breaking Bad ; all ; 2
  Money Heist ; 1-3 ; 1
  Sacred Games
  (name ; seasons watched ; times watched)

Every command that changes data re-exports the CSVs into ./powerbi_export/
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from statistics import median

if getattr(sys, "frozen", False):          # running as a packaged .exe
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "series.db"
EXPORT_DIR = BASE / "powerbi_export"
API = "https://api.themoviedb.org/3"

LANG_FALLBACK = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", "pa": "Punjabi",
    "ko": "Korean", "ja": "Japanese", "zh": "Chinese", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "tr": "Turkish", "ru": "Russian", "th": "Thai", "da": "Danish",
    "sv": "Swedish", "no": "Norwegian", "pl": "Polish",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_id         INTEGER PRIMARY KEY,   -- TMDB id
    name              TEXT,
    original_name     TEXT,
    original_language TEXT,
    origin_country    TEXT,
    spoken_languages  TEXT,
    genres            TEXT,
    status            TEXT,                  -- Returning Series / Ended / Canceled ...
    first_air_year    INTEGER,
    last_checked      TEXT
);
CREATE TABLE IF NOT EXISTS seasons (
    series_id            INTEGER,
    season_no            INTEGER,
    episodes             INTEGER,            -- aired episodes only
    season_total_minutes INTEGER,
    avg_runtime          REAL,
    air_date             TEXT,
    PRIMARY KEY (series_id, season_no)
);
CREATE TABLE IF NOT EXISTS watch_log (
    series_id        INTEGER,
    season_no        INTEGER,
    episodes_watched INTEGER DEFAULT 0,
    watch_count      INTEGER DEFAULT 0,
    watched_language TEXT,
    updated_on       TEXT,
    PRIMARY KEY (series_id, season_no)
);

DROP VIEW IF EXISTS season_detail;
CREATE VIEW season_detail AS
SELECT sr.series_id, sr.name AS series_name, sr.original_language, sr.genres,
       se.season_no, se.episodes, se.season_total_minutes,
       COALESCE(w.episodes_watched, 0) AS episodes_watched,
       COALESCE(w.watch_count, 0)      AS watch_count,
       COALESCE(w.watched_language, sr.original_language) AS watched_language,
       CASE WHEN COALESCE(w.episodes_watched, 0) = 0 THEN 'Not watched'
            WHEN w.episodes_watched >= se.episodes   THEN 'Completed'
            ELSE 'In progress' END AS season_status,
       ROUND(1.0 * se.season_total_minutes / se.episodes
             * COALESCE(w.episodes_watched, 0)) AS minutes_watched_unique,
       ROUND(1.0 * se.season_total_minutes / se.episodes
             * COALESCE(w.episodes_watched, 0) * COALESCE(w.watch_count, 0))
             AS minutes_watched_incl_rewatch
FROM seasons se
JOIN series sr ON sr.series_id = se.series_id
LEFT JOIN watch_log w ON w.series_id = se.series_id AND w.season_no = se.season_no;

DROP VIEW IF EXISTS series_summary;
CREATE VIEW series_summary AS
SELECT sr.series_id, sr.name AS series_name, sr.original_language, sr.origin_country,
       sr.genres, sr.status AS show_status, sr.first_air_year,
       COUNT(*)                         AS total_seasons,
       SUM(d.episodes)                  AS total_episodes,
       SUM(d.season_total_minutes)      AS total_minutes,
       SUM(d.episodes_watched)          AS episodes_watched,
       ROUND(100.0 * SUM(d.episodes_watched) / SUM(d.episodes), 1) AS completion_pct,
       SUM(d.season_status = 'Completed') AS seasons_completed,
       MAX(d.watch_count)               AS times_watched,
       SUM(d.minutes_watched_incl_rewatch) AS minutes_watched_incl_rewatch,
       CASE WHEN SUM(d.episodes_watched) = 0 THEN 'Not started'
            WHEN SUM(d.season_status = 'Completed') = COUNT(*) THEN 'Completed'
            ELSE 'In progress' END      AS watch_status
FROM series sr
JOIN season_detail d ON d.series_id = sr.series_id
GROUP BY sr.series_id;
"""


# ----------------------------------------------------------------- TMDB ----
def api_key():
    key = os.environ.get("TMDB_API_KEY")
    key_file = BASE / "tmdb_key.txt"
    if not key and key_file.exists():
        key = key_file.read_text().strip()
    if not key:
        sys.exit("No TMDB key found. Set TMDB_API_KEY or create tmdb_key.txt (see top of file).")
    return key


def tmdb(path, **params):
    params["api_key"] = api_key()
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("TMDB rejected the API key. Use the v3 'API Key', not the read access token.")
        raise
    except urllib.error.URLError as e:
        sys.exit(f"Network problem talking to TMDB: {e.reason}")


def fetch_series(tv_id):
    """Return (series_dict, [season_dict, ...]) with aired episodes only."""
    d = tmdb(f"/tv/{tv_id}")
    code = d.get("original_language", "")
    spoken = d.get("spoken_languages", [])
    names = {l.get("iso_639_1"): l.get("english_name") for l in spoken}
    first = d.get("first_air_date") or ""
    series = {
        "series_id": tv_id,
        "name": d.get("name"),
        "original_name": d.get("original_name"),
        "original_language": names.get(code) or LANG_FALLBACK.get(code, code),
        "origin_country": ", ".join(d.get("origin_country", [])),
        "spoken_languages": ", ".join(l.get("english_name", "") for l in spoken),
        "genres": ", ".join(g["name"] for g in d.get("genres", [])),
        "status": d.get("status", ""),
        "first_air_year": int(first[:4]) if first[:4].isdigit() else None,
    }

    today = date.today().isoformat()
    raw = []  # (season_no, air_date, [runtime or None per aired episode])
    for s in d.get("seasons", []):
        n = s.get("season_number")
        if not n:  # skip season 0 (specials)
            continue
        sd = tmdb(f"/tv/{tv_id}/season/{n}")
        aired = [e for e in sd.get("episodes", [])
                 if e.get("air_date") and e["air_date"] <= today]
        if not aired:
            continue  # not aired yet; picked up by a later `update`
        raw.append((n, s.get("air_date"), [e.get("runtime") or None for e in aired]))

    known = [r for _, _, rts in raw for r in rts if r]
    legacy = (d.get("episode_run_time") or [None])[0]
    fill = median(known) if known else (legacy or 0)

    seasons = []
    for n, air, rts in raw:
        total = sum(r if r else fill for r in rts)
        seasons.append({
            "season_no": n, "episodes": len(rts),
            "season_total_minutes": int(total),
            "avg_runtime": round(total / len(rts), 1), "air_date": air,
        })
    return series, seasons


def search_series(query, auto=False):
    results = tmdb("/search/tv", query=query).get("results", [])[:5]
    if not results:
        print(f"  No TMDB results for '{query}'.")
        return None
    if auto:
        r = results[0]
        print(f"  Matched: {r['name']} ({(r.get('first_air_date') or '')[:4]})")
        return r["id"]
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['name']} ({(r.get('first_air_date') or '')[:4]}) "
              f"[{r.get('original_language')}]  {(r.get('overview') or '')[:70]}")
    choice = input("Pick a number [1]: ").strip() or "1"
    try:
        return results[int(choice) - 1]["id"]
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return None


# ------------------------------------------------------------------ DB -----
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def save_series(conn, series, seasons):
    """Upsert data; return a list of human-readable changes for existing series."""
    sid = series["series_id"]
    old = dict(conn.execute("SELECT season_no, episodes FROM seasons WHERE series_id=?", (sid,)))
    existed = bool(conn.execute("SELECT 1 FROM series WHERE series_id=?", (sid,)).fetchone())
    conn.execute("""
        INSERT INTO series VALUES (:series_id,:name,:original_name,:original_language,
            :origin_country,:spoken_languages,:genres,:status,:first_air_year,:last_checked)
        ON CONFLICT(series_id) DO UPDATE SET
            name=excluded.name, original_name=excluded.original_name,
            original_language=excluded.original_language, origin_country=excluded.origin_country,
            spoken_languages=excluded.spoken_languages, genres=excluded.genres,
            status=excluded.status, first_air_year=excluded.first_air_year,
            last_checked=excluded.last_checked
    """, {**series, "last_checked": date.today().isoformat()})

    changes = []
    for s in seasons:
        n = s["season_no"]
        if existed:
            if n not in old:
                changes.append(("NEW_SEASON", n, s["episodes"]))
            elif s["episodes"] != old[n]:
                changes.append(("NEW_EPISODES", n, s["episodes"] - old[n]))
        conn.execute("""
            INSERT INTO seasons VALUES (?,?,?,?,?,?)
            ON CONFLICT(series_id, season_no) DO UPDATE SET
                episodes=excluded.episodes, season_total_minutes=excluded.season_total_minutes,
                avg_runtime=excluded.avg_runtime, air_date=excluded.air_date
        """, (sid, n, s["episodes"], s["season_total_minutes"], s["avg_runtime"], s["air_date"]))
    conn.commit()
    return changes


def find_local(conn, name):
    rows = conn.execute("SELECT series_id, name FROM series WHERE name LIKE ?",
                        (f"%{name}%",)).fetchall()
    exact = [r for r in rows if r[1].lower() == name.lower()]
    if exact:
        return exact[0]
    if len(rows) == 1:
        return rows[0]
    if not rows:
        print(f"'{name}' isn't in your database yet. Run: python tracker.py add \"{name}\"")
    else:
        print("Several matches, be more specific: " + ", ".join(r[1] for r in rows))
    return None


def parse_seasons(spec, available):
    spec = spec.strip().lower()
    available = set(available)
    if spec == "all":
        return sorted(available)
    wanted = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            wanted.update(range(int(a), int(b) + 1))
        else:
            wanted.add(int(part))
    missing = wanted - available
    if missing:
        print(f"  (ignoring seasons not in database: {sorted(missing)})")
    return sorted(wanted & available)


def mark_watched(conn, sid, spec, times=1, episodes=None, lang=None):
    seasons = dict(conn.execute("SELECT season_no, episodes FROM seasons WHERE series_id=?", (sid,)))
    nums = parse_seasons(spec, seasons)
    for n in nums:
        eps = seasons[n]
        if episodes is not None and len(nums) == 1:
            eps = min(episodes, seasons[n])
        conn.execute("""
            INSERT INTO watch_log VALUES (?,?,?,?,?,?)
            ON CONFLICT(series_id, season_no) DO UPDATE SET
                episodes_watched=excluded.episodes_watched, watch_count=excluded.watch_count,
                watched_language=excluded.watched_language, updated_on=excluded.updated_on
        """, (sid, n, eps, times, lang, date.today().isoformat()))
    conn.commit()
    return nums


# ------------------------------------------------------------- EXPORT ------
def export_csv(conn):
    EXPORT_DIR.mkdir(exist_ok=True)

    def dump(filename, cursor):
        cols = [c[0] for c in cursor.description]
        with open(EXPORT_DIR / filename, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(cursor.fetchall())

    dump("series_summary.csv", conn.execute("SELECT * FROM series_summary ORDER BY series_name"))
    dump("season_detail.csv", conn.execute("SELECT * FROM season_detail ORDER BY series_name, season_no"))

    # One row per (series, genre) so Power BI can slice by genre properly
    rows = []
    for sid, genres in conn.execute("SELECT series_id, genres FROM series"):
        rows += [(sid, g.strip()) for g in (genres or "").split(",") if g.strip()]
    with open(EXPORT_DIR / "series_genres.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["series_id", "genre"])
        w.writerows(rows)
    print(f"  CSVs updated in {EXPORT_DIR}")


# ------------------------------------------------------------ COMMANDS -----
def cmd_add(args):
    conn = connect()
    tv_id = search_series(args.name)
    if tv_id is None:
        return
    series, seasons = fetch_series(tv_id)
    save_series(conn, series, seasons)
    total_min = sum(s["season_total_minutes"] for s in seasons)
    print(f"\n  {series['name']} | {series['original_language']} | {series['genres']} | {series['status']}")
    print(f"  {len(seasons)} seasons, {sum(s['episodes'] for s in seasons)} episodes, "
          f"{total_min} min (~{total_min / 60:.1f} h)")
    spec = input("\nSeasons you've watched (all / none / e.g. 1-3,5) [none]: ").strip() or "none"
    if spec.lower() != "none":
        times = int(input("How many times watched [1]: ").strip() or 1)
        lang = input(f"Language you watched in [{series['original_language']}]: ").strip() or None
        done = mark_watched(conn, tv_id, spec, times, None, lang)
        print(f"  Logged seasons {done} x{times}")
    export_csv(conn)


def cmd_watched(args):
    conn = connect()
    hit = find_local(conn, args.name)
    if not hit:
        return
    done = mark_watched(conn, hit[0], args.seasons, args.times, args.episodes, args.lang)
    print(f"  {hit[1]}: logged seasons {done} x{args.times}")
    export_csv(conn)


def refresh_one(conn, sid):
    series, seasons = fetch_series(sid)
    changes = save_series(conn, series, seasons)
    for kind, n, val in changes:
        if kind == "NEW_SEASON":
            print(f"  NEW SEASON: {series['name']} S{n} ({val} eps). Mark it with:\n"
                  f"      python tracker.py watched \"{series['name']}\" --seasons {n}")
        else:
            print(f"  +{val} new episode(s) in {series['name']} S{n} (now marked 'In progress' if you'd finished it)")
    return bool(changes)


def cmd_update(args):
    conn = connect()
    query = "SELECT series_id, name FROM series"
    if not args.all:
        query += " WHERE status NOT IN ('Ended', 'Canceled')"
    rows = conn.execute(query).fetchall()
    print(f"Checking {len(rows)} series...")
    changed = False
    for sid, name in rows:
        try:
            changed |= refresh_one(conn, sid)
        except Exception as e:  # keep going if one show fails
            print(f"  Could not refresh {name}: {e}")
    if not changed:
        print("  No new seasons or episodes.")
    export_csv(conn)


def cmd_bulk(args):
    conn = connect()
    for line in Path(args.file).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        name = parts[0]
        spec = parts[1] if len(parts) > 1 else "none"
        times = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        print(f"- {name}")
        tv_id = search_series(name, auto=True)
        if tv_id is None:
            continue
        series, seasons = fetch_series(tv_id)
        save_series(conn, series, seasons)
        if spec.lower() != "none":
            mark_watched(conn, tv_id, spec, times)
    export_csv(conn)


def cmd_list(args):
    conn = connect()
    rows = conn.execute("""SELECT series_name, original_language, total_seasons, total_episodes,
        ROUND(total_minutes/60.0,1), completion_pct, times_watched, watch_status
        FROM series_summary ORDER BY series_name""").fetchall()
    print(f"{'Series':32} {'Lang':10} {'S':>3} {'Eps':>5} {'Hours':>7} {'Done%':>6} {'x':>2}  Status")
    for r in rows:
        print(f"{r[0][:31]:32} {str(r[1])[:9]:10} {r[2]:>3} {r[3]:>5} {r[4]:>7} {r[5]:>6} {r[6]:>2}  {r[7]}")


def cmd_export(args):
    export_csv(connect())


def main():
    p = argparse.ArgumentParser(description="Series tracker -> Power BI")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add"); a.add_argument("name"); a.set_defaults(fn=cmd_add)

    w = sub.add_parser("watched")
    w.add_argument("name")
    w.add_argument("--seasons", required=True, help="all, 3, or 1-3,5")
    w.add_argument("--times", type=int, default=1, help="total times you've watched them")
    w.add_argument("--episodes", type=int, help="partly watched: episodes seen (single season only)")
    w.add_argument("--lang", help="language you watched in, e.g. Hindi")
    w.set_defaults(fn=cmd_watched)

    u = sub.add_parser("update"); u.add_argument("--all", action="store_true",
                                                  help="also re-check ended series")
    u.set_defaults(fn=cmd_update)

    b = sub.add_parser("bulk"); b.add_argument("file"); b.set_defaults(fn=cmd_bulk)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("export").set_defaults(fn=cmd_export)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
