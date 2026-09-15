"""
data_store.py
--------------
Holds the working dataframe for a session, with:
  - the ORIGINAL upload kept immutable, always
  - a version history (v0 = original, v1, v2, ... after each edit)
  - a full audit log: what changed, which rows, why (the conversation
    turn that triggered it), when

Why this exists: once an agent can WRITE to real business data, "it
made a change" is not good enough - a person needs to see exactly what
changed and undo it if the agent got it wrong.

Persistence
-----------
Sessions survive a server restart. Disk is the source of truth; memory
is a cache in front of it.

  data/store.db                      SQLite: sessions, version index,
                                     audit log, agent conversation,
                                     UI transcript
  data/snapshots/<session>/v<n>.pkl.gz   one full dataframe per version

Why pickle and not Parquet for the snapshots: Parquet was the first
choice and it fails on this dataset. The `Page` column mixes integers
with strings such as "4-5", and pyarrow refuses a mixed-type column. The
only way round that is converting the whole column to text, which
changes the data the brief says to keep as-is. Pickle round-trips the
real file identically, including keeping None, NaN and "" distinct -
the distinction diagnostics depends on. The usual objection to pickle is
that loading an untrusted file can execute code; these files are only
ever written by this server and never accepted from a client.

Restore is non-destructive
--------------------------
Restoring an earlier version APPENDS a new version whose data equals the
old one, rather than deleting the versions after it. Deleting would also
delete their audit entries, and the audit log is the record that makes
agent edits defensible. With append-only history nothing is ever lost,
so a restore needs no "are you sure" prompt.

Concurrency
-----------
(session_id, version) is the primary key of the version index. Two
writers that both read version N and both try to write N+1 cannot both
succeed: the second insert fails and raises VersionConflictError instead
of silently replacing the first edit. Its edit was computed from data
that is now stale, so retrying it blindly would be a lost update - the
caller has to recompute on the fresh version.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.config import settings

logger = logging.getLogger("ad_intel.data_store")

# Sessions held fully in memory at once. Disk is authoritative, so an
# evicted session is simply reloaded on its next request.
_CACHE_SIZE = 8


class VersionConflictError(Exception):
    """Another writer created this version first."""


@dataclass
class AuditEntry:
    version: int
    timestamp: float
    operation: str
    scope: str
    rows_affected: int
    reason: str          # the user's request / conversation context that triggered this
    diff_preview: list = field(default_factory=list)  # small before/after sample
    excel: dict | None = None  # how to reproduce this change in Excel, see excel_formulas.py


@dataclass
class Session:
    session_id: str
    original_df: pd.DataFrame       # never mutated after upload
    current_df: pd.DataFrame        # latest version
    versions: list = field(default_factory=list)   # list[pd.DataFrame], index 0 = original
    audit_log: list = field(default_factory=list)  # list[AuditEntry]
    conversation: list = field(default_factory=list)  # chat history for the agent
    transcript: list = field(default_factory=list)    # chat as the UI renders it
    filename: str = "Spreadsheet.xlsx"
    created_at: float = field(default_factory=time.time)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    version     INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (session_id, version)
);
CREATE TABLE IF NOT EXISTS audit (
    session_id    TEXT NOT NULL,
    version       INTEGER NOT NULL,
    timestamp     REAL NOT NULL,
    operation     TEXT NOT NULL,
    scope         TEXT NOT NULL,
    rows_affected INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    diff_preview  TEXT NOT NULL,
    excel         TEXT,
    PRIMARY KEY (session_id, version)
);
CREATE TABLE IF NOT EXISTS conversation (
    session_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    message     TEXT NOT NULL,
    PRIMARY KEY (session_id, position)
);
CREATE TABLE IF NOT EXISTS transcript (
    session_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    message     TEXT NOT NULL,
    PRIMARY KEY (session_id, position)
);
"""


def _valid_session_id(session_id: str) -> bool:
    """Session ids reach this module straight from URL paths and are used
    to build snapshot file paths, so anything that is not a canonical
    UUID is rejected before it can become '../../somewhere'."""
    try:
        return str(uuid.UUID(session_id)) == session_id
    except (ValueError, AttributeError, TypeError):
        return False


def _dumps(value) -> str:
    return json.dumps(value, default=str)


