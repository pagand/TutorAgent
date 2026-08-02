# AI Tutor Proof of Concept (POC)

This project is a proof-of-concept AI-powered tutoring system designed to provide proactive, diagnostic, and personalized learning assistance. It uses a Retrieval-Augmented Generation (RAG) agent, Bayesian Knowledge Tracking (BKT), and a configurable intervention system to deliver timely and relevant help to students.

## Current Project Status

**The project has successfully completed Stage 7 (Formal Evaluation).** The core backend is fully functional, and the initial round of evaluation using the LLM-as-a-Student framework has yielded critical insights into the system's pedagogical effectiveness.

* **✅ Implemented Features:**
    * FastAPI backend with endpoints for questions, hints, answers, user profiles, and preferences.
    * **PostgreSQL Database:** Persistent storage for all user data, including mastery, preferences, and interaction history.
    * PDF ingestion pipeline into a ChromaDB vector store.
    * RAG agent with a dynamic prompt engine that uses user history for context-aware hint generation.
    * Support for multiple LLM backends (Ollama, OpenAI, Google Gemini).
    * Bayesian Knowledge Tracker (BKT) to model student mastery per skill.
    * Intervention Controller that flags the need for proactive hints.
    * **Unified Hybrid Feedback Loop:** The `/answer` endpoint records both explicit user ratings and implicit performance changes (BKT state) to adapt to the user.
    * **Adaptive Hint Selection:** An epsilon-greedy algorithm that balances exploiting the best-known hint style with exploring new ones.
    * **Multiple Question Types:** Support for `multiple_choice` and `fill_in_the_blank` questions.
    * Comprehensive, automated integration test suite using `pytest` and a custom validation script.
    * **LLM-as-a-Student Evaluation Framework:** A complete, configurable framework for offline evaluation of the tutor's effectiveness.

* **Next Immediate Goal:**
    * **Tune System Based on Evaluation Findings.** The immediate priority is to adjust system parameters based on the results of the formal evaluation. This includes lowering the `intervention_mastery_threshold` to make proactive hints less aggressive and improving hint prompts to be more Socratic. The secondary goal is to implement the full user interface (Stage 6).

## Project Setup

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd AITUTORAPP
    ```

2.  **Create Virtual Environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment:**
    * Copy the example environment file: `cp .env.example .env`
    * Edit the `.env` file to configure your desired `LLM_PROVIDER` (`ollama`, `openai`, `google`) and add the corresponding API keys if necessary.

5.  **Run the Application:**
update log from .env file. 
Back end:
    ```bash
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    ```
front end:
```bash
npm run dev
```

admin dashboard:
```bash
streamlit run streamlit_app/app.py
```


## Running Tests

The project uses `pytest` for high-level integration testing.

1.  **Run All Mocked Tests:**
    ```bash
    pytest
    ```

2.  **Run Stage-Specific Tests:**
    ```bash
    pytest -m stage5
    ```
For more details on the testing strategy, see `TESTING_STRATEGY.md`.


if changing the database:
```bash
alembic revision --autogenerate -m "the revision message"
alembic upgrade head 
```

## Docker Deployment

`prod/data/` (exam questions, answer key, participant tokens, source PDF) is intentionally excluded from git.
Copy it onto the target host out-of-band before the first build.

```bash
git clone <repository_url> AITutorApp && cd AITutorApp
scp -r /path/to/prod/data ec2-user@<host>:~/AITutorApp/prod/data   # or equivalent for your host
cp .env.docker.example .env        # fill in POSTGRES_PASSWORD, GOOGLE_API_KEY, ALLOWED_ORIGIN
docker compose up -d --build       # first build ~10-15 min
docker compose logs -f api         # watch alembic migrate + uvicorn startup
curl http://localhost/             # should return {"message":"Welcome to the AI Tutor API"}
```

## Backup and Restore

`scripts/backup.sh` dumps Postgres to a timestamped `pg_dump -Fc` file, prunes dumps past the retention window, and optionally uploads to S3. `scripts/restore.sh` restores a dump into an explicit target (no default target, so it can't silently overwrite production). `scripts/restore_drill.sh` proves a backup is actually restorable: it restores into a scratch database, compares every table's row count against the source, and reports any mismatch — a backup that has never been restored is not a backup.

**Local dev** (`DATABASE_URL` from `.env`, already exported by `.venv`):
```bash
./scripts/backup.sh                                    # writes ./backups/aitutor_<timestamp>.dump
./scripts/restore_drill.sh                              # restores the newest dump into a scratch DB, drops it after
./scripts/restore.sh ./backups/aitutor_<ts>.dump postgresql+asyncpg://user@localhost:5432/some_target_db
```

**EC2 / Docker Compose** — Postgres's `5432` is intentionally not exposed to the host, so these scripts run `pg_dump`/`pg_restore` inside the `db` service instead:
```bash
DOCKER_DB_SERVICE=db POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db ./scripts/backup.sh
DOCKER_DB_SERVICE=db POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db ./scripts/restore.sh ./backups/aitutor_<ts>.dump
```

Cron, run nightly and before/after each exam (`crontab -e` on the EC2 host, with the vars above exported or set inline):
```
0 2 * * * cd ~/AITutorApp && DOCKER_DB_SERVICE=db POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db BACKUP_S3_URI=s3://<bucket>/aitutor-backups ./scripts/backup.sh >> ~/AITutorApp/backups/cron.log 2>&1
```

`BACKUP_S3_URI` is optional — set it once the Stage 4 Terraform creates the bucket; until then dumps stay local under `BACKUP_DIR` (default `./backups`).