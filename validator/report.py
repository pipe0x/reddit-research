"""Markdown report + evidence dump."""
import json
import time

LABELS = {"seeking": "Sucht nach Lösung", "pain": "Schmerz / Frust", "wtp": "Zahlungsbereitschaft",
          "workaround": "Workaround (Excel, manuell …)", "complaint": "Kritik an bestehenden Tools",
          "recommendation": "Empfiehlt bestehendes Tool"}
WEIGHT = {"wtp": 5, "seeking": 4, "complaint": 3, "pain": 2, "workaround": 2, "recommendation": 1}


def link(item):
    return "https://www.reddit.com" + item["permalink"] if item["permalink"].startswith("/") else item["permalink"]


def quote(item, length=280):
    text = " ".join(f"{item['title']} — {item['text']}".strip(" —").split())
    return text[:length] + ("…" if len(text) > length else "")


def rank(item):
    return item["relevance"] * 2 + sum(WEIGHT[s] for s in item["signals"]) + min(item["score"], 50) / 10 \
        + min(item["num_comments"], 50) / 10


def bar(value):
    return "█" * round(value / 10) + "░" * (10 - round(value / 10))


def render(idea, result, sources):
    r, lines = result, []
    add = lines.append
    add(f"# Reddit-Validierung: {idea['name']}\n")
    add(f"_Erstellt {time.strftime('%Y-%m-%d %H:%M')} · Quellen: {', '.join(sources)} · "
        f"Zeitraum: letzte {idea.get('years', 3)} Jahre_\n")
    add(f"> {idea.get('description', '')}\n")
    add("## Ergebnis (heuristisch)\n")
    add("| Index | Wert | |\n|---|---|---|")
    add(f"| **Nachfrage-Signal** | **{r['demand_index']} / 100** | `{bar(r['demand_index'])}` |")
    add(f"| **Konkurrenz-Dichte** | **{r['competition_index']} / 100** | `{bar(r['competition_index'])}` |\n")
    add("Die Indizes basieren auf Phrasen-Mustern und sind ein grober Startpunkt, kein Urteil. "
        "Die finale Einschätzung entsteht durch Lesen der Belege unten.\n")
    for title, parts in (("Nachfrage", r["demand_parts"]), ("Konkurrenz", r["competition_parts"])):
        add(f"**{title} – Komponenten:** " + " · ".join(f"{k} {v:.0f} (×{w})" for k, (w, v) in parts.items()))
        add("")
    add(f"Trend-Korrektur Nachfrage: {r['trend_bonus']:+}\n")

    add("## Datenbasis\n")
    add(f"- Gesammelt: {r['collected']} Posts/Kommentare, davon **relevant: {r['relevant']}** "
        f"von **{r['authors']} verschiedenen Autoren**")
    add("- Subreddits: " + ", ".join(f"r/{s} ({n})" for s, n in r["subreddits"][:15]))
    t = r["trend"]
    if t["per_month"]:
        add(f"- Trend ({t['source']}): Ø {t['avg_month_last_12m']} Posts/Monat in den letzten 12 Monaten vs. "
            f"Ø {t['avg_month_prev_12m']} davor → **Faktor {t['ratio']}**")
        add("- Pro Monat: " + ", ".join(f"{m}: {n}" for m, n in t["per_month"].items()))
        if t["gaps"]:
            add(f"- Archiv-Lücken (ignoriert): {', '.join(t['gaps'])}")
    else:
        add(f"- Trend: {t['source']}")
    add("- Stichprobe pro Jahr (je Anfrage gedeckelt auf `per_slice`, daher kein echter Trend): "
        + ", ".join(f"{y}: {n}" for y, n in t["sample_per_year"].items()))
    add("")
    add("| Signal | verschiedene Autoren |\n|---|---|")
    for key, label in LABELS.items():
        add(f"| {label} | {r['signal_authors'][key]} |")
    add("")

    add("## Konkurrenz\n")
    if r["known_competitors"]:
        add("| Bekannter Anbieter | Nennungen | davon mit Kritik |\n|---|---|---|")
        for name, count in r["known_competitors"]:
            add(f"| {name} | {count} | {r['competitor_complaints'].get(name, 0)} |")
    else:
        add("_Keiner der vorgegebenen Anbieter wurde genannt._")
    add("\n**Automatisch gefundene Namen** (≥2 Autoren; enthält Rauschen, muss manuell geprüft werden):\n")
    add(", ".join(f"{n} ({c})" for n, c in r["discovered_candidates"]) or "_keine_")
    add("")

    add("## Belege\n")
    for key, label in LABELS.items():
        hits = sorted((i for i in r["items"] if key in i["signals"]), key=rank, reverse=True)[:12]
        if not hits:
            continue
        add(f"### {label} ({r['signal_authors'][key]})\n")
        for i in hits:
            day = time.strftime("%Y-%m-%d", time.gmtime(i["created_utc"]))
            add(f"- [r/{i['subreddit']} · {day} · {i['kind']}]({link(i)}) {quote(i)}")
        add("")

    add("## Grenzen\n")
    add("- Archiv-Daten: Scores/Kommentarzahlen sind oft zum Zeitpunkt der Archivierung erfasst und daher zu niedrig.")
    add("- Suche ist auf die gewählten Subreddits und Suchbegriffe begrenzt; Reddit-Gerede ≠ Kaufbereitschaft.")
    add("- Muster erkennen keine Ironie; falsche Treffer sind möglich, darum die Belege lesen.")
    return "\n".join(lines) + "\n"


def write(run_dir, idea, result, sources):
    (run_dir / "report.md").write_text(render(idea, result, sources), encoding="utf-8")
    slim = {k: v for k, v in result.items() if k != "items"}
    slim["demand_parts"] = {k: round(v) for k, (_, v) in result["demand_parts"].items()}
    slim["competition_parts"] = {k: round(v) for k, (_, v) in result["competition_parts"].items()}
    (run_dir / "summary.json").write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    with (run_dir / "evidence.jsonl").open("w", encoding="utf-8") as handle:
        for item in sorted(result["items"], key=rank, reverse=True):
            handle.write(json.dumps({"link": link(item), "kind": item["kind"], "subreddit": item["subreddit"],
                                     "date": time.strftime("%Y-%m-%d", time.gmtime(item["created_utc"])),
                                     "signals": sorted(item["signals"]), "competitors": item["competitors"],
                                     "text": quote(item, 1200)}, ensure_ascii=False) + "\n")
