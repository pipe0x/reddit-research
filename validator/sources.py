"""Data sources. Every source yields normalized items:

{kind: post|comment, id, subreddit, author, created_utc (epoch), score, num_comments,
 title, text, permalink, source}
"""
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "reddit-universal-scraper"
USER_AGENT = "reddit-idea-validator/0.1 (personal market research)"


def use_repo():
    """Make the reddit-universal-scraper modules importable."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))


def _post(p, source):
    return {"kind": "post", "id": str(p.get("id", "")).removeprefix("t3_"), "subreddit": p.get("subreddit", ""),
            "author": p.get("author") or "", "created_utc": float(p.get("created_utc") or 0),
            "score": p.get("score") or 0, "num_comments": p.get("num_comments") or 0,
            "title": p.get("title") or "", "text": p.get("selftext") or "",
            "permalink": p.get("permalink") or "", "source": source}


def _comment(c, source):
    return {"kind": "comment", "id": str(c.get("id", "")).removeprefix("t1_"), "subreddit": c.get("subreddit", ""),
            "author": c.get("author") or "", "created_utc": float(c.get("created_utc") or 0),
            "score": c.get("score") or 0, "num_comments": 0, "title": "", "text": c.get("body") or "",
            "permalink": c.get("permalink") or "", "source": source,
            "link_id": str(c.get("link_id") or "").removeprefix("t3_")}


class CachedHttp:
    """Polite JSON GETs: fixed pacing, backoff on 429/5xx, on-disk cache."""

    def __init__(self, cache_dir, min_interval=20, max_requests=250, max_wait=1800):
        self.max_wait = max_wait
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_requests = max_requests
        self.requests_made = 0
        self.next_at = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get_json(self, url, attempts=5):
        path = self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.requests_made >= self.max_requests:
            raise RuntimeError(f"Request budget ({self.max_requests}) exhausted; raise max_requests to continue.")
        attempt, waited = 0, 0.0
        while attempt < attempts:
            time.sleep(max(0.0, self.next_at - time.monotonic()))
            self.requests_made += 1
            started = time.monotonic()
            try:
                response = self.session.get(url, timeout=60)
            except requests.RequestException as e:
                error, attempt = e, attempt + 1
                self.next_at = time.monotonic() + 5 * 2 ** attempt
                continue
            elapsed = time.monotonic() - started
            self.next_at = time.monotonic() + self.min_interval
            reset = self._reset(response.headers)
            if response.headers.get("X-RateLimit-Remaining") == "0" and reset:
                self.next_at = time.monotonic() + reset
            payload = response.json() if "json" in response.headers.get("Content-Type", "") else {}
            # Arctic Shift answers both an exhausted query budget (instantly) and a query that ran too
            # long (after ~10s) with 422 "Timeout. Maybe slow down a bit".
            timeout_422 = response.status_code == 422 and "Timeout" in str(payload.get("error"))
            if (timeout_422 and elapsed < 3) or response.status_code == 429:
                wait = min(reset or 30, 120)
                if waited + wait > self.max_wait:
                    raise RuntimeError(f"rate limit persisted for {waited:.0f}s")
                waited += wait
                self.requests_made -= 1  # refused requests don't count against the budget
                print(f"      … Server-Limit, warte {wait:.0f}s", flush=True)
                self.next_at = time.monotonic() + wait
                continue
            if timeout_422 or response.status_code >= 500:
                error, attempt = RuntimeError(f"HTTP {response.status_code} (query too slow)"), attempt + 1
                self.next_at = time.monotonic() + max(reset or 0, 10 * 2 ** attempt)
                continue
            if response.status_code != 200 or payload.get("error"):
                raise RuntimeError(f"{url} -> HTTP {response.status_code}: {payload.get('error')}")
            path.write_text(json.dumps(payload), encoding="utf-8")
            return payload
        raise RuntimeError(f"Giving up on {url}: {error}")

    @staticmethod
    def _reset(headers):
        try:
            return float(headers.get("X-RateLimit-Reset")) + 1
        except (TypeError, ValueError):
            return None


class ArcticShift:
    """Public Reddit archive (arctic-shift.photon-reddit.com). Search must be scoped to a subreddit."""

    BASE = "https://arctic-shift.photon-reddit.com/api"
    name = "arcticshift"

    def __init__(self, http):
        self.http = http

    def _search(self, kind, subreddit, term, after, before, limit):
        endpoint, field, convert = (("posts", "query", _post) if kind == "post" else ("comments", "body", _comment))
        params = {"subreddit": subreddit, field: term, "limit": min(100, limit), "sort": "desc",
                  "after": int(after), "before": int(before)}
        data = self.http.get_json(f"{self.BASE}/{endpoint}/search?{urlencode(params)}")["data"] or []
        return [convert(d, self.name) for d in data]

    def monthly_counts(self, subreddit, term, after):
        """Real post counts per month (not capped like the sample). Best effort: None if the server refuses."""
        params = {"subreddit": subreddit, "query": term, "aggregate": "created_utc", "frequency": "month",
                  "after": int(after)}
        try:
            data = self.http.get_json(f"{self.BASE}/posts/search/aggregate?{urlencode(params)}", attempts=2)["data"] or []
        except RuntimeError:
            return None
        return {row["created_utc"][:7]: int(row["count"]) for row in data}

    def collect(self, idea, after, log=print):
        """Sample evenly per year slice so older years are represented, not just the newest 100 hits."""
        per_slice = idea.get("per_slice", 50)
        # Day-aligned boundaries keep request URLs (and thus the cache) stable between runs.
        end = (time.time() // 86400 + 1) * 86400
        after = after // 86400 * 86400
        slices = []
        while end - after >= 86400:
            start = end - 365 * 86400
            if start - after < 30 * 86400:  # fold a short remainder into this slice
                start = after
            slices.append((start, end))
            end = start
        self.trend = {}
        # Full-text comment search is too expensive for the archive; by default comments come from the
        # threads of the most discussed matching posts instead.
        kinds = ("post", "comment") if idea.get("comment_search") else ("post",)
        posts = []
        for subreddit in idea["subreddits"]:
            terms = idea.get("subreddit_terms", {}).get(subreddit, idea["search_terms"])
            for term in terms:
                counts = self.monthly_counts(subreddit, term, after) if idea.get("trend_counts", False) else None
                if counts:
                    self.trend[f"r/{subreddit} · {term}"] = counts
                for kind in kinds:
                    found = []
                    for start, stop in slices:
                        try:
                            found += self._search(kind, subreddit, term, start, stop, per_slice)
                        except RuntimeError as e:
                            log(f"   ! r/{subreddit} {kind}s '{term}' {time.strftime('%Y', time.gmtime(start))}: {e}")
                            if "budget" in str(e):
                                return
                    log(f"   r/{subreddit:<22} {kind+'s':<9} '{term}': {len(found)}")
                    posts += [i for i in found if i["kind"] == "post"]
                    yield from found
        from .analyze import term_regex
        anchors = term_regex(idea.get("relevance_terms") or idea["search_terms"])
        excludes = term_regex(idea.get("exclude_terms", []))

        def on_topic(p):
            text = f"{p['title']}\n{p['text']}"
            return any(r.search(text) for r in anchors) and not any(r.search(text) for r in excludes)

        threads = {p["id"]: p for p in posts if p["num_comments"] > 0 and on_topic(p)}
        ranked = sorted(threads.values(), key=lambda p: -p["num_comments"])[:idea.get("comment_threads", 25)]
        for post in ranked:
            try:
                data = self.http.get_json(f"{self.BASE}/comments/tree?{urlencode({'link_id': 't3_' + post['id'], 'limit': 100})}")
            except RuntimeError as e:
                log(f"   ! Kommentare zu {post['id']}: {e}")
                if "budget" in str(e):
                    return
                continue
            comments = [_comment(c, self.name) for c in _flatten(data.get("data") or [])]
            log(f"   r/{post['subreddit']:<22} Thread    '{post['title'][:40]}': {len(comments)} Kommentare")
            yield from comments


def _flatten(children):
    """Reddit-style comment tree -> flat list of comment dicts."""
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child["data"]
        yield data
        replies = data.get("replies")
        if isinstance(replies, dict):
            yield from _flatten((replies.get("data") or {}).get("children") or [])


class RedditOfficial:
    """Reddit's own search through the repo's OAuth client (needs approved credentials in the repo .env)."""

    name = "reddit"

    def __init__(self):
        use_repo()
        from scraper.reddit_client import RedditClient, listing_children
        self.client, self.children = RedditClient(), listing_children

    def collect(self, idea, after, log=print):
        self.client.validate()
        scopes = [None] + list(idea["subreddits"])
        for subreddit in scopes:
            for term in idea["search_terms"]:
                params = {"q": term, "sort": "relevance", "t": "all", "limit": 100, "raw_json": 1, "type": "link"}
                if subreddit:
                    params["restrict_sr"] = 1
                path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
                data = self.client.get_json(f"https://oauth.reddit.com{path}?{urlencode(params)}")
                found = [_post(c["data"], self.name) for c in self.children(data)]
                found = [p for p in found if p["created_utc"] >= after]
                log(f"   {('r/' + subreddit) if subreddit else 'all of reddit':<24} posts     '{term}': {len(found)}")
                yield from found


def from_browser_export(path, source="browser"):
    """Read a Browser Collector Companion export (the repo's extension), validated by the repo importer."""
    use_repo()
    from datetime import datetime, timezone
    from export.browser_import import validate_bundle
    posts, comments = validate_bundle(json.loads(Path(path).read_text(encoding="utf-8")))

    def epoch(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() if value else 0

    for p in posts:
        yield _post({**p, "created_utc": epoch(p["created_utc"])}, source)
    for c in comments:
        yield _comment({**c, "id": c["comment_id"], "created_utc": epoch(c["created_utc"]),
                        "permalink": c["post_permalink"].rstrip("/") + f"/{c['comment_id']}/"}, source)
