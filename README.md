# AI Tutor Proof of Concept (POC)

This project is a proof-of-concept AI-powered tutoring system designed to provide proactive, diagnostic, and personalized learning assistance. It uses a Retrieval-Augmented Generation (RAG) agent, Bayesian Knowledge Tracking (BKT), and a configurable intervention system to deliver timely and relevant help to students.

## Current Project Status

**The project has successfully completed Stage 4.** The core backend is fully functional, including the RAG pipeline, BKT student modeling, and now a complete personalization and feedback loop.

* **✅ Implemented Features:**
    * FastAPI backend with endpoints for questions, hints, answers, user state, and preferences.
    * PDF ingestion pipeline into a ChromaDB vector store.
    * RAG agent for hint generation with multi-LLM support (Ollama, OpenAI, Google Gemini).
    * **Personalized Hint Generation:** The RAG agent now generates hints in different styles ("Analogy", "Worked Example", etc.) based on user preferences.
    * Bayesian Knowledge Tracker (BKT) to model student mastery per skill.
    * Intervention Controller that flags the need for proactive hints.
    * **Feedback Loop:** A `/feedback` endpoint now records user ratings on hint effectiveness, updating a user's profile.
    * Comprehensive integration test suite using `pytest`.
    * Robust and stable mocking strategy for reliable and fast testing.

* **Next Immediate Goal:**
    * **Implement Stage 5: Evaluation, UI & Production-Readiness.** This involves building a Streamlit UI, creating a formal evaluation framework to measure pedagogical effectiveness, and migrating the in-memory state to a persistent database.

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
    * The application requires data to be ingested into the vector store on first run.
    ```bash
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    ```
    * Check the console logs to ensure PDF ingestion and RAG component initialization complete successfully.

## Running Tests

The project uses `pytest` for high-level integration testing.

1.  **Run All Mocked Tests:** This is the default and recommended way to test. It does **not** make real LLM API calls.
    ```bash
    pytest
    ```

2.  **Run Stage-Specific Tests:** Use pytest markers to run tests related to a specific development stage.
    ```bash
    pytest -m stage4
    ```

3.  **Run Real LLM Integration Test:** To run the single test that verifies connectivity with your configured live LLM, ensure your `.env` is set up correctly and use the `llm_integration` marker.
    ```bash
    pytest -m llm_integration -s
    ```

For more details on the testing strategy, including manual API testing snippets, see `TESTING_STRATEGY.md`.
