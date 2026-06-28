"""The idea store: deduped, counted memory of every challenge the octagon harvests.

A durable registry so the system remembers what it has already thought of: which ideas
recur (the crowd of personas keeps landing on them) versus which are genuinely NEW (the
signal you actually care about). Two tables:
  - features:    one row per distinct idea, with seen_count + first_seen + which persona
                 discovered it.
  - occurrences: an append-only log of every raw mention.

This adapter is stdlib-only (SQLite, no server, no external services). Dedup defaults to a
normalized token-overlap (Jaccard) similarity so paraphrases collapse without any model
dependency. For semantic dedup, inject `similarity=` with your own embedding-backed
function; the rest of the store is unchanged.

CLI:
    python -m adapters.store --init --db ideas.sqlite
    python -m adapters.store --ingest last_harvest.md --domain example --run r1 --db ideas.sqlite
    python -m adapters.store --report --domain example --db ideas.sqlite
    python -m adapters.store --probe "free text idea" --domain example --db ideas.sqlite
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.50   # token-overlap is less peaked than cosine; 0.50 splits paraphrase from distinct

DDL = """
CREATE TABLE IF NOT EXISTS features (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    domain        TEXT NOT NULL,
    canonical     TEXT NOT NULL,
    seen_count    INTEGER NOT NULL DEFAULT 1,
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen     TEXT NOT NULL DEFAULT (datetime('now')),
    first_persona TEXT,
    bucket        TEXT,
    data_need     TEXT,
    status        TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS occurrences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id  INTEGER REFERENCES features(id),
    domain      TEXT NOT NULL,
    run_id      TEXT,
    raw_text    TEXT NOT NULL,
    persona     TEXT,
    seen_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_features_domain ON features(domain);
CREATE INDEX IF NOT EXISTS idx_occ_feature ON occurrences(feature_id);
"""


# ---- text helpers ----------------------------------------------------------------
def _idea(raw):
    """The de-numbered, tag-stripped idea text we canonicalize on."""
    s = re.sub(r"^\s*\d+[.)]\s*", "", raw)
    s = s.split("|")[0]                    # drop the | from: ... | first test: ... tags
    return " ".join(s.split()).strip()


def _persona(raw):
    """Which seat(s) raised this challenge, from the harvester's 'from:' tag."""
    m = re.search(r"\|\s*from:\s*([^|]+)", raw, flags=re.I)
    return " ".join(m.group(1).split()).strip().lower() if m else None


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a, b):
    """Default similarity: token-overlap. No model dependency. Returns 0.0 to 1.0."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_challenges(text):
    """Split a harvest into individual challenge blocks (numbered list)."""
    items, cur = [], []
    for line in text.splitlines():
        if re.match(r"^\s*\d+[.)]\s", line):
            if cur:
                items.append(" ".join(cur).strip())
            cur = [line.strip()]
        elif cur:
            cur.append(line.strip())
    if cur:
        items.append(" ".join(cur).strip())
    return [it for it in items if re.match(r"^\s*\d+[.)]", it)]


# ---- the store -------------------------------------------------------------------
class IdeaStore:
    """SQLite-backed idea registry. `similarity(a, b) -> float in [0,1]` is injectable."""

    def __init__(self, path="ideas.sqlite", *, similarity=jaccard, threshold=DEFAULT_THRESHOLD):
        self._conn = sqlite3.connect(path)
        self._sim = similarity
        self._threshold = threshold
        self._conn.executescript(DDL)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _best_match(self, domain, idea):
        cur = self._conn.execute(
            "SELECT id, canonical FROM features WHERE domain=?", (domain,))
        best_id, best_canon, best_sim = None, None, -1.0
        for fid, canon in cur.fetchall():
            sim = self._sim(idea, canon)
            if sim > best_sim:
                best_id, best_canon, best_sim = fid, canon, sim
        return best_id, best_canon, best_sim

    def ingest_one(self, domain, raw, run_id=None):
        idea = _idea(raw)
        persona = _persona(raw)
        mid, mcanon, msim = self._best_match(domain, idea)
        is_new = mid is None or msim < self._threshold
        if is_new:
            cur = self._conn.execute(
                "INSERT INTO features(domain, canonical, first_persona) VALUES (?,?,?)",
                (domain, idea, persona))
            fid = cur.lastrowid
        else:
            fid = mid
            self._conn.execute(
                "UPDATE features SET seen_count=seen_count+1, last_seen=datetime('now') WHERE id=?",
                (fid,))
        self._conn.execute(
            "INSERT INTO occurrences(feature_id, domain, run_id, raw_text, persona) VALUES (?,?,?,?,?)",
            (fid, domain, run_id, raw, persona))
        self._conn.commit()
        return {"new": is_new, "sim": max(msim, 0.0), "feature_id": fid, "idea": idea,
                "persona": persona, "matched": None if is_new else mcanon}

    def ingest_harvest(self, path, domain, run_id=None):
        challenges = parse_challenges(Path(path).read_text(encoding="utf-8"))
        new = recur = 0
        for raw in challenges:
            r = self.ingest_one(domain, raw, run_id)
            who = f"[{r['persona']}]" if r["persona"] else "[?]"
            if r["new"]:
                new += 1
                print(f"  NEW  {who:<24} {r['idea'][:52]}")
            else:
                recur += 1
                print(f"  seen({r['sim']:.2f}) {who:<18} {r['idea'][:44]}")
        print(f"[store] run {run_id} / {domain}: {new} NEW, {recur} recurring, {len(challenges)} total")
        return {"new": new, "recurring": recur, "total": len(challenges)}

    def report(self, domain=None):
        q = ("SELECT seen_count, date(first_seen), first_persona, canonical FROM features "
             + ("WHERE domain=? " if domain else "")
             + "ORDER BY seen_count DESC, first_seen DESC")
        rows = self._conn.execute(q, (domain,) if domain else ()).fetchall()
        print(f"\n{'cnt':>4}  {'first_seen':<11}  {'by':<10}  idea")
        for cnt, first, persona, canon in rows:
            print(f"{cnt:>4}  {str(first):<11}  {str(persona or '-'):<10}  {canon[:60]}")
        print(f"[store] {len(rows)} distinct features{(' in ' + domain) if domain else ''}")
        return rows

    def probe(self, text, domain):
        """What would this match? Read-only; useful for tuning the threshold."""
        mid, mcanon, msim = self._best_match(domain, text)
        print(f"best match (sim {msim:.3f}): {mcanon}" if mid else "no features yet")
        return mid, mcanon, msim


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]

    def opt(flag, default=None):
        return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default

    db = opt("--db", "ideas.sqlite")
    domain = opt("--domain", "example")
    run_id = opt("--run", "run-local")
    threshold = float(opt("--threshold", DEFAULT_THRESHOLD))

    with IdeaStore(db, threshold=threshold) as store:
        if "--init" in a:
            print(f"[store] schema ready in {db}")
        if "--ingest" in a:
            store.ingest_harvest(opt("--ingest"), domain, run_id)
        if "--probe" in a:
            store.probe(opt("--probe"), domain)
        if "--report" in a:
            store.report(domain)
