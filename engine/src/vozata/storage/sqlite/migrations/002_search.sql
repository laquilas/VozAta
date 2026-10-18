-- Full-text search over each session's best transcript (phases 22 and 31).
--
-- `segments_fts` holds, for every session, only the segments of its best source (edited, then
-- diarized, then raw); its rowid is `segments.row_id`. The triggers keep it in sync on every
-- insert and delete of `segments`, so writers never touch it. Same tokenizer as the old
-- `index.db`: accent- and case-insensitive, `decisao` finds `decisão`.

CREATE VIRTUAL TABLE segments_fts USING fts5 (
    session_id UNINDEXED,
    segment_id UNINDEXED,
    start UNINDEXED,
    speaker_id UNINDEXED,
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- A new segment of the best source is indexed and replaces the worse sources of its session.
CREATE TRIGGER segments_fts_insert AFTER INSERT ON segments
WHEN NOT EXISTS (
    SELECT 1 FROM segments AS other
    WHERE other.session_id = NEW.session_id
      AND (CASE other.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
        > (CASE NEW.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
)
BEGIN
    DELETE FROM segments_fts WHERE rowid IN (
        SELECT row_id FROM segments
        WHERE session_id = NEW.session_id
          AND (CASE source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
            < (CASE NEW.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
    );
    INSERT INTO segments_fts (rowid, session_id, segment_id, start, speaker_id, text)
    VALUES (NEW.row_id, NEW.session_id, NEW.segment_id, NEW.start, NEW.speaker_id, NEW.text);
END;

-- A deleted segment leaves the index; when the last segment of the best source goes (an edit
-- reverted), the next best source of the session is indexed again.
CREATE TRIGGER segments_fts_delete AFTER DELETE ON segments
BEGIN
    DELETE FROM segments_fts WHERE rowid = OLD.row_id;
    INSERT INTO segments_fts (rowid, session_id, segment_id, start, speaker_id, text)
    SELECT row_id, session_id, segment_id, start, speaker_id, text FROM segments AS kept
    WHERE kept.session_id = OLD.session_id
      AND NOT EXISTS (
          SELECT 1 FROM segments AS better
          WHERE better.session_id = OLD.session_id
            AND (CASE better.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
             >= (CASE OLD.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
      )
      AND (CASE kept.source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END) = (
          SELECT MAX(CASE source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
          FROM segments WHERE session_id = OLD.session_id
      )
      AND NOT EXISTS (SELECT 1 FROM segments_fts WHERE rowid = kept.row_id);
END;

-- A changed segment (no writer updates rows today) is indexed with its new values.
CREATE TRIGGER segments_fts_update AFTER UPDATE ON segments
BEGIN
    UPDATE segments_fts
    SET session_id = NEW.session_id, segment_id = NEW.segment_id, start = NEW.start,
        speaker_id = NEW.speaker_id, text = NEW.text
    WHERE rowid = OLD.row_id;
END;

-- Segments written before this version.
INSERT INTO segments_fts (rowid, session_id, segment_id, start, speaker_id, text)
SELECT row_id, session_id, segment_id, start, speaker_id, text FROM segments AS kept
WHERE (CASE source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END) = (
    SELECT MAX(CASE source WHEN 'edited' THEN 3 WHEN 'diarized' THEN 2 ELSE 1 END)
    FROM segments WHERE session_id = kept.session_id
);
