-- Minutes of part of a meeting (phase 48): written while recording ("minutes so far") or for a
-- time range of a recorded meeting. Kept apart from `minutes`, in the order they were written.
CREATE TABLE partial_minutes (
    row_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    partial_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    range_start REAL NOT NULL,
    range_end REAL NOT NULL,
    origin TEXT NOT NULL,
    template TEXT,
    markdown TEXT NOT NULL
);

CREATE INDEX partial_minutes_session ON partial_minutes (session_id);
