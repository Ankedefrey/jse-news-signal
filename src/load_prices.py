"""Load daily JSE prices from Yahoo Finance into Postgres.

Usage:
    python src/load_prices.py                 # last 2 years, all companies in data/companies.csv
    python src/load_prices.py --years 5
    python src/load_prices.py --tickers NPN,SHP

Safe to re-run: rows are upserted on (ticker, trade_date), so nothing is duplicated.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
COMPANIES_CSV = ROOT / "data" / "companies.csv"
BENCHMARK = "^J203.JO"  # JSE All Share Index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("load_prices")


def connect() -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


def upsert_companies(conn: psycopg.Connection, companies: pd.DataFrame) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO companies (ticker, yahoo_symbol, name, sector)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE
              SET yahoo_symbol = EXCLUDED.yahoo_symbol,
                  name = EXCLUDED.name,
                  sector = EXCLUDED.sector
            """,
            companies[["ticker", "yahoo_symbol", "name", "sector"]].itertuples(index=False),
        )
    conn.commit()


def download(symbol: str, start: date) -> pd.DataFrame:
    """Daily OHLCV for one symbol. Empty DataFrame if Yahoo has nothing."""
    df = yf.Ticker(symbol).history(start=start.isoformat(), interval="1d", auto_adjust=False)
    if df.empty:
        return df
    df = df.reset_index()
    df["trade_date"] = pd.to_datetime(df["Date"]).dt.date
    return df


def to_rands(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Yahoo quotes most JSE shares in cents (ZAc). Convert to rands so returns and charts make sense."""
    currency = (yf.Ticker(symbol).fast_info.get("currency") or "").upper()
    if currency in ("ZAC", ""):  # default to cents for .JO symbols if Yahoo doesn't say
        for col in ["Open", "High", "Low", "Close", "Adj Close"]:
            if col in df:
                df[col] = df[col] / 100.0
    return df


def upsert_prices(conn: psycopg.Connection, ticker: str, df: pd.DataFrame) -> int:
    rows = list(
        zip(
            [ticker] * len(df),
            df["trade_date"],
            df["Open"],
            df["High"],
            df["Low"],
            df["Close"],
            df["Adj Close"] if "Adj Close" in df else [None] * len(df),
            [int(v) if pd.notna(v) else None for v in df["Volume"]],
        )
    )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prices (ticker, trade_date, open_zar, high_zar, low_zar,
                                close_zar, adj_close_zar, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, trade_date) DO UPDATE
              SET open_zar = EXCLUDED.open_zar,
                  high_zar = EXCLUDED.high_zar,
                  low_zar = EXCLUDED.low_zar,
                  close_zar = EXCLUDED.close_zar,
                  adj_close_zar = EXCLUDED.adj_close_zar,
                  volume = EXCLUDED.volume,
                  loaded_at = now()
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def upsert_index(conn: psycopg.Connection, symbol: str, df: pd.DataFrame) -> int:
    rows = list(zip([symbol] * len(df), df["trade_date"], df["Close"]))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO index_levels (index_symbol, trade_date, close_level)
            VALUES (%s, %s, %s)
            ON CONFLICT (index_symbol, trade_date) DO UPDATE
              SET close_level = EXCLUDED.close_level, loaded_at = now()
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def log_run(conn, run_id: int | None, rows: int | None = None, status: str | None = None,
            error: str | None = None) -> int:
    with conn.cursor() as cur:
        if run_id is None:
            cur.execute("INSERT INTO pipeline_runs (job_name) VALUES ('load_prices') RETURNING run_id")
            run_id = cur.fetchone()[0]
        else:
            cur.execute(
                """UPDATE pipeline_runs SET finished_at = now(), rows_loaded = %s,
                   status = %s, error = %s WHERE run_id = %s""",
                (rows, status, error, run_id),
            )
    conn.commit()
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--tickers", help="comma-separated JSE codes; default = all in companies.csv")
    args = parser.parse_args()

    companies = pd.read_csv(COMPANIES_CSV)
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        companies = companies[companies["ticker"].isin(wanted)]
    start = date.today() - timedelta(days=365 * args.years)

    with connect() as conn:
        run_id = log_run(conn, None)
        total, failed = 0, []
        try:
            upsert_companies(conn, companies)
            for c in companies.itertuples(index=False):
                df = download(c.yahoo_symbol, start)
                if df.empty:
                    log.warning("No data for %s (%s) - check the Yahoo symbol", c.ticker, c.yahoo_symbol)
                    failed.append(c.ticker)
                    continue
                df = to_rands(df, c.yahoo_symbol)
                n = upsert_prices(conn, c.ticker, df)
                total += n
                log.info("%-4s %5d rows  last close R%.2f", c.ticker, n, df["Close"].iloc[-1])

            bench = download(BENCHMARK, start)
            if not bench.empty:
                total += upsert_index(conn, BENCHMARK, bench)
                log.info("Benchmark %s: %d rows", BENCHMARK, len(bench))

            status = "ok" if not failed else "partial"
            log_run(conn, run_id, total, status, ",".join(failed) or None)
            log.info("Done: %d rows loaded. Failed: %s", total, failed or "none")
            return 0
        except Exception as exc:  # log loudly, then fail
            conn.rollback()
            log_run(conn, run_id, total, "error", repr(exc))
            log.exception("Run failed")
            return 1


if __name__ == "__main__":
    sys.exit(main())
