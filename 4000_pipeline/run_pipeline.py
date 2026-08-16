"""Single entrypoint that runs the whole EGM pipeline end to end:

  1. Make sure Postgres is up (starts it via `docker compose up -d` if needed).
  2. Ingest the CSV into raw.egm_performance (idempotent upsert - see
     2000_ingestion/ingest_csv_to_postgres.py).
  3. Generate a working dbt profile from the same PG_* env vars (no manual
     ~/.dbt/profiles.yml setup required).
  4. `dbt build`: runs every model (staging -> marts) and every test in
     dependency order.
  5. `dbt docs generate`: builds the documentation site.

Usage:
  python 4000_pipeline/run_pipeline.py
  python 4000_pipeline/run_pipeline.py --csv "1000_data/Data Engineer Challenge_input.csv"
  python 4000_pipeline/run_pipeline.py --no-docker   # skip auto-starting Postgres

Re-running this script with an updated/appended CSV is how incremental loads
work: ingestion upserts on the natural key, and the dbt staging model only
(re)processes rows whose ingested_at is newer than what it already built.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "2000_ingestion"))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DBT_PROJECT_DIR = os.path.join(REPO_ROOT, "3000_dbt_project")


def load_dotenv_if_present():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    except ImportError:
        pass


def run_cmd(cmd, cwd=None, env=None, fatal=True):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"Command exited with code {result.returncode}: {' '.join(cmd)}")
        if fatal:
            sys.exit(result.returncode)
    return result.returncode


def wait_for_postgres(timeout=30):
    from sqlalchemy import create_engine
    from ingest_csv_to_postgres import get_engine

    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            engine = get_engine()
            with engine.connect():
                return True
        except Exception as exc:  # noqa: BLE001 - just retrying until timeout
            last_error = exc
            time.sleep(1)
    print(f"Postgres did not become reachable within {timeout}s: {last_error}")
    return False


def ensure_postgres_running(no_docker):
    from ingest_csv_to_postgres import get_engine

    try:
        with get_engine().connect():
            print("Postgres is already reachable.")
            return
    except Exception:  # noqa: BLE001
        pass

    if no_docker:
        print("Postgres is not reachable and --no-docker was set; aborting.")
        sys.exit(1)

    if shutil.which("docker") is None:
        print("Postgres is not reachable and Docker is not installed; aborting.")
        sys.exit(1)

    print("Postgres is not reachable, starting it with `docker compose up -d`...")
    run_cmd(["docker", "compose", "up", "-d"], cwd=REPO_ROOT)

    if not wait_for_postgres():
        sys.exit(1)
    print("Postgres is up.")


def write_dbt_profile():
    example = os.path.join(DBT_PROJECT_DIR, "profiles.yml.example")
    target = os.path.join(DBT_PROJECT_DIR, "profiles.yml")
    shutil.copyfile(example, target)
    return DBT_PROJECT_DIR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default=os.path.join("1000_data", "Data Engineer Challenge_input.csv"),
        help="Path to the source CSV file",
    )
    parser.add_argument(
        "--no-docker", action="store_true",
        help="Don't attempt to auto-start Postgres via docker compose",
    )
    parser.add_argument(
        "--skip-docs", action="store_true", help="Skip the `dbt docs generate` step",
    )
    args = parser.parse_args()

    load_dotenv_if_present()

    from ingest_csv_to_postgres import ingest

    print("=== Step 1/4: Ensure Postgres is running ===")
    ensure_postgres_running(args.no_docker)

    print("\n=== Step 2/4: Ingest CSV ===")
    csv_path = os.path.join(REPO_ROOT, args.csv) if not os.path.isabs(args.csv) else args.csv
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        sys.exit(1)
    stats = ingest(csv_path)
    print(
        f"{stats['csv_rows']} rows in CSV -> {stats['inserted']} inserted, "
        f"{stats['updated']} updated ({stats['total_in_table']} total rows)."
    )

    print("\n=== Step 3/4: dbt build (models + tests) ===")
    profiles_dir = write_dbt_profile()
    dbt_env = os.environ.copy()
    dbt_env["DBT_PROFILES_DIR"] = profiles_dir
    # Make sure `dbt` resolves to this venv's copy even if the venv was never
    # activated (e.g. this script was invoked as `.venv/Scripts/python.exe 4000_pipeline/run_pipeline.py`).
    dbt_env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + dbt_env.get("PATH", "")
    dbt_exe = shutil.which("dbt", path=dbt_env["PATH"]) or "dbt"

    # Installs packages.yml dependencies (dbt_utils); fatal, since dbt build
    # would just fail on every model/test otherwise.
    run_cmd([dbt_exe, "deps"], cwd=DBT_PROJECT_DIR, env=dbt_env)

    # Not fatal: a failing data-quality test should be reported, not hide the
    # docs step or the final summary. Models still build/run in DAG order;
    # `dbt build` only skips work that actually depends on a failed node.
    build_rc = run_cmd([dbt_exe, "build"], cwd=DBT_PROJECT_DIR, env=dbt_env, fatal=False)

    if not args.skip_docs:
        print("\n=== Step 4/4: dbt docs generate ===")
        run_cmd([dbt_exe, "docs", "generate"], cwd=DBT_PROJECT_DIR, env=dbt_env)
        print(
            "\nDocs generated. View them with:\n"
            f'  dbt docs serve --profiles-dir "{profiles_dir}"  (run from {DBT_PROJECT_DIR})'
        )

    if build_rc != 0:
        print("\nPipeline finished with one or more dbt build/test failures - see log above.")
        sys.exit(build_rc)

    print("\nPipeline finished successfully.")


if __name__ == "__main__":
    main()
