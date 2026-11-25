# JSE News Signal

**Research question: does news predict JSE share returns?**

A student research project that ingests JSE prices and South African financial news, uses an LLM to extract
events and sentiment from each article, and tests honestly (walk-forward, after costs) whether those signals
predict returns relative to the market.

> Student research project. Not financial advice.

## Status

- [x] Week 1: Postgres in Docker, schema, daily price loader
- [ ] Week 2: news and company announcement ingestion
- [ ] Week 3: returns and market features
- [ ] Week 4-5: LLM extraction and evaluation
- [ ] Week 6-7: model and walk-forward backtest
- [ ] Week 8-9: AI summary, dashboard, write-up

## Run it locally

Requirements: Docker Desktop, Python 3.11+.

```bash
cp .env.example .env              # then edit the passwords
docker compose up -d              # Postgres on :5432, pgAdmin on http://localhost:8080
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/load_prices.py         # loads 2 years of daily prices
```

Check it worked:

```bash
docker exec -it jns-postgres psql -U jns -d jse_news_signal \
  -c "SELECT ticker, count(*), max(trade_date) FROM prices GROUP BY ticker ORDER BY ticker;"
```

## Project structure

```
data/companies.csv     companies tracked (JSE code, Yahoo symbol, name, sector)
sql/001_schema.sql     database tables, created on first start
src/load_prices.py     price loader (idempotent: safe to re-run)
docker-compose.yml     Postgres + pgAdmin
```

## Data notes

- Prices come from Yahoo Finance (`.JO` symbols). Yahoo quotes most JSE shares in **cents (ZAc)**; the loader
  stores rands.
- Benchmark: JSE All Share Index (`^J203.JO`).
- Every run is logged in the `pipeline_runs` table.
