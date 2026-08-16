"""Ingest the EGM performance CSV into PostgreSQL.

Loads every column as text into raw.egm_performance, preserving source
fidelity exactly as it arrived — typing/casting and validation are dbt's job
(see 3000_dbt_project/3200_models/3220_staging/stg_egm_performance.sql). Rows
are upserted on the natural key (bus_date, venue_code, egm_description, fp),
so this script is safe to re-run: a CSV containing only new or corrected rows
is enough to do an incremental load, and re-running the same file is a no-op.

Usage:
  python 2000_ingestion/ingest_csv_to_postgres.py --csv "1000_data/Data Engineer Challenge_input.csv"

Connection is controlled via environment variables (see .env.example):
  PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB
"""
import argparse
import os
import sys

import pandas as pd
from sqlalchemy import create_engine, text

REQUIRED_COLUMNS = [
    "bus_date",
    "venue_code",
    "egm_description",
    "manufacturer",
    "fp",
    "turnover_sum",
    "gmp_sum",
    "games_played_sum",
]

NATURAL_KEY = ["bus_date", "venue_code", "egm_description", "fp"]


def get_engine():
    # Build the Postgres connection string from env vars, falling back to
    # local-dev defaults if they aren't set.
    host = os.environ.get("PG_HOST", "localhost")
    port = os.environ.get("PG_PORT", "5432")
    user = os.environ.get("PG_USER", "postgres")
    password = os.environ.get("PG_PASSWORD", "postgres")
    db = os.environ.get("PG_DB", "onyx")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)  # SQLAlchemy engine, not an open connection yet


def load_dataframe(csv_path):
    # dtype=str: every column comes in as text, matching the raw table below.
    # Casting to real numeric/date types is dbt's responsibility.
    df = pd.read_csv(csv_path, dtype=str)
    df.columns = [c.strip() for c in df.columns]  # tolerate stray whitespace in header names

    # Fail fast if the CSV doesn't have the columns we expect, rather than
    # letting a malformed file silently load partial/garbage data.
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    return df[REQUIRED_COLUMNS]  # drop any extra columns the CSV might carry


def ingest(csv_path, engine=None, schema_name="raw"):
    df = load_dataframe(csv_path)
    engine = engine or get_engine()

    # Everything below runs in one transaction: engine.begin() commits at the
    # end of the `with` block, or rolls back entirely if anything raises.
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name};"))

        # Create the raw table on first run; no-op on subsequent runs.
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.egm_performance (
          bus_date TEXT,
          venue_code TEXT,
          egm_description TEXT,
          manufacturer TEXT,
          fp TEXT,
          turnover_sum TEXT,
          gmp_sum TEXT,
          games_played_sum TEXT,
          ingested_at TIMESTAMP NOT NULL DEFAULT now(),
          PRIMARY KEY (bus_date, venue_code, egm_description, fp)
        );
        """))

        # Row count before the upsert, so we can report how many rows were
        # newly inserted vs. updated after the fact.
        before = conn.execute(
            text(f"SELECT count(*) FROM {schema_name}.egm_performance")
        ).scalar()

        # Dump the whole CSV into a throwaway staging table first. This lets
        # us upsert with a single SQL statement instead of looping row by row.
        staging_table = "egm_performance_staging"
        df.to_sql(staging_table, conn, schema=schema_name, if_exists="replace", index=False)

        # Upsert staging -> raw on the natural key: new keys get inserted,
        # existing keys get their values (and ingested_at) refreshed.
        conn.execute(text(f"""
        INSERT INTO {schema_name}.egm_performance (
          bus_date, venue_code, egm_description, manufacturer, fp,
          turnover_sum, gmp_sum, games_played_sum, ingested_at
        )
        SELECT
          bus_date, venue_code, egm_description, manufacturer, fp,
          turnover_sum, gmp_sum, games_played_sum, now()
        FROM {schema_name}.{staging_table}
        ON CONFLICT (bus_date, venue_code, egm_description, fp) DO UPDATE
          SET manufacturer      = EXCLUDED.manufacturer,
              turnover_sum      = EXCLUDED.turnover_sum,
              gmp_sum           = EXCLUDED.gmp_sum,
              games_played_sum  = EXCLUDED.games_played_sum,
              ingested_at       = EXCLUDED.ingested_at;
        """))

        # Staging table has served its purpose; clean it up.
        conn.execute(text(f"DROP TABLE IF EXISTS {schema_name}.{staging_table};"))

        after = conn.execute(
            text(f"SELECT count(*) FROM {schema_name}.egm_performance")
        ).scalar()

    # Rows in the CSV that didn't create a new row must have updated an
    # existing one (or been an exact no-op re-run).
    inserted = after - before
    updated = len(df) - inserted
    return {"csv_rows": len(df), "inserted": inserted, "updated": updated, "total_in_table": after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default="1000_data/Data Engineer Challenge_input.csv",
        help="Path to the source CSV file",
    )
    parser.add_argument("--schema", default="raw", help="Target Postgres schema")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"CSV file not found: {args.csv}")
        sys.exit(1)

    stats = ingest(args.csv, schema_name=args.schema)
    print(
        f"Ingestion complete: {stats['csv_rows']} rows in CSV -> "
        f"{stats['inserted']} inserted, {stats['updated']} updated "
        f"({stats['total_in_table']} total rows in {args.schema}.egm_performance)."
    )


if __name__ == "__main__":
    main()
