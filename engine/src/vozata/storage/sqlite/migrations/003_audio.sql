-- Recorded audio (phase 32): mono 16-bit PCM in chunks of about one second per channel.
-- `start_frame` is the sample index of the chunk's first sample in its track; `frames` its
-- number of samples (`length(pcm) / 2`). The mixed track is never stored (mixed on read).
CREATE TABLE audio_chunks (
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('mic', 'system')),
    seq INTEGER NOT NULL,
    start_frame INTEGER NOT NULL,
    frames INTEGER NOT NULL,
    pcm BLOB NOT NULL,
    PRIMARY KEY (session_id, channel, seq)
);

CREATE INDEX audio_chunks_start ON audio_chunks (session_id, channel, start_frame);
