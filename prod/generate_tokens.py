"""
prod/generate_tokens.py

Reads prod/data/participants.csv (name, identifier, group, intervention),
generates a unique 8-char token per participant, writes prod/data/manifest.csv,
and upserts all rows into the 'participants' DB table.

Usage (from project root, with .venv active and DB running):
    python prod/generate_tokens.py

The manifest CSV is handout-only — never ship it to the frontend.
prod/data/ is gitignored.
"""
import asyncio
import csv
import os
import secrets
import sys

# Add project root to path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.future import select
from app.models.user import Participant
from app.utils.db import AsyncSessionLocal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(SCRIPT_DIR, "data", "participants.csv")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "data", "manifest.csv")

# Unambiguous alphabet — no O/0/I/1/L confusion
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TOKEN_LENGTH = 8
VALID_GROUPS = {"free_choice", "adaptive"}
VALID_INTERVENTIONS = {"proactive", "manual"}


def generate_token() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LENGTH))


async def run():
    if not os.path.exists(INPUT_PATH):
        print(f"ERROR: Input file not found: {INPUT_PATH}")
        sys.exit(1)

    with open(INPUT_PATH, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: participants.csv is empty.")
        sys.exit(1)

    # Validate columns
    required = {"name", "identifier", "group", "intervention"}
    missing = required - set(rows[0].keys())
    if missing:
        print(f"ERROR: Missing columns in participants.csv: {missing}")
        sys.exit(1)

    # Validate values
    for i, row in enumerate(rows, start=2):
        if row["group"] not in VALID_GROUPS:
            print(f"ERROR row {i}: group='{row['group']}' must be one of {VALID_GROUPS}")
            sys.exit(1)
        if row["intervention"] not in VALID_INTERVENTIONS:
            print(f"ERROR row {i}: intervention='{row['intervention']}' must be one of {VALID_INTERVENTIONS}")
            sys.exit(1)

    async with AsyncSessionLocal() as session:
        # Collect existing tokens so we never collide
        existing = await session.execute(select(Participant.token))
        used_tokens = set(existing.scalars().all())

        manifest_rows = []
        upserted = 0

        for row in rows:
            identifier = row["identifier"].strip()
            name = row["name"].strip()
            group = row["group"].strip()
            intervention = row["intervention"].strip()

            # Check for an existing participant by identifier (idempotent re-runs)
            result = await session.execute(
                select(Participant).filter_by(identifier=identifier)
            )
            participant = result.scalars().first()

            if participant:
                token = participant.token
                # Update group/intervention in case they changed in the CSV
                participant.group = group
                participant.intervention = intervention
                participant.name = name
            else:
                # Generate a unique token
                token = generate_token()
                while token in used_tokens:
                    token = generate_token()
                used_tokens.add(token)

                participant = Participant(
                    token=token,
                    name=name,
                    identifier=identifier,
                    group=group,
                    intervention=intervention,
                    status="unused",
                )
                session.add(participant)

            upserted += 1
            manifest_rows.append({
                "token": token,
                "name": name,
                "identifier": identifier,
                "group": group,
                "intervention": intervention,
            })

        await session.commit()

    # Write manifest CSV
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["token", "name", "identifier", "group", "intervention"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Generated/updated {upserted} participant(s).")
    print(f"Manifest written to: {OUTPUT_PATH}")
    print()
    print("Tokens (for distribution):")
    for r in manifest_rows:
        print(f"  {r['token']}  {r['name']} ({r['identifier']})  [{r['group']}/{r['intervention']}]")


if __name__ == "__main__":
    asyncio.run(run())
