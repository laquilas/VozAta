-- The request history of a meeting (phase 59): voice commands, and minutes so far / of a range /
-- again, action items and questions asked from the app, with what became of them.
CREATE TABLE requests (
    row_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    at REAL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    result_id TEXT,
    message TEXT,
    finished_at TEXT
);

CREATE INDEX requests_session ON requests (session_id);
