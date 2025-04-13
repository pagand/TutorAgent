# app/services/question_service.py
import csv
from typing import List, Dict, Optional, Set
from app.models.question import Question
from app.utils.logger import logger

CSV_FILE_PATH = "data/questions.csv"

class QuestionService:
    def __init__(self, csv_path: str = CSV_FILE_PATH):
        self.questions: List[Question] = []
        self.questions_by_id: Dict[int, Question] = {}
        self.skills: Set[str] = set()
        self.load_questions(csv_path)

    def load_questions(self, csv_path: str):
        try:
            self.questions = []
            self.questions_by_id = {}
            self.skills = set()
            with open(csv_path, mode="r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        question = Question(
                            question_number=int(row["id"]),
                            question=row["question"],
                            answer1=row["answer_1"],
                            answer2=row["answer_2"],
                            answer3=row["answer_3"],
                            answer4=row["answer_4"],
                            # Handle potential variations in correct answer format (e.g., '1' vs 'Answer 1')
                            # Assuming correct_answer column stores the *index* (1-4)
                            correct_answer=row["correct_answer"].strip(),
                            skill=row["skill"].strip()
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
             # Optionally raise an error to prevent startup without questions
             # raise FileNotFoundError(f"Question CSV file not found: {csv_path}")
        except Exception as e:
            logger.exception(f"Error loading questions from {csv_path}: {e}")


    def get_all_questions(self) -> List[Question]:
        return self.questions

    def get_question_by_id(self, question_id: int) -> Optional[Question]:
        return self.questions_by_id.get(question_id)

    def get_all_skills(self) -> List[str]:
        return list(self.skills)

    def check_answer(self, question_id: int, user_answer: str) -> Optional[bool]:
        """Checks if the user's answer is correct for the given question ID."""
        question = self.get_question_by_id(question_id)
        if not question:
            return None # Question not found

        # Assuming correct_answer is the index (1-4) and user_answer is the index (1-4)
        # Add more robust checking if user_answer format can vary
        return str(user_answer).strip() == str(question.correct_answer).strip()

# Instantiate the service globally or manage via dependency injection
question_service = QuestionService()