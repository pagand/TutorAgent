"""
frontend/e2e/fixtures/answer_key.py

Test-only oracle for the E2E suite: prints the correct_answer for a given
question_number by reading the same CSV question_service loads from at
runtime. Never goes over HTTP/the app's API — GET /questions/ and POST
/answer/ deliberately never expose this field (Stage 1a), so tests that need
to submit a genuinely correct answer must get it from this side channel
instead, not from the network.

Usage:
    python frontend/e2e/fixtures/answer_key.py <question_number>
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from app.services.question_service import question_service
from app.utils.config import settings


def run(question_number: int):
    question_service.load_questions(settings.QUESTION_CSV_FILE_PATH)
    question = question_service.get_question_by_id(question_number)
    if question is None:
        print(f"ERROR: no question numbered {question_number}", file=sys.stderr)
        sys.exit(1)
    print(question.correct_answer)


if __name__ == "__main__":
    run(int(sys.argv[1]))
