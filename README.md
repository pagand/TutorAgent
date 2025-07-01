# AI Tutor Proof of Concept (POC)

This project is a proof-of-concept AI-powered tutoring system designed to provide proactive, diagnostic, and personalized learning assistance. It uses a Retrieval-Augmented Generation (RAG) agent, Bayesian Knowledge Tracking (BKT), and a configurable intervention system to deliver timely and relevant help to students.

## Current Project Status

**The project has successfully completed Stage 4.5.** The core backend is fully functional, including the RAG pipeline, BKT student modeling, and a complete, adaptive personalization and feedback loop.

* **✅ Implemented Features:**
    * FastAPI backend with endpoints for questions, hints, answers, user state, and preferences.
    * PDF ingestion pipeline into a ChromaDB vector store.
    * RAG agent with a dynamic prompt engine for personalized hint generation.
    * Support for multiple LLM backends (Ollama, OpenAI, Google Gemini).
    * Bayesian Knowledge Tracker (BKT) to model student mastery per skill.
    * Intervention Controller that flags the need for proactive hints.
    * **Hybrid Feedback Loop:** A `/feedback` endpoint that records both explicit user ratings and implicit performance changes (BKT state) to adapt to the user.
    * **Adaptive Hint Selection:** An epsilon-greedy algorithm that balances exploiting the best-known hint style with exploring new ones.
    * Comprehensive integration test suite using `pytest`.

* **Next Immediate Goal:**
    * **Implement Stage 5: Data Persistence & Expanded User Model.** This involves migrating the in-memory state to a persistent SQLite database, enriching the user model with a full interaction history, and adding support for multiple question types.

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
    ```bash
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
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