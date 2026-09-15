"""
Sessions survive a restart, restore never deletes history, and two
writers cannot both claim the same version.

"A restart" is simulated by building a second SessionStore on the same
directory: it has an empty memory cache, so everything it returns must
have come off disk.
"""

import tempfile

import pandas as pd
import pytest

from app.data_store import SessionStore, VersionConflictError


@pytest.fixture
def root():
    return tempfile.mkdtemp(prefix="store-")


def frame():
    return pd.DataFrame({
        "Category": ["Fmcg", None, "", float("nan")],
        # mixed ints and strings, like the real file's Page column
        "Page": [1, "4-5", 3, "A2"],
        "Width (cm)": [10, 20, 30, 40],
    })


def fill(df):
    new = df.copy(deep=True)
    new.loc[[1, 2, 3], "Category"] = "Uncategorized"
    return new


def test_session_survives_restart_with_values_exactly_preserved(root):
    first = SessionStore(root)
    s = first.create(frame(), filename="Sample.xlsx")

    reopened = SessionStore(root).get(s.session_id)

    assert reopened is not None
    assert reopened.filename == "Sample.xlsx"
    got = reopened.current_df["Category"].tolist()
    # None, "" and NaN must come back as three different things
    assert got[1] is None
    assert got[2] == ""
    assert isinstance(got[3], float) and pd.isna(got[3])
    assert reopened.current_df["Page"].tolist() == [1, "4-5", 3, "A2"]


def test_edits_audit_and_conversation_survive_restart(root):
    store = SessionStore(root)
    s = store.create(frame())
    store.apply_edit(s.session_id, fill(s.current_df), "fill_missing_value_bulk",
                     "Category", 3, "user asked", [{"row": 1}], excel={"items": []})
    s.conversation.append({"role": "user", "content": "fix it"})
    store.save_conversation(s)
    store.append_transcript(s, [{"role": "user", "text": "fix it"}])

    r = SessionStore(root).get(s.session_id)

    assert len(r.versions) == 2
    assert r.current_df["Category"].tolist()[1:] == ["Uncategorized"] * 3
    assert r.original_df["Category"].tolist()[1] is None
    assert r.audit_log[0].reason == "user asked"
    assert r.audit_log[0].excel == {"items": []}
    assert r.conversation == [{"role": "user", "content": "fix it"}]
    assert r.transcript == [{"role": "user", "text": "fix it"}]


def test_restore_appends_a_version_and_keeps_history(root):
    store = SessionStore(root)
    s = store.create(frame())
    store.apply_edit(s.session_id, fill(s.current_df), "fill", "Category", 3, "r", [])

    entry = store.restore(s.session_id, 0, rows_affected=3, diff_preview=[])

    assert entry.version == 2
    assert entry.operation == "restore"
    assert len(s.versions) == 3                     # v1 is still there
    assert [e.version for e in s.audit_log] == [1, 2]
    assert s.current_df["Category"].tolist()[1] is None


def test_restore_to_current_version_is_refused(root):
    store = SessionStore(root)
    s = store.create(frame())
    with pytest.raises(ValueError):
        store.restore(s.session_id, 0, rows_affected=0, diff_preview=[])


def test_second_writer_for_the_same_version_is_rejected(root):
    """Two server processes that both loaded v0 and both try to write v1."""
    a = SessionStore(root)
    s = a.create(frame())
    b = SessionStore(root)
    b.get(s.session_id)  # b now also believes v0 is current

    a.apply_edit(s.session_id, fill(s.current_df), "fill", "Category", 3, "a", [])
    with pytest.raises(VersionConflictError):
        b.apply_edit(s.session_id, frame(), "fill", "Category", 1, "b", [])

    # the winner's edit is intact on disk
    assert SessionStore(root).get(s.session_id).audit_log[0].reason == "a"


@pytest.mark.parametrize("bad", ["../../etc/passwd", "nope", "", "12345678-1234"])
def test_non_uuid_session_ids_never_reach_the_filesystem(root, bad):
    assert SessionStore(root).get(bad) is None
