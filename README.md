# Onyx EGM Performance Pipeline

A local dbt + PostgreSQL pipeline that ingests, transforms, and quality-checks
EGM (electronic gaming machine) performance data, built for the Onyx Gaming
data engineer technical challenge.

One command runs the whole thing:

```bash
python 4000_pipeline/run_pipeline.py
```

See [Getting started](#getting-started) for this step by step.

## Table of contents

- [Approach](#approach)
- [Docker: what it runs and why](#docker-what-it-runs-and-why)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Running the pipeline](#running-the-pipeline)
- [Data transformations](#data-transformations)
- [Data quality checks](#data-quality-checks)
- [Incremental loads](#incremental-loads)
- [Design notes / assumptions](#design-notes--assumptions)
- [Troubleshooting](#troubleshooting)

## Approach

The pipeline follows a standard **EL-T** (extract/load, then transform) shape,
deliberately keeping ingestion "dumb" and pushing all typing, validation, and
business logic into dbt, where it's testable and version-controlled as SQL:

```
CSV  --ingest-->  raw.egm_performance  --dbt-->  staging  --dbt-->  marts
(1000_data/*.csv)  (Postgres, text        (typed,           (turnover, revenue,
                    columns, upserted)      validated)         daily summary)
```

1. **Ingest** (`2000_ingestion/ingest_csv_to_postgres.py`) loads the CSV into
   `raw.egm_performance` in Postgres, upserting on the natural key
   `(bus_date, venue_code, egm_description, fp)`. Every column is loaded as
   text, preserving the source data exactly as it arrived — typing and
   validation are dbt's job, not the loader's. This means a malformed value
   surfaces later as a clear dbt test failure or compile error, not a silent
   pandas coercion at load time.
2. **Transform** (`3000_dbt_project/`) casts and validates the raw data in a
   staging model, then builds three marts on top of it.
3. **Test**: dbt tests run as part of the same `dbt build` step, gating the
   raw data before it's trusted and the marts after they're built. Nothing
   downstream reads data that hasn't passed the tests upstream of it.
4. **Document**: `dbt docs generate` builds a browsable docs site describing
   every model, column, source, and test — so the pipeline documents itself
   instead of relying on this file staying in sync by hand.

Why this split matters: the ingestion script is the only piece of Python that
touches raw data, and it does the minimum possible (read CSV, upsert rows).
Everything with actual logic — casting, validation, aggregation — lives in
dbt models and tests, where it's declarative, diffable, and has its own test
framework, rather than buried in imperative Python.

## Docker: what it runs and why

This project does **not** build a custom Docker image and there is no
`Dockerfile`. `docker-compose.yml` at the repo root does one thing: pull and
run the official, unmodified **`postgres:15`** image from Docker Hub.

```yaml
services:
  postgres:
    image: postgres:15        # stock image, no build step
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: onyx
    ports:
      - "5432:5432"            # host:container — change the left side if 5432 is taken
    volumes:
      - pgdata:/var/lib/postgresql/data   # named volume: data survives container restarts
```

There's nothing to install *inside* Docker — the stock Postgres image already
bundles everything the database itself needs. The library your machine needs
is on the **Python** side, not the Docker side: `psycopg2-binary` (a
PostgreSQL client driver for Python) and `sqlalchemy`, both in
`requirements.txt`, are what let the ingestion script and dbt talk to the
Postgres server running inside the container. Docker just hosts the server;
Python's Postgres client libraries are how the rest of the pipeline reaches
it over `localhost:5432`.

`4000_pipeline/run_pipeline.py` manages the container for you: it checks
whether Postgres is already reachable on `localhost:5432` and, if not, runs
`docker compose up -d` and waits (up to 30s) for it to come up. You never
need to run `docker compose` yourself unless you want to.

Useful Docker commands if you want to manage it manually:

```bash
docker compose up -d       # start Postgres in the background
docker compose ps          # check it's running
docker compose logs -f     # tail Postgres logs
docker compose down        # stop and remove the container (data volume persists)
docker compose down -v     # stop and remove the container AND wipe all data
```

If you'd rather not use Docker at all, run `python 4000_pipeline/run_pipeline.py --no-docker`
against any reachable Postgres instance — see [Configuration](#configuration)
for how to point it at a non-default host.

## Getting started

This section is the complete, step-by-step path from a fresh `git clone` to
a finished pipeline run.

### Step 0 — Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Git | any | to clone the repo |
| Python | 3.10 or newer | developed and tested against 3.13. Check yours with `python --version` (or `python3 --version` on macOS/Linux) |
| Docker Desktop (or Docker Engine + Compose plugin) | any recent version | must provide `docker compose` (v2, no hyphen); runs Postgres locally — see [Docker](#docker-what-it-runs-and-why) |
| Internet access | — | first run pulls the `postgres:15` base image and installs `dbt-core`/`dbt-postgres`/`dbt_utils` |

You do not need Postgres or dbt installed yourself — Postgres comes from the
Docker image, and dbt is installed automatically from `requirements.txt`.

### Step 1 — Clone the repo

```bash
git clone <this repo>
cd Onyx_egm_pipeline
```

### Step 2 — Set up the virtual environment

1. **Create a virtual environment** (isolates this project's Python packages
   from the rest of your machine):

   ```bash
   python -m venv .venv
   ```

2. **Activate it** — you'll need to do this in every new terminal session
   you use for this project:

   ```bash
   .venv\Scripts\activate            # Windows (cmd or PowerShell)
   # source .venv/bin/activate       # macOS/Linux
   ```

   Your terminal prompt should now be prefixed with `(.venv)`.

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   This installs everything the project needs — nothing else to install by
   hand:

   | Package | What it's for |
   |---|---|
   | `pandas` | reads the CSV in the ingestion script |
   | `sqlalchemy` | database connection/engine used by the ingestion script |
   | `psycopg2-binary` | PostgreSQL driver (what SQLAlchemy actually talks over) |
   | `python-dotenv` | loads `.env` automatically if you create one |
   | `dbt-core` | the dbt CLI/runtime |
   | `dbt-postgres` | dbt's Postgres adapter |

### Step 3 — Run the pipeline

```bash
python 4000_pipeline/run_pipeline.py
```

This single script starts Postgres via `docker compose up -d` if it isn't
already running, ingests the sample CSV, runs `dbt build`, and generates the
docs site. See [Running the pipeline](#running-the-pipeline) for what each
step does and the available flags.

### Step 4 — What success looks like

You should see a summary like this in the terminal:

```
=== Step 1/4: Ensure Postgres is running ===
Postgres is already reachable.

=== Step 2/4: Ingest CSV ===
1240 rows in CSV -> 1240 inserted, 0 updated (1240 total rows).

=== Step 3/4: dbt build (models + tests) ===
...
Done. PASS=24 WARN=1 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=25

=== Step 4/4: dbt docs generate ===
...
Pipeline finished successfully.
```

**`WARN=1` is expected**, not a failure — see
[Data quality checks](#data-quality-checks) for what it is and why it's a
warning rather than an error. `ERROR=0` is what actually matters.

### Step 5 — View the generated docs

```bash
cd 3000_dbt_project
dbt docs serve --profiles-dir .
```

Opens a browsable site with every model, column, source, and test
documented, plus the full lineage graph.

### Next steps

- Point the pipeline at your own Postgres, or a different port/user, via
  `.env` — see [Configuration](#configuration).
- Load a new day's data incrementally — see [Incremental loads](#incremental-loads).
- Run ingestion or dbt commands individually instead of through
  `run_pipeline.py` — see [Running the pipeline](#running-the-pipeline).

## Configuration

Connection settings are environment variables, read by both the ingestion
script and (via the generated dbt profile) dbt itself:

| Variable | Default | Matches docker-compose default? |
|---|---|---|
| `PG_HOST` | `localhost` | yes |
| `PG_PORT` | `5432` | yes |
| `PG_USER` | `postgres` | yes |
| `PG_PASSWORD` | `postgres` | yes |
| `PG_DB` | `onyx` | yes |

The defaults match `docker-compose.yml` exactly, so if you're using the
bundled container you don't need to configure anything. If you're pointing at
a different Postgres instance (a remote box, a different port, different
credentials), copy `.env.example` to `.env` and edit it — `run_pipeline.py`
loads `.env` automatically via `python-dotenv`.

```bash
cp .env.example .env    # macOS/Linux
copy .env.example .env  # Windows
```

`.env` is git-ignored, so real credentials never get committed.

## Project structure

Folders are numbered to show the pipeline's flow order end to end
(data → ingestion → dbt transform/test → orchestration), and the folders
inside the dbt project are numbered the same way (macros load first, then
models run in source → staging → marts order, then tests).

```
Onyx_egm_pipeline/
├── 1000_data/
│   └── Data Engineer Challenge_input.csv   # sample data
├── 2000_ingestion/
│   └── ingest_csv_to_postgres.py           # CSV -> Postgres loader
├── 3000_dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml.example                # template; pipeline generates the real one
│   ├── packages.yml                        # dbt_utils dependency
│   ├── 3100_macros/
│   │   └── safe_cast_to_date.sql           # SAFE_CAST equivalent (Postgres has none)
│   ├── 3200_models/
│   │   ├── 3210_source/
│   │   │   └── sources.yml                 # raw.egm_performance source + tests
│   │   ├── 3220_staging/
│   │   │   ├── stg_egm_performance.sql     # typed, incrementally-loaded staging model
│   │   │   └── staging.yml
│   │   └── 3230_marts/
│   │       ├── venue_turnover.sql          # total turnover per venue
│   │       ├── egm_revenue_by_venue.sql    # total revenue (gmp_sum) by EGM and venue
│   │       ├── daily_summary.sql           # daily turnover/revenue summary
│   │       └── marts.yml
│   └── 3300_tests/
│       └── generic/                        # custom reusable generic tests (see below)
├── 4000_pipeline/
│   └── run_pipeline.py                     # single entrypoint: runs everything
├── docker-compose.yml                      # local Postgres (stock postgres:15 image)
├── requirements.txt
└── .env.example
```

## Running the pipeline

```bash
python 4000_pipeline/run_pipeline.py
```

This single script:

1. **Ensures Postgres is running** — checks `localhost:5432` (or your `.env`
   settings), and if unreachable, runs `docker compose up -d` and waits for
   it to accept connections (see [Docker](#docker-what-it-runs-and-why)).
2. **Ingests** `1000_data/Data Engineer Challenge_input.csv` into
   `raw.egm_performance`.
3. **Writes a working `3000_dbt_project/profiles.yml`** from your `PG_*` env
   vars (copied from `profiles.yml.example`) — no manual
   `~/.dbt/profiles.yml` setup needed.
4. **Runs `dbt deps`** to install the `dbt_utils` package dependency.
5. **Runs `dbt build`** — every model and every test, in dependency order. A
   failing test is reported but doesn't abort the script (docs still get
   generated); the script exits non-zero at the end if anything failed.
6. **Runs `dbt docs generate`** to build the documentation site.

Useful flags:

```bash
python 4000_pipeline/run_pipeline.py --csv "1000_data/some_other_file.csv"
python 4000_pipeline/run_pipeline.py --no-docker   # if you're managing Postgres yourself
python 4000_pipeline/run_pipeline.py --skip-docs
```

View the generated docs:

```bash
cd 3000_dbt_project
dbt docs serve --profiles-dir .
```

To run ingestion or dbt on their own (e.g. while iterating on a model):

```bash
python 2000_ingestion/ingest_csv_to_postgres.py --csv "1000_data/Data Engineer Challenge_input.csv"

cd 3000_dbt_project
dbt deps            # installs dbt_utils, only needed once (or after upgrading packages.yml)
dbt build --profiles-dir .
```

Everything dbt builds lands in Postgres under the `onyx` database. With no
custom `generate_schema_name` macro, dbt's default naming applies: the
staging model lands in `analytics_staging` and the marts in `analytics_marts`
(the profile's base schema, `analytics`, combined with each model's
`+schema` config in `dbt_project.yml`).

## Data transformations

| Model | Grain | Purpose |
|---|---|---|
| `stg_egm_performance` | one row per bus_date/venue/EGM/fp | Casts raw text to real types (date, numeric, bigint); incrementally loaded |
| `venue_turnover` | one row per venue | Total turnover, games played, and active days per venue |
| `egm_revenue_by_venue` | one row per venue + EGM | Total revenue (`gmp_sum`), turnover, and games played per machine, per venue |
| `daily_summary` | one row per bus_date | Turnover, revenue, and games played across all venues, per day |

## Data quality checks

All tests are declared in yml against sources/models — there are no
standalone singular test `.sql` files in this project.

Built-in tests (`3210_source/sources.yml`, `3220_staging/staging.yml`, `3230_marts/marts.yml`):
- `not_null` on `bus_date`, `venue_code`, `egm_description`, `manufacturer`,
  `fp` — checked on the raw source *and* on the staging model, so a bad row
  is caught immediately after ingestion, before anything downstream reads it.
- `unique` on the mart grains (`venue_code` in `venue_turnover`, `bus_date`
  in `daily_summary`).

`dbt_utils` tests (`3220_staging/staging.yml`):
- `accepted_range` (`min_value: 0`) on `turnover_sum` and `games_played_sum`
  — fails if either is negative. (`gmp_sum`/revenue is deliberately **not**
  checked here — it's legitimately negative on days a venue pays out more
  than it collects.) Runs on the staging model, where these columns are
  already cast to `numeric`/`bigint` — `accepted_range` doesn't cast, and
  the raw source columns are text.
- `accepted_range` (`max_value: 1000000`, `severity: warn`) on
  `games_played_sum` — an outlier check. While testing this pipeline I found
  a real row in the sample data with `games_played_sum = 4,294,247,914` —
  physically impossible, and suspiciously close to 2^32, pointing at a
  source-system integer overflow rather than a real count. It also
  overflowed Postgres's standard 32-bit `integer` type outright, which is
  why the staging model casts `games_played_sum` to `bigint`. Rather than
  crash the pipeline or silently drop the row, this test flags it as a
  warning so it stays visible for follow-up without blocking the rest of
  the build.

Custom generic test (`3300_tests/generic/valid_date.sql`, backed by the
`safe_cast_to_date` Postgres function in `3100_macros/`):
- `valid_date` on raw `bus_date` (`3210_source/sources.yml`) — fails if the
  raw text value isn't a real calendar date (catches both malformed strings
  and impossible dates like `2025-02-30`). Runs against the raw text column
  *before* staging casts it to a date, so a malformed value is a clean test
  failure rather than a hard cast error mid-build. Postgres has no built-in
  `SAFE_CAST`/`TRY_CAST`, so `safe_cast_to_date` wraps a real `::date` cast
  in `plpgsql` exception handling to get the same effect.

`dbt build` will therefore usually finish with **1 warning** on the
provided sample data — that's expected, and is the outlier above.

## Incremental loads

Two layers work together:

- **Ingestion is an upsert**, not an append: re-running it with the same
  file is a no-op; a file containing only new or corrected rows inserts or
  updates just those rows, keyed on `(bus_date, venue_code, egm_description, fp)`.
- **The staging model is `materialized='incremental'`**, filtered on an
  `ingested_at` timestamp set at load time. On each `dbt build`, it only
  (re)processes rows ingested since the last run — so loading a new day's
  delta file reprocesses just that delta, not the full history. Marts
  rebuild as tables on top of it, which is cheap at this data volume; at
  larger volume they'd move to incremental too.

To simulate a daily incremental load: drop a new CSV containing just the new
day's rows into `1000_data/`, then run `python 4000_pipeline/run_pipeline.py
--csv "1000_data/new_day.csv"`.

## Design notes / assumptions

- **Raw layer stores everything as text.** The loader never casts anything;
  it hands dbt the CSV data byte-for-byte. This means a malformed value
  fails as a dbt test or a clear dbt compile error, not a silent pandas
  coercion — and it's why the "valid date format" and "positive values"
  checks in this project are meaningful rather than tautological.
- **`fp`** is treated as an opaque machine position/footprint identifier
  (not a floating-point value, despite the column name) and is only ever
  used as part of the natural key.
- **`dbt_utils` is a real dependency** (`3000_dbt_project/packages.yml`), so
  `dbt deps` must be run once before `dbt build`/`dbt test` will work.
  `4000_pipeline/run_pipeline.py` does this automatically; running `dbt`
  commands directly (see "Running the pipeline" above) needs a manual
  `dbt deps` first.
- **No Docker image is built for this project.** The only container involved
  runs the stock, official `postgres:15` image — see
  [Docker](#docker-what-it-runs-and-why). Everything else (Python, dbt) runs
  on the host, in the virtualenv.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker compose` not found, but `docker-compose` works | You have Compose v1, not v2. Update Docker Desktop, or install the `compose` CLI plugin. |
| `run_pipeline.py` hangs at "Ensure Postgres is running" then times out | Docker Desktop isn't running, or port 5432 is already in use by another Postgres install/container. Run `docker compose ps` / `docker compose logs` to check, or change the host port in `docker-compose.yml` and `PG_PORT` in `.env` together. |
| `dbt build` fails immediately with "package not found" (e.g. `dbt_utils`) | `dbt deps` hasn't been run. `run_pipeline.py` does this automatically; if running `dbt` directly, run `dbt deps` first. |
| Connection refused when running `dbt` commands directly | You need `--profiles-dir .` (from inside `3000_dbt_project/`) so dbt finds the generated `profiles.yml`, or set `DBT_PROFILES_DIR`. Note `profiles.yml` itself is only created by `run_pipeline.py` (or by manually copying `profiles.yml.example`) — it's git-ignored. |
| Re-running the pipeline seems to do nothing | That's expected if the CSV hasn't changed — ingestion upserts on the natural key, so an unchanged file is a no-op, and the incremental staging model only reprocesses newly ingested rows. |
| Want a totally clean slate | `docker compose down -v` (wipes the Postgres data volume), then re-run `python 4000_pipeline/run_pipeline.py`. |
