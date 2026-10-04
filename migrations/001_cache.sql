-- API response cache (CLAUDE.md §6). Bodies and records are stored verbatim, because citation
-- excerpts are checked as substrings of the cached record (§7.6).

-- One row per fetched page, keyed on the canonical API params, so an identical request reuses
-- identical records.
CREATE TABLE api_pages (
    params_key  text        NOT NULL,
    page_index  integer     NOT NULL CHECK (page_index >= 0),
    total_count integer     NOT NULL CHECK (total_count >= 0),
    body        jsonb       NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (params_key, page_index)
);

-- One row per trial, for exact NCT ID lookup when building and checking citations.
CREATE TABLE trials (
    nct_id     text        PRIMARY KEY CHECK (nct_id ~ '^NCT[0-9]{8}$'),
    record     jsonb       NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
