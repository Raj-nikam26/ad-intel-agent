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
from app.snapshot_storage import LocalSnapshots, make_snapshot_storage

logger = logging.getLogger("ad_intel.data_store")

try:  # PostgreSQL driver is only needed when DATABASE_URL points at Postgres
    import psycopg
    _INTEGRITY_ERRORS: tuple = (sqlite3.IntegrityError, psycopg.errors.UniqueViolation)
except ImportError:  # pragma: no cover
    psycopg = None
    _INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


class _PostgresConnection:
    """Gives a psycopg connection the small sqlite3-style surface this
    module uses, so the SQL below is written once. SQLite placeholders
    ('?') are rewritten to psycopg's ('%s')."""

    def __init__(self, url: str):
        self._conn = psycopg.connect(url)

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        return self._conn.execute(self._sql(sql), params)

    def executemany(self, sql, rows):
        with self._conn.cursor() as cur:
            cur.executemany(self._sql(sql), list(rows))

    def executescript(self, script):
        for statement in filter(None, (s.strip() for s in script.split(";"))):
            self._conn.execute(statement)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

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
    user_id: str | None = None   # who asked for it; an audit entry without an actor is half a record
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
    owner_id: str | None = None
    mapping: dict | None = None      # inferred column roles, see schema_profile.py
    created_at: float = field(default_factory=time.time)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    provider_id TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT NOT NULL,
    picture     TEXT,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    owner_id    TEXT
);
CREATE TABLE IF NOT EXISTS versions (
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    version     INTEGER NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (session_id, version)
);
CREATE TABLE IF NOT EXISTS audit (
    session_id    TEXT NOT NULL,
    version       INTEGER NOT NULL,
    timestamp     DOUBLE PRECISION NOT NULL,
    operation     TEXT NOT NULL,
    scope         TEXT NOT NULL,
    rows_affected INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    diff_preview  TEXT NOT NULL,
    excel         TEXT,
    user_id       TEXT,
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
        explicit = data_dir is not None
        self._root = Path(data_dir) if explicit else settings.resolved_data_dir
        self._root.mkdir(parents=True, exist_ok=True)
        # An explicit directory (tests) always means fully local storage.
        self._postgres_url = settings.database_url if (settings.use_postgres and not explicit) else ""
        self._snapshots = (LocalSnapshots(self._root / "snapshots") if explicit
                           else make_snapshot_storage(self._root / "snapshots"))
        self._db_path = self._root / "store.db"
        self._cache: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.RLock()
        self._listeners: list = []
        with self._db() as db:
            db.executescript(_SCHEMA)
        # Databases created before sign-in existed lack these columns.
        # Each ALTER runs on its own connection: in PostgreSQL a failed
        # statement poisons the rest of its transaction.
        for table, column in (("sessions", "owner_id"), ("audit", "user_id")):
            try:
                with self._db() as db:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            except Exception:  # noqa: BLE001 - column already exists
                pass
        logger.info("Session store: %s, snapshots: %s",
                    "PostgreSQL" if self._postgres_url else f"SQLite at {self._db_path}",
                    type(self._snapshots).__name__)

    def add_listener(self, fn) -> None:
        """fn(session_id, version, before_df, after_df) runs after every new
        version is saved. The graph sync hangs off this."""
        self._listeners.append(fn)

    def _notify(self, session_id: str, version: int, before, after) -> None:
        for fn in self._listeners:
            try:
                fn(session_id, version, before, after)
            except Exception:  # noqa: BLE001 - a listener must never undo a saved edit
                logger.exception("Version listener failed for %s v%s", session_id, version)

    # ---------------------------------------------------------------- plumbing

    @contextmanager
    def _db(self):
        if self._postgres_url:
            conn = _PostgresConnection(self._postgres_url)
        else:
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

    def _write_snapshot(self, session_id: str, version: int, df: pd.DataFrame) -> None:
        self._snapshots.write(session_id, version, df)

    def _remember(self, session: Session) -> None:
        self._cache[session.session_id] = session
        self._cache.move_to_end(session.session_id)
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)

    # ---------------------------------------------------------------- sessions

    def create(self, df: pd.DataFrame, filename: str = "Spreadsheet.xlsx",
               owner_id: str | None = None) -> Session:
        session_id = str(uuid.uuid4())
        original = df.copy(deep=True)
        now = time.time()
        with self._lock:
            self._write_snapshot(session_id, 0, original)
            with self._db() as db:
                db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (session_id, filename, now, owner_id))
                db.execute("INSERT INTO versions VALUES (?, 0, ?)", (session_id, now))
            session = Session(
                session_id=session_id,
                original_df=original,
                current_df=original.copy(deep=True),
                versions=[original.copy(deep=True)],
                filename=filename,
                owner_id=owner_id,
                created_at=now,
            )
            self._remember(session)
        self._notify(session_id, 0, None, original)
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
                "SELECT filename, created_at, owner_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            filename, created_at, owner_id = row
            version_numbers = [v for (v,) in db.execute(
                "SELECT version FROM versions WHERE session_id = ? ORDER BY version", (session_id,)
            )]
            audit_rows = db.execute(
                "SELECT version, timestamp, operation, scope, rows_affected, reason, diff_preview, excel, user_id "
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
            df = self._snapshots.read(session_id, v)
            if df is None:
                logger.error("Snapshot missing for session %s v%s", session_id, v)
                return None
            versions.append(df)

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
                    excel=json.loads(a[7]) if a[7] else None, user_id=a[8],
                )
                for a in audit_rows
            ],
            conversation=conversation,
            transcript=transcript,
            filename=filename,
            owner_id=owner_id,
            created_at=created_at,
        )

    # ---------------------------------------------------------------- edits

    def apply_edit(self, session_id: str, new_df: pd.DataFrame, operation: str,
                   scope: str, rows_affected: int, reason: str,
                   diff_preview: list, excel: dict | None = None,
                   user_id: str | None = None) -> AuditEntry:
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
                user_id=user_id,
            )

            try:
                with self._db() as db:
                    # The insert is the claim on this version number. It
                    # happens before the snapshot is written, so a writer
                    # that loses the race never overwrites the winner's file.
                    db.execute("INSERT INTO versions VALUES (?, ?, ?)",
                               (session_id, version, entry.timestamp))
                    db.execute(
                        "INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (session_id, version, entry.timestamp, operation, scope,
                         rows_affected, reason, _dumps(diff_preview),
                         _dumps(excel) if excel else None, user_id),
                    )
                    self._write_snapshot(session_id, version, new_df)
            except _INTEGRITY_ERRORS as e:
                # Someone else wrote this version. Drop our stale copy so
                # the next read sees theirs.
                self._cache.pop(session_id, None)
                raise VersionConflictError(
                    f"Version {version} of this session was created by another request. "
                    "The data changed underneath this edit; re-run it against the latest version."
                ) from e

            before = session.current_df
            session.current_df = new_df
            session.versions.append(new_df.copy(deep=True))
            session.audit_log.append(entry)
        self._notify(session_id, version, before, new_df)
        return entry

    def restore(self, session_id: str, to_version: int, rows_affected: int,
                diff_preview: list, user_id: str | None = None) -> AuditEntry:
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
                user_id=user_id,
            )

    # ---------------------------------------------------------------- users

    def upsert_user(self, provider_id: str, email: str, name: str, picture: str = "") -> dict:
        """Creates or refreshes a user, keyed on the identity provider's id
        rather than the email, which a person can change."""
        with self._lock, self._db() as db:
            row = db.execute("SELECT user_id FROM users WHERE provider_id = ?", (provider_id,)).fetchone()
            if row:
                user_id = row[0]
                db.execute("UPDATE users SET email = ?, name = ?, picture = ? WHERE user_id = ?",
                           (email, name, picture, user_id))
            else:
                user_id = str(uuid.uuid4())
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                           (user_id, provider_id, email, name, picture, time.time()))
        return {"id": user_id, "email": email, "name": name, "picture": picture}

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
