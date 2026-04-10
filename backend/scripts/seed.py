"""
Seed script — creates test users, listings, and one active auction for dev.

Usage:
    python -m scripts.seed          (from /backend)
    make seed                       (from /backend)

Delegates to app.db.seed which defines all seed data.
"""

import asyncio
import sys

from app.db.seed import seed


def main() -> None:
    try:
        asyncio.run(seed())
    except KeyboardInterrupt:
        print("\nSeed interrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nSeed failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
