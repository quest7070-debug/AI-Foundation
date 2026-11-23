"""Read-only lifecycle counts from the existing owner Work DB, never source text."""
from pathlib import Path
import os
import sqlite3
import stat
from threading import Lock
from time import monotonic, time


def lifecycle_status(path, *, wall_clock=time):
    unavailable = {"state": "UNVERIFIED"}
    try:
        path = Path(path)
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022):
            return unavailable
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            db.execute("PRAGMA query_only=ON")
            # One consistent snapshot; bounded VM work also caps malformed or
            # unexpectedly large owner indexes during normal UI refresh.
            remaining = [250]
            def bounded():
                remaining[0] -= 1
                return remaining[0] < 0
            db.set_progress_handler(bounded, 1000)
            db.execute("BEGIN")
            required = {"klm_atoms", "klm_atom_features", "klm_relation_reviews",
                        "klm_relations", "klm_drive_intake", "work_steps"}
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables:
                return unavailable
            from .klm_relation_review import unresolved_review_filter
            pending = unresolved_review_filter(db)
            queries = {
                "atoms": "SELECT COUNT(*) FROM klm_atoms",
                "missing_features": "SELECT COUNT(*) FROM klm_atoms a LEFT JOIN klm_atom_features f USING(atom_id) WHERE f.atom_id IS NULL",
                "unresolved_reviews": "SELECT COUNT(*) FROM klm_relation_reviews r WHERE " + pending,
                "relations": "SELECT COUNT(*) FROM klm_relations",
                "failed_intake": "SELECT COUNT(*) FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.position=0 AND w.status='FAILED'",
            }
            counts = {key: db.execute(sql).fetchone()[0]
                      for key, sql in queries.items()}
            if any(type(n) is not int or not 0 <= n <= 100000 for n in counts.values()):
                return unavailable
            result = {"state": "OBSERVED", **counts,
                      "observed_at": int(wall_clock())}
            # Owner-local, reason-only aggregation: no source content, atom
            # references, model conclusions, or automatic relation approval.
            # Legacy journals without a reason column stay observable but
            # cannot claim that the review breakdown is complete.
            columns = {row[1] for row in db.execute(
                "PRAGMA table_info(klm_relation_reviews)")}
            if "reason" in columns:
                reasons = {
                    "conflict": ("POTENTIAL_CONTRADICTION",),
                    "revision": ("REVISION_OR_REINTERPRETATION_REVIEW",
                                 "SAME_REVISION_INTERPRETATION_REVIEW"),
                    "qualifier": ("CONDITION_TIME_OR_ATTRIBUTION_REVIEW",),
                    "dependency": ("DEPENDENCY_REVIEW",),
                    "difference": ("UNRESOLVED_VALUE_DIFFERENCE",
                                   "POTENTIAL_SUPPORT_KIND_REVIEW"),
                    "duplicate": ("SAME_INFORMATION_CANDIDATE",),
                }
                buckets = {key: 0 for key in (*reasons, "other")}
                known = {reason: bucket for bucket, names in reasons.items()
                         for reason in names}
                # No reason text is passed beyond this owner process.
                for reason, total in db.execute("""
                        SELECT reason,COUNT(*) FROM klm_relation_reviews r
                        WHERE """ + pending + " GROUP BY reason"):
                    if type(total) is not int or total < 0:
                        return unavailable
                    buckets[known.get(reason, "other")] += total
                if sum(buckets.values()) != counts["unresolved_reviews"]:
                    return unavailable
                result["review_triage"] = buckets
            return result
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error):
        return unavailable


class CachedKlmLifecycleStatus:
    """Bounded read-only Work index with nonblocking concurrent UI projection.

    Do not hold a shared request lock while SQLite is reading the owner Work
    database. Concurrent requests see explicit UNVERIFIED, never stale counts
    masquerading as current and never a second database query.
    """

    def __init__(self, path, *, clock=monotonic):
        self.path, self.clock = Path(path), clock
        self.lock, self.saved, self.until = Lock(), None, 0
        self.observed_clock = 0
        self.busy = False

    def __call__(self):
        now = self.clock()
        refresh = False
        with self.lock:
            if self.saved is None or now >= self.until:
                if self.busy:
                    return {"state": "UNVERIFIED"}
                self.busy = True
                refresh = True
            else:
                row = dict(self.saved)
                observed_clock = self.observed_clock
        if refresh:
            try:
                fresh = lifecycle_status(self.path)
            except Exception:
                fresh = {"state": "UNVERIFIED"}
            with self.lock:
                self.saved = fresh
                self.observed_clock = self.clock()
                self.until = self.observed_clock + 30
                row = dict(self.saved)
                observed_clock = self.observed_clock
                self.busy = False
        if type(row.get("review_triage")) is dict:
            row["review_triage"] = dict(row["review_triage"])
        if row.get("state") == "OBSERVED":
            row["snapshot_age_seconds"] = max(0, int(
                (self.clock() if not refresh else observed_clock) - observed_clock))
        return row
