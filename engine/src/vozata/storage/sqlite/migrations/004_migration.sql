-- Import of the session folders recorded before phase 31 (phase 33).

-- `imported_from` (phase 31) holds the folder a session was imported from; `imported_at` when.
ALTER TABLE sessions ADD COLUMN imported_at TEXT;

CREATE INDEX sessions_imported_from ON sessions (imported_from);

-- Folders that could not be imported (unreadable JSON or WAV); they are not tried again until
-- their row is removed. `reason` is a locale key of `[migration]`; `detail` the error text.
CREATE TABLE migration_errors (
    folder TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL,
    at TEXT NOT NULL
);
