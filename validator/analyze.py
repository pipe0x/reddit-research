"""Relevance filtering, signal classification, competitor detection and the two indices."""
import math
import re
import time
from collections import Counter, defaultdict

from .signals import candidates, signals

DAY = 86400
DELETED = {"", "[deleted]", "[removed]", "AutoModerator"}


def saturate(x, k):
    """0..100, reaching ~63 at x == k and approaching 100 asymptotically."""
    return 100 * (1 - math.exp(-x / k)) if k else 0


def term_regex(terms):
    # Allow simple inflections: invoice -> invoices / invoiced / invoicing.
    return [re.compile(r"(?<!\w)" + re.escape(t.rstrip("e") if len(t) > 4 else t) + r"(?:e|es|s|ed|ing|d)?(?!\w)", re.I)
            for t in terms if t]


def classify(items, idea):
    anchors = term_regex(idea.get("relevance_terms") or idea["search_terms"])
    excludes = term_regex(idea.get("exclude_terms", []))
    competitors = {name: term_regex([name] + idea.get("competitor_aliases", {}).get(name, []))
                   for name in idea.get("competitors", [])}
    unique, relevant = {}, []
    for item in items:
        unique.setdefault((item["kind"], item["id"]), item)
    def matches(item):
        text = f"{item['title']}\n{item['text']}"
        return 0 if any(r.search(text) for r in excludes) else sum(1 for r in anchors if r.search(text))

    relevant_threads = {i["id"] for i in unique.values() if i["kind"] == "post" and matches(i)}
    for item in unique.values():
        text = f"{item['title']}\n{item['text']}"
        if item["text"] in ("[deleted]", "[removed]") and not item["title"] or item["author"] == "AutoModerator":
            continue
        hits = matches(item)
        if not hits and item.get("link_id") in relevant_threads and not any(r.search(text) for r in excludes):
            hits = 0.5  # reply inside a relevant thread
        if not hits:
            continue
        item = dict(item, relevance=hits, signals=signals(text),
                    competitors=sorted(n for n, rs in competitors.items() if any(r.search(text) for r in rs)),
                    candidates=sorted(candidates(text)))
        relevant.append(item)
    return list(unique.values()), relevant


def by_author(items, predicate):
    return {i["author"] for i in items if predicate(i) and i["author"] not in DELETED} | \
           {i["id"] for i in items if predicate(i) and i["author"] in DELETED}


def trend(counts, now):
    """Trend from real monthly post counts. Months with zero hits in every series are archive gaps, not
    zero interest, so they are excluded from the averages."""
    if not counts:
        return {"source": "keine Monatszählungen (in der Idee-Datei \"trend_counts\": true setzen)",
                "ratio": None, "per_month": {}, "gaps": []}
    totals = Counter()
    for series in counts.values():
        totals.update(series)
    current = time.strftime("%Y-%m", time.gmtime(now))
    months = sorted(m for m in totals if m < current)  # the running month is incomplete
    gaps = [m for m in months if totals[m] == 0]
    recent_start = time.strftime("%Y-%m", time.gmtime(now - 365 * DAY))
    prev_start = time.strftime("%Y-%m", time.gmtime(now - 730 * DAY))
    recent = [totals[m] for m in months if m >= recent_start and m not in gaps]
    previous = [totals[m] for m in months if prev_start <= m < recent_start and m not in gaps]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    r, p = avg(recent), avg(previous)
    return {"source": "echte Monatszählungen (Posts, Archiv)", "avg_month_last_12m": r and round(r, 1),
            "avg_month_prev_12m": p and round(p, 1), "ratio": round(r / p, 2) if r and p else None,
            "per_month": {m: totals[m] for m in months}, "gaps": gaps}


def analyze(items, idea, counts=None, now=None):
    now = now or time.time()
    unique, relevant = classify(items, idea)
    authors = by_author(relevant, lambda i: True)
    sig = {name: by_author(relevant, lambda i, n=name: n in i["signals"])
           for name in ("seeking", "pain", "wtp", "workaround", "complaint", "recommendation")}

    known = Counter()
    complaints_about = Counter()
    for item in relevant:
        for name in item["competitors"]:
            known[name] += 1
            if "complaint" in item["signals"]:
                complaints_about[name] += 1
    candidate_authors = defaultdict(set)
    for item in relevant:
        for name in item["candidates"]:
            if name not in known:
                candidate_authors[name].add(item["author"] or item["id"])
    discovered = sorted(((n, len(a)) for n, a in candidate_authors.items() if len(a) >= 2), key=lambda x: -x[1])[:25]

    t = trend(counts, now)
    t["sample_per_year"] = dict(sorted(Counter(time.strftime("%Y", time.gmtime(i["created_utc"]))
                                               for i in relevant).items()))
    trend_bonus = 0 if t["ratio"] is None else max(-10, min(10, (t["ratio"] - 1) * 10))
    demand_parts = {
        "Volumen (Autoren)": (0.20, saturate(len(authors), 80)),
        "Lösungssuche": (0.30, saturate(len(sig["seeking"]), 25)),
        "Zahlungsbereitschaft": (0.15, saturate(len(sig["wtp"]), 6)),
        "Schmerz + Workarounds": (0.25, saturate(len(sig["pain"]) + len(sig["workaround"]), 30)),
        "Breite (Subreddits)": (0.10, saturate(len({i["subreddit"] for i in relevant}), 6)),
    }
    demand = sum(w * v for w, v in demand_parts.values()) + trend_bonus

    mentioning = sum(1 for i in relevant if i["competitors"])
    established = sum(1 for n, c in known.items() if c >= 3) + sum(1 for _, c in discovered if c >= 4)
    competition_parts = {
        "Etablierte Anbieter": (0.45, saturate(established, 4)),
        "Anteil mit Anbieter-Nennung": (0.30, min(100, 400 * mentioning / max(1, len(relevant)))),
        "Empfehlungen in Antworten": (0.25, saturate(len(sig["recommendation"]), 25)),
    }
    competition = sum(w * v for w, v in competition_parts.values())

    return {
        "collected": len(unique), "relevant": len(relevant), "authors": len(authors),
        "subreddits": Counter(i["subreddit"] for i in relevant).most_common(),
        "signal_authors": {k: len(v) for k, v in sig.items()},
        "trend": t, "trend_bonus": round(trend_bonus, 1),
        "demand_index": round(max(0, min(100, demand))), "demand_parts": demand_parts,
        "competition_index": round(competition), "competition_parts": competition_parts,
        "known_competitors": known.most_common(), "competitor_complaints": dict(complaints_about),
        "discovered_candidates": discovered, "items": relevant,
    }
