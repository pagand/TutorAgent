# app/services/question_service.py
import csv
from typing import List, Dict, Optional, Set
import json
from app.models.question import Question
from app.utils.logger import logger
from app.utils.config import settings

class QuestionService:
    def __init__(self):
        self.questions: List[Question] = []
        self.questions_by_id: Dict[int, Question] = {}
        self.skills: Set[str] = set()
        # self.load_questions(csv_path)
        logger.info("QuestionService initialized (data loading deferred).")

    def load_questions(self, csv_path: Optional[str] = None):
        """Loads questions from the specified CSV path."""
        csv_path = csv_path if csv_path is not None else settings.QUESTION_CSV_FILE_PATH
        try:
            self.questions = []
            self.questions_by_id = {}
            self.skills = set()
            with open(csv_path, mode="r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        question_type = row.get("question_type", "multiple_choice").strip()
                        options = None
                        if question_type == "multiple_choice":
                            # Safely parse options, expecting a JSON-like string '["opt1", "opt2"]'
                            try:
                                options_raw = row.get("options")
                                if options_raw:
                                    options = json.loads(options_raw)
                            except (json.JSONDecodeError, TypeError):
                                logger.error(f"Skipping row due to invalid JSON in 'options': {row}")
                                continue

                        question = Question(
                            question_number=int(row["id"]),
                            question=row["question"].strip(),
                            question_type=question_type,
                            options=options,
                            correct_answer=row["correct_answer"].strip().strip('"'),
                            skill=row["skill"].strip().strip('"')
                        )
                        self.questions.append(question)
                        self.questions_by_id[question.question_number] = question
                        self.skills.add(question.skill)
                    except ValueError as ve:
                        logger.error(f"Skipping row due to ValueError: {row} - Error: {ve}")
                    except KeyError as ke:
                        logger.error(f"Skipping row due to missing key: {row} - Missing Key: {ke}")

            logger.info(f"Loaded {len(self.questions)} questions.")
            logger.info(f"Found {len(self.skills)} unique skills: {self.skills}")
            if not self.questions:
                logger.warning(f"No questions loaded from {csv_path}. Check the file format and content.")

        except FileNotFoundError:
            logger.error(f"Question CSV file not found at: {csv_path}")
        except Exception as e:
            logger.exception(f"Error loading questions from {csv_path}: {e}")


    def get_all_questions(self) -> List[Question]:
        return self.questions

    def get_question_by_id(self, question_id: int) -> Optional[Question]:
        return self.questions_by_id.get(question_id)

    def get_all_skills(self) -> List[str]:
        return list(self.skills)

    def check_answer(self, question_id: int, user_answer: str) -> Optional[bool]:
        """Checks if the user's answer is correct based on the question type."""
        question = self.get_question_by_id(question_id)
        if not question:
            return None

        user_answer_stripped = str(user_answer).strip()
        correct_answer_stripped = str(question.correct_answer).strip()

        if question.question_type == "fill_in_the_blank":
            return user_answer_stripped.lower() == correct_answer_stripped.lower()
        # Default to multiple_choice or any other type with a direct string match
        return user_answer_stripped == correct_answer_stripped

# Instantiate the service globally or manage via dependency injection
question_service = QuestionService()