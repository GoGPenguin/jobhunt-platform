-- 0002: digests, which jobs they included, and collector runs (spec 05).
-- jobhunt_app gets row access through the default privileges set in 0001.

CREATE TABLE digests (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sent_at              timestamptz NOT NULL,
    postings             integer NOT NULL,
    telegram_message_ids jsonb NOT NULL
);

CREATE TABLE notified_jobs (
    source      text NOT NULL,
    external_id text NOT NULL,
    digest_id   bigint NOT NULL REFERENCES digests (id),
    notified_at timestamptz NOT NULL,
    PRIMARY KEY (source, external_id),
    FOREIGN KEY (source, external_id) REFERENCES jobs (source, external_id) ON DELETE CASCADE
);

CREATE TABLE collection_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at  timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    ok          boolean NOT NULL,
    summary     jsonb NOT NULL,
    error       text
);
CREATE INDEX collection_runs_finished_at ON collection_runs (finished_at);
