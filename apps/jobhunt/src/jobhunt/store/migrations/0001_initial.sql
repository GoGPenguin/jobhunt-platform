-- 0001: raw payloads, jobs and dead letters (spec 04, "Data model").
-- Applied by jobhunt_owner; jobhunt_app gets row access only.

CREATE TABLE raw_payloads (
    raw_ref      text PRIMARY KEY,
    origin       text NOT NULL,
    content_type text NOT NULL,
    content      bytea NOT NULL,
    fetched_at   timestamptz NOT NULL,
    stored_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX raw_payloads_fetched_at ON raw_payloads (fetched_at);

CREATE TABLE jobs (
    source         text NOT NULL,
    external_id    text NOT NULL,
    data           jsonb NOT NULL,        -- canonical Job, stored shape (schemas/job.v1.json)
    fingerprint    text NOT NULL,         -- posting key (jobhunt.store.fingerprint)
    language       text NOT NULL,
    collected_at   timestamptz NOT NULL,
    raw_ref        text NOT NULL,         -- not a foreign key: raw payloads expire (retention)
    parser_name    text NOT NULL,
    parser_version text NOT NULL,
    first_seen_at  timestamptz NOT NULL,
    last_seen_at   timestamptz NOT NULL,
    updated_at     timestamptz NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX jobs_fingerprint ON jobs (fingerprint);
CREATE INDEX jobs_first_seen_at ON jobs (first_seen_at);

CREATE TABLE dead_letters (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dedupe_key     text NOT NULL UNIQUE,  -- same payload stored twice adds it once
    source         text NOT NULL,
    raw_ref        text NOT NULL,
    parser_name    text NOT NULL,
    parser_version text NOT NULL,
    errors         jsonb NOT NULL,
    parsed_record  jsonb NOT NULL,
    failed_at      timestamptz NOT NULL
);

-- Row access for the application role, now and for tables added by later migrations.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO jobhunt_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jobhunt_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunt_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jobhunt_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunt_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO jobhunt_app;
-- The migration history is the owner's alone.
REVOKE INSERT, UPDATE, DELETE ON schema_migrations FROM jobhunt_app;
