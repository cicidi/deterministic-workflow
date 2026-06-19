"""Entry point for mfangdai agent."""
import sys

from src.db import init_db, get_session, seed_loan_officers
from src.mcp_server import run_cli


def main():
    db_url = "sqlite:///mfangdai_test.db"
    init_db(db_url)

    session = get_session()
    try:
        seed_loan_officers(session)
        print(f"Database ready: {db_url}")
        print(f"Loan officers seeded: 5")
    finally:
        session.close()

    run_cli()


if __name__ == "__main__":
    main()
