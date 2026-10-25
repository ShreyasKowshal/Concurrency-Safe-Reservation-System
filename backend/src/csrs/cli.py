"""Explicit administrator commands; no passwords or session secrets on command lines."""

import argparse

from sqlalchemy.orm import Session

from csrs.auth.admin import promote_organizer, purge_sessions
from csrs.config import Settings
from csrs.database import create_database_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="CSRS local administration")
    parser.add_argument("--env-file", help="Optional explicit environment file")
    commands = parser.add_subparsers(dest="command", required=True)
    promote = commands.add_parser("promote-organizer", help="Promote an existing active attendee")
    promote.add_argument("email")
    purge = commands.add_parser(
        "purge-sessions", help="Delete one bounded batch of expired/revoked sessions"
    )
    purge.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    engine = create_database_engine(Settings(_env_file=args.env_file))
    try:
        with Session(engine, expire_on_commit=False) as db:
            try:
                if args.command == "promote-organizer":
                    user = promote_organizer(db, args.email)
                    print(f"User {user.id} is now ORGANIZER; existing sessions revoked.")
                else:
                    print(
                        f"Removed {purge_sessions(db, args.batch_size)} expired/revoked sessions."
                    )
            except ValueError as error:
                parser.error(str(error))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
