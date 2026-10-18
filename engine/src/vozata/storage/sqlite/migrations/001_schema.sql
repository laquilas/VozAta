-- Sessions, transcripts, speakers, translations, minutes and action items (phase 31).

-- One row per session. `meta_json` holds the metadata fields without a column of their own (and
-- the order of every key); it stays NULL until the first `write_meta`, so a session that never
-- got metadata (a recording that failed to start) is not listed.
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    status TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_seconds REAL,
    last_heartbeat_at TEXT,
    language TEXT,
    language_source TEXT,
    app_language TEXT,
    template TEXT,
    title TEXT,
    meta_json TEXT,
    imported_from TEXT
);

CREATE INDEX sessions_status ON sessions (status);

-- Every transcript of a session: `raw` (live), `diarized` (phase 14) and `edited` (phase 21).
-- `row_id` keeps the written order and is the rowid of `segments_fts` (stable across VACUUM).
CREATE TABLE segments (
    row_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('raw', 'diarized', 'edited')),
    segment_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    start REAL NOT NULL,
    "end" REAL NOT NULL,
    text TEXT NOT NULL,
    words_json TEXT NOT NULL,
    edited INTEGER NOT NULL DEFAULT 0,
    UNIQUE (session_id, source, segment_id)
);

-- Live translations (phase 29): the last one of a segment wins.
CREATE TABLE translations (
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    segment_id TEXT NOT NULL,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (session_id, segment_id)
);

-- Speakers found by diarization (phase 14) and the names given to them (phase 16).
CREATE TABLE speakers (
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    speaker_id TEXT NOT NULL,
    name TEXT,
    PRIMARY KEY (session_id, speaker_id)
);

CREATE TABLE minutes (
    session_id TEXT PRIMARY KEY REFERENCES sessions (id) ON DELETE CASCADE,
    markdown TEXT NOT NULL,
    template TEXT,
    generated_at TEXT NOT NULL
);

-- Action items (phase 23) in their written order (`row_id`).
CREATE TABLE action_items (
    row_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    owner TEXT,
    due TEXT,
    source_ids_json TEXT NOT NULL,
    exported_url TEXT
);

CREATE INDEX action_items_session ON action_items (session_id);