class SessionStore:
    def __init__(self, data_dir: str | Path | None = None):
        self._root = Path(data_dir) if data_dir is not None else settings.resolved_data_dir
        self._snapshots = self._root / "snapshots"
        self._snapshots.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "store.db"
        self._cache: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.RLock()
        with self._db() as db:
            db.executescript(_SCHEMA)

    # ---------------------------------------------------------------- plumbing

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _snapshot_path(self, session_id: str, version: int) -> Path:
        return self._snapshots / session_id / f"v{version}.pkl.gz"

    def _write_snapshot(self, session_id: str, version: int, df: pd.DataFrame) -> Path:
        path = self._snapshot_path(session_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a crash mid-write never leaves a truncated
        # file sitting where a valid version should be.
        tmp = path.with_suffix(".tmp")
        df.to_pickle(tmp, compression="gzip")
        tmp.replace(path)
        return path

    def _remember(self, session: Session) -> None:
        self._cache[session.session_id] = session
        self._cache.move_to_end(session.session_id)
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)

    # ---------------------------------------------------------------- sessions

    def create(self, df: pd.DataFrame, filename: str = "Spreadsheet.xlsx") -> Session:
        session_id = str(uuid.uuid4())
        original = df.copy(deep=True)
        now = time.time()
        with self._lock:
            self._write_snapshot(session_id, 0, original)
            with self._db() as db:
                db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, filename, now))
                db.execute("INSERT INTO versions VALUES (?, 0, ?)", (session_id, now))
            session = Session(
                session_id=session_id,
                original_df=original,
                current_df=original.copy(deep=True),
                versions=[original.copy(deep=True)],
                filename=filename,
                created_at=now,
            )
            self._remember(session)
        return session

    def get(self, session_id: str) -> Session | None:
        if not _valid_session_id(session_id):
            return None
        with self._lock:
            cached = self._cache.get(session_id)
            if cached is not None:
                self._cache.move_to_end(session_id)
                return cached
            session = self._load(session_id)
            if session is not None:
                self._remember(session)
            return session

    def _load(self, session_id: str) -> Session | None:
        with self._db() as db:
            row = db.execute(
                "SELECT filename, created_at FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            filename, created_at = row
            version_numbers = [v for (v,) in db.execute(
                "SELECT version FROM versions WHERE session_id = ? ORDER BY version", (session_id,)
            )]
            audit_rows = db.execute(
                "SELECT version, timestamp, operation, scope, rows_affected, reason, diff_preview, excel "
                "FROM audit WHERE session_id = ? ORDER BY version", (session_id,)
            ).fetchall()
            conversation = [json.loads(m) for (m,) in db.execute(
                "SELECT message FROM conversation WHERE session_id = ? ORDER BY position", (session_id,)
            )]
            transcript = [json.loads(m) for (m,) in db.execute(
                "SELECT message FROM transcript WHERE session_id = ? ORDER BY position", (session_id,)
            )]

        versions = []
        for v in version_numbers:
            path = self._snapshot_path(session_id, v)
            if not path.exists():
                logger.error("Snapshot missing for session %s v%s at %s", session_id, v, path)
                return None
            versions.append(pd.read_pickle(path, compression="gzip"))

        logger.info("Session %s loaded from disk (%s versions)", session_id, len(versions))
        return Session(
            session_id=session_id,
            original_df=versions[0],
            current_df=versions[-1].copy(deep=True),
            versions=versions,
            audit_log=[
                AuditEntry(
                    version=a[0], timestamp=a[1], operation=a[2], scope=a[3],
                    rows_affected=a[4], reason=a[5], diff_preview=json.loads(a[6]),
                    excel=json.loads(a[7]) if a[7] else None,
                )
                for a in audit_rows
            ],
            conversation=conversation,
            transcript=transcript,
            filename=filename,
            created_at=created_at,
        )

    # ---------------------------------------------------------------- edits

    def apply_edit(self, session_id: str, new_df: pd.DataFrame, operation: str,
                   scope: str, rows_affected: int, reason: str,
                   diff_preview: list, excel: dict | None = None) -> AuditEntry:
        with self._lock:
            session = self.get(session_id)
            if session is None:
                raise KeyError(session_id)

            version = len(session.versions)
            entry = AuditEntry(
                version=version,
                timestamp=time.time(),
                operation=operation,
                scope=scope,
                rows_affected=rows_affected,
                reason=reason,
                diff_preview=diff_preview,
                excel=excel,
            )

            try:
                with self._db() as db:
                    # The insert is the claim on this version number. It
                    # happens before the snapshot is written, so a writer
                    # that loses the race never overwrites the winner's file.
                    db.execute("INSERT INTO versions VALUES (?, ?, ?)",
                               (session_id, version, entry.timestamp))
                    db.execute(
                        "INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (session_id, version, entry.timestamp, operation, scope,
                         rows_affected, reason, _dumps(diff_preview),
                         _dumps(excel) if excel else None),
                    )
                    self._write_snapshot(session_id, version, new_df)
            except sqlite3.IntegrityError as e:
                # Someone else wrote this version. Drop our stale copy so
                # the next read sees theirs.
                self._cache.pop(session_id, None)
                raise VersionConflictError(
                    f"Version {version} of this session was created by another request. "
                    "The data changed underneath this edit; re-run it against the latest version."
                ) from e

            session.current_df = new_df
            session.versions.append(new_df.copy(deep=True))
            session.audit_log.append(entry)
            return entry

    def restore(self, session_id: str, to_version: int, rows_affected: int,
                diff_preview: list) -> AuditEntry:
        """Makes an earlier version current again by appending a copy of it
        as a new version. History after `to_version` is kept, not deleted."""
        with self._lock:
            session = self.get(session_id)
            if session is None:
                raise KeyError(session_id)
            current = len(session.versions) - 1
            if to_version < 0 or to_version > current:
                raise ValueError(f"Invalid version {to_version}; valid range 0-{current}")
            if to_version == current:
                raise ValueError(f"v{to_version} is already the current version.")

            return self.apply_edit(
                session_id=session_id,
                new_df=session.versions[to_version].copy(deep=True),
                operation="restore",
                scope=f"v{to_version}",
                rows_affected=rows_affected,
                reason=f"Restored the data to v{to_version}",
                diff_preview=diff_preview,
            )

    # ---------------------------------------------------------------- chat

    def save_conversation(self, session: Session) -> None:
        """Persists the agent's message history, so "fix it" still has a
        referent after a restart."""
        with self._lock, self._db() as db:
            db.execute("DELETE FROM conversation WHERE session_id = ?", (session.session_id,))
            db.executemany(
                "INSERT INTO conversation VALUES (?, ?, ?)",
                [(session.session_id, i, _dumps(m)) for i, m in enumerate(session.conversation)],
            )

    def append_transcript(self, session: Session, messages: list[dict]) -> None:
        """Persists chat as the UI shows it, so a reload restores the panel."""
        with self._lock, self._db() as db:
            start = len(session.transcript)
            db.executemany(
                "INSERT INTO transcript VALUES (?, ?, ?)",
                [(session.session_id, start + i, _dumps(m)) for i, m in enumerate(messages)],
            )
            session.transcript.extend(messages)


session_store = SessionStore()
