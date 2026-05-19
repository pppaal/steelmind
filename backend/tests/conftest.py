import os
import tempfile

# Point the journal at a per-process temp file before backend.main is imported.
# Each pytest invocation gets its own DB so concurrent runs don't collide.
_JOURNAL_FD, _JOURNAL_PATH = tempfile.mkstemp(prefix="steelmind-test-", suffix=".db")
os.close(_JOURNAL_FD)
os.environ.setdefault("JOURNAL_DB", _JOURNAL_PATH)
