"""Reddit business-idea validator, built on reddit-universal-scraper.

  python validate.py run ideas/<idee>.json [--source arcticshift|reddit] [--import export.json]
  python validate.py analyze ideas/<idee>.json      # re-score the collected corpus
  python validate.py import-db ideas/<idee>.json    # load corpus into the scraper's SQLite/dashboard
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from validator import analyze, report, sources

ROOT = Path(__file__).resolve().parent


def load_idea(path):
    idea = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "slug", "subreddits", "search_terms"):
        if not idea.get(key):
            sys.exit(f"Idee-Datei braucht das Feld '{key}'.")
    return idea


def run_dir(idea):
    path = ROOT / "runs" / idea["slug"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_corpus(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def cmd_run(args):
    idea = load_idea(args.idea)
    out = run_dir(idea)
    after = time.time() - idea.get("years", 3) * 365 * 86400
    corpus = out / "corpus.jsonl"
    items = []
    used = []
    counts = {}
    for name in args.source:
        print(f"\n📡 Quelle: {name}")
        if name == "arcticshift":
            http = sources.CachedHttp(out / "cache", max_requests=idea.get("max_requests", 250))
            source = sources.ArcticShift(http)
        elif name == "reddit":
            source = sources.RedditOfficial()
        else:
            sys.exit(f"Unbekannte Quelle {name}")
        try:
            items += list(source.collect(idea, after))
            counts.update(getattr(source, "trend", {}))
            used.append(name)
        except Exception as e:  # keep what other sources found
            print(f"   ❌ {name}: {e}")
    for path in args.import_file or []:
        found = list(sources.from_browser_export(path))
        print(f"\n📥 Browser-Export {path}: {len(found)} Einträge")
        items += found
        used.append("browser-export")
    if not items:
        sys.exit("Keine Daten gesammelt.")
    with corpus.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out / "sources.json").write_text(json.dumps(used), encoding="utf-8")
    (out / "trend_counts.json").write_text(json.dumps(counts, indent=1), encoding="utf-8")
    finish(idea, items, used, out, counts)


def cmd_analyze(args):
    idea = load_idea(args.idea)
    out = run_dir(idea)
    used = json.loads((out / "sources.json").read_text()) if (out / "sources.json").exists() else ["?"]
    counts = json.loads((out / "trend_counts.json").read_text()) if (out / "trend_counts.json").exists() else {}
    finish(idea, read_corpus(out / "corpus.jsonl"), used, out, counts)


def finish(idea, items, used, out, counts):
    result = analyze.analyze(items, idea, counts)
    report.write(out, idea, result, used)
    print(f"\n✅ {result['relevant']} relevante von {result['collected']} Einträgen "
          f"({result['authors']} Autoren)")
    print(f"   Nachfrage-Signal:   {result['demand_index']}/100")
    print(f"   Konkurrenz-Dichte:  {result['competition_index']}/100")
    print(f"   Bericht: {out / 'report.md'}")


def cmd_import_db(args):
    """Push the corpus into the repo's SQLite DB so its dashboard/search/API can be used on it."""
    idea = load_idea(args.idea)
    items = read_corpus(run_dir(idea) / "corpus.jsonl")
    sources.use_repo()
    from export.browser_import import import_bundle
    from export.database import init_database
    init_database()

    def iso(epoch):
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat()

    seen, posts, comments = set(), [], []
    for i in items:
        if (i["kind"], i["id"]) in seen or not i["permalink"]:
            continue
        seen.add((i["kind"], i["id"]))
        if i["kind"] == "post":
            posts.append({"id": i["id"], "permalink": i["permalink"], "title": i["title"], "author": i["author"],
                          "created_utc": iso(i["created_utc"]), "selftext": i["text"], "score": i["score"],
                          "num_comments": i["num_comments"], "post_type": "text"})
        else:
            comments.append({"comment_id": i["id"], "post_permalink": i["permalink"], "author": i["author"],
                             "body": i["text"], "score": i["score"], "created_utc": iso(i["created_utc"])})
    total = {}
    records = [("p", p) for p in posts] + [("c", c) for c in comments]
    for start in range(0, len(records), 5000):
        chunk = records[start:start + 5000]
        stats = import_bundle({"schema_version": 1, "posts": [r for k, r in chunk if k == "p"],
                               "comments": [r for k, r in chunk if k == "c"]})
        for key, value in stats.items():
            total[key] = total.get(key, 0) + value
    print(f"✅ In die Scraper-Datenbank importiert: {total}")
    print("   Dashboard: cd reddit-universal-scraper && ..\\.venv\\Scripts\\python.exe main.py --dashboard")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Validiert Geschäftsideen anhand von Reddit-Diskussionen.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Daten sammeln und auswerten")
    run.add_argument("idea")
    run.add_argument("--source", action="append", choices=["arcticshift", "reddit"],
                     help="Datenquelle (mehrfach möglich, Standard: arcticshift)")
    run.add_argument("--import", dest="import_file", action="append",
                     help="Export der Browser-Extension (JSON) zusätzlich einlesen")
    run.add_argument("--no-api", action="store_true", help="Nur --import-Dateien nutzen")
    run.set_defaults(func=cmd_run)
    sub.add_parser("analyze", help="Gesammelte Daten neu auswerten").add_argument("idea")
    sub.choices["analyze"].set_defaults(func=cmd_analyze)
    sub.add_parser("import-db", help="Korpus in die Scraper-DB laden").add_argument("idea")
    sub.choices["import-db"].set_defaults(func=cmd_import_db)
    args = parser.parse_args()
    if args.command == "run":
        args.source = [] if args.no_api else (args.source or ["arcticshift"])
    args.func(args)


if __name__ == "__main__":
    main()
