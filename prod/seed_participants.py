"""
prod/seed_participants.py

Upserts prod/data/manifest.csv into the 'participants' table. Run on the EC2
box (scripts/ec2-bootstrap.sh, every boot, after the api container reports
healthy) to close the gap where nothing ever writes the manifest into prod
Postgres: prod/generate_tokens.py runs on a dev machine, not the box, and the
S3 sync only lands the CSV on disk.

Does NOT generate tokens - the manifest is authoritative and already carries
them (minted once by prod/generate_tokens.py and handed to students).

Idempotent and safe to run against a live exam: an existing row's token,
name, group and intervention are updated from the CSV, but status,
active_session_id, started_at and last_seen_at are never touched. This
script re-runs on every boot, including the monthly cert-renewal boot and
any mid-exam reboot - resetting a live student's status back to "unused"
would break their session.

Usage (inside the api container, DB reachable via DATABASE_URL):
    python prod/seed_participants.py
"""
import asyncio
import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.future import select
from app.models.user import Participant
from app.utils.db import AsyncSessionLocal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "data", "manifest.csv")


async def run():
    if not os.path.exists(MANIFEST_PATH):
        print(f"ERROR: Manifest not found: {MANIFEST_PATH}")
        sys.exit(1)

    with open(MANIFEST_PATH, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: manifest.csv is empty.")
        sys.exit(1)

    required = {"token", "name", "identifier", "group", "intervention"}
    missing = required - set(rows[0].keys())
    if missing:
        print(f"ERROR: Missing columns in manifest.csv: {missing}")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        inserted = 0
        updated = 0

        for row in rows:
            token = row["token"].strip()
            name = row["name"].strip()
            identifier = row["identifier"].strip()
            group = row["group"].strip()
            intervention = row["intervention"].strip()

            result = await session.execute(select(Participant).filter_by(token=token))
            participant = result.scalars().first()

            if participant:
                participant.name = name
                participant.identifier = identifier
                participant.group = group
                participant.intervention = intervention
                updated += 1
            else:
                session.add(Participant(
                    token=token,
                    name=name,
                    identifier=identifier,
                    group=group,
                    intervention=intervention,
                    status="unused",
                ))
                inserted += 1

        await session.commit()

    print(f"Seeded participants: {inserted} inserted, {updated} updated (unchanged: status, active_session_id, started_at, last_seen_at).")


if __name__ == "__main__":
    asyncio.run(run())
