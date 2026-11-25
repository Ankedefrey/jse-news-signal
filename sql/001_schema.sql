-- JSE News Signal: database schema, week 1.
-- Runs automatically the first time the Postgres container starts.

-- One row per listed company we track.
CREATE TABLE IF NOT EXISTS companies (
    ticker        TEXT PRIMARY KEY,          -- JSE code, e.g. 'NPN'
    yahoo_symbol  TEXT NOT NULL UNIQUE,      -- e.g. 'NPN.JO'
    name          TEXT NOT NULL,
    sector        TEXT,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Daily prices. Stored in RANDS (Yahoo returns JSE prices in cents; the loader converts).
-- Primary key (ticker, trade_date) makes the loader idempotent: re-running updates, never duplicates.
CREATE TABLE IF NOT EXISTS prices (
    ticker       TEXT NOT NULL REFERENCES companies(ticker),
    trade_date   DATE NOT NULL,
    open_zar     NUMERIC(14,4),
    high_zar     NUMERIC(14,4),
    low_zar      NUMERIC(14,4),
    close_zar    NUMERIC(14,4) NOT NULL,
    adj_close_zar NUMERIC(14,4),
    volume       BIGINT,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);

-- Benchmark index levels (e.g. JSE All Share). Kept separate from company prices.
CREATE TABLE IF NOT EXISTS index_levels (
    index_symbol TEXT NOT NULL,              -- e.g. '^J203.JO'
    trade_date   DATE NOT NULL,
    close_level  NUMERIC(14,4) NOT NULL,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_symbol, trade_date)
);

-- News articles (filled from week 2). Full text is stored so every signal can be traced to its source.
CREATE TABLE IF NOT EXISTS articles (
    article_id    BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,      -- unique URL = no duplicate articles
    source        TEXT NOT NULL,             -- e.g. 'SENS', outlet name
    headline      TEXT NOT NULL,
    published_at  TIMESTAMPTZ NOT NULL,      -- needed to avoid look-ahead bias later
    body          TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What the LLM extracted from each article (filled from week 4).
-- evidence_text stores the exact passage the extraction was based on.
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id BIGSERIAL PRIMARY KEY,
    article_id    BIGINT NOT NULL REFERENCES articles(article_id),
    ticker        TEXT REFERENCES companies(ticker),
    event_type    TEXT,
    sentiment     NUMERIC(4,3) CHECK (sentiment BETWEEN -1 AND 1),
    confidence    NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    evidence_text TEXT,
    model         TEXT,
    cost_usd      NUMERIC(10,6),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every pipeline run is logged, so failures are loud, not silent.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    job_name     TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    rows_loaded  INTEGER,
    status       TEXT,                       -- 'ok' or 'error'
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_prices_date ON prices (trade_date);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_at);
