import re
import uuid
import json
from datetime import datetime
import os
import sys
import random
import yaml
import pandas as pd
import requests
import time

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from prepare_data import convert_evaluation_questions
from app.utils.config import settings # Import settings to access API key
import google.generativeai as genai
import PyPDF2

# --- Constants ---
BASE_URL = "http://127.0.0.1:8000"
PERSONAS_CONFIG_PATH = "evaluation/configs/personas.yaml"
EXPERIMENTS_CONFIG_PATH = "evaluation/configs/experiments.yaml"
QUESTIONS_PATH = "evaluation/data/evaluation_questions.csv" # Use the human-readable source
EVALUATION_PDF_PATH = "evaluation/data/evaluation_source.pdf"
RESULTS_DIR = "evaluation/results"

# --- PDF Helper ---
PDF_CACHE = {}

def get_text_from_pdf(path: str, percentage: int) -> str:
    """Extracts a percentage of the text from a PDF, using a cache."""
    if path in PDF_CACHE:
        full_text = PDF_CACHE[path]
    else:
        if not os.path.exists(path):
            print(f"CRITICAL ERROR: PDF file not found at '{path}'")
            return ""
        try:
            with open(path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text_content = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        cleaned_text = re.sub(r'\s+', ' ', page_text.replace('\n', ' '))
                        text_content += cleaned_text
                PDF_CACHE[path] = text_content
                full_text = text_content
        except Exception as e:
            print(f"CRITICAL ERROR reading PDF: {e}")
            return ""

    if not full_text:
        print(f"WARNING: Could not extract any text from '{path}'.")
        return ""
    
    slice_index = int(len(full_text) * (percentage / 100))
    print(f"Extracted {len(full_text)} chars, returning first {percentage}% ({slice_index} chars).")
    return full_text[:slice_index]

# --- Robust Parsing Helper ---
def parse_llm_answer(persona_name: str, raw_answer: str) -> str:
    """Strips persona-specific artifacts from the LLM's raw response using regex."""
    if "Expert" in persona_name:
        match = re.search(r'^(.*?)Verification:', raw_answer, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return raw_answer.strip()

# --- Simulated Student Class ---
class SimulatedStudent:
    """Represents an LLM-based agent simulating a student."""
    def __init__(self, persona_config: dict):
        self.user_id = f"sim_{persona_config['name'].lower().replace(' ', '_')}_{int(time.time())}"
        self.persona = persona_config
        self.hint_style_experience = {}
        
        knowledge_source = self.persona.get('initial_knowledge_prompt', '')
        print(f"Found knowledge source for persona '{self.persona['name']}': {knowledge_source}")
        if knowledge_source.startswith('[PDF_TEXT_PERCENT:'):
            try:
                percentage = int(knowledge_source.split(':')[1].strip(']'))
                self.knowledge_base = get_text_from_pdf(EVALUATION_PDF_PATH, percentage)
            except (ValueError, IndexError):
                self.knowledge_base = ""
        elif knowledge_source == "[USE_OWN_KNOWLEDGE]":
            self.knowledge_base = "[USE_OWN_KNOWLEDGE]"
        else:
            self.knowledge_base = ""
        
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set in the environment.")
        genai.configure(api_key=settings.google_api_key)
        self.llm_client = genai.GenerativeModel(settings.google_model_name)
        
        print(f"Initialized student: {self.user_id} with persona '{self.persona['name']}'")
        print(f"Knowledge base seeded with {len(self.knowledge_base.split())} words.")

    def _get_system_prompt(self) -> str:
        # ... (rest of the class is correct)
        persona_name = self.persona['name']
        guess_prob = self.persona.get('guess_probability', 0.5)
        
        base_instruction = f"""
You are role-playing as a student.
- If you are unsure of an answer, you have two choices: either make a logical guess based on your limited KNOWLEDGE BASE, or respond with the exact phrase "I don't know.".
- You are {guess_prob*100:.0f}% likely to guess and {100-guess_prob*100:.0f}% likely to say "I don't know.".
- CRITICAL: If you are given a `TUTOR HINT`, you MUST use it to re-evaluate your previous answer and provide a new, improved response. Do not simply repeat your old answer.
"""
        if "Struggling" in persona_name or "Anxious" in persona_name:
            return f"{base_instruction}\n- You are finding the material difficult and may make mistakes."
        elif "Confident" in persona_name:
            return f"{base_instruction}\n- You are a confident student and should answer decisively. Avoid saying 'I don't know' unless absolutely necessary."
        elif "Expert" in persona_name:
            return """
You are role-playing as an expert in this field.
- First, answer the question using your own extensive knowledge.
- After providing your answer, you MUST then consult the provided KNOWLEDGE BASE.
- Add a short, second paragraph to your response starting with "Verification:". In this paragraph, state whether the knowledge base confirms your answer, contradicts it, or provides insufficient information.
"""
        return base_instruction

    def answer_question(self, question: pd.Series, hint: str | None = None, previous_answer: str | None = None) -> str:
        options_text = ""
        if question['question_type'] == 'multiple_choice':
            options_list = str(question['options']).split('|')
            options_text = "\n".join(f"- {opt}" for opt in options_list)
            options_text = f"\n**Multiple Choice Options:**\n{options_text}"

        hint_text = f"**TUTOR HINT:**\n{hint}\n" if hint else ""
        previous_answer_text = f"Your previous answer was '{previous_answer}', which was INCORRECT. You MUST provide a different answer based on the TUTOR HINT.\n" if previous_answer else ""

        knowledge_text = f"**KNOWLEDGE BASE (for verification only):**\n---\n{get_text_from_pdf(EVALUATION_PDF_PATH, 100)}\n---" if self.persona['name'] == "Expert Student" else f"**KNOWLEDGE BASE:**\n---\n{self.knowledge_base}\n---"

        prompt = f"""
{self._get_system_prompt()}
{knowledge_text}
{previous_answer_text}
**QUESTION:**
{question['question_text']}
{options_text}
{hint_text}
**INSTRUCTIONS FOR YOUR ANSWER:**
- If the question is multiple-choice, respond with only the full text of the single best option.
- If the question is fill-in-the-blank, respond with only the word or short phrase that fills the blank.
- Follow all instructions in your role-playing persona.

Your Answer:
"""
        print(f"[{self.user_id}] Generating answer for question: {question['question_text']}")
        try:
            response = self.llm_client.generate_content(prompt)
            return response.text.strip() if response.parts else "Error: Blocked by API"
        except Exception as e:
            print(f"[{self.user_id}] ERROR calling LLM API: {e}")
            return "Error: LLM API call failed."

    def learn_from_hint(self, hint_text: str):
        print(f"[{self.user_id}] Learning from hint: {hint_text}")
        self.knowledge_base += f"\n\nTutor Hint: {hint_text}"

    def decide_to_request_hint(self) -> bool:
        return random.random() < self.persona.get('hint_request_probability', 1.0)

    def rate_hint(self, hint_style: str) -> int | None:
        if random.random() >= self.persona.get('give_feedback_probability', 1.0):
            return None
        if hint_style not in self.hint_style_experience:
            return 3 
        was_successful_last_time = self.hint_style_experience[hint_style]
        return 5 if was_successful_last_time else 1

    def update_hint_experience(self, hint_style: str, was_successful: bool):
        self.hint_style_experience[hint_style] = was_successful

# --- API Client Class ---
class EvaluationRunner:
    def __init__(self):
        self.session = requests.Session()

    def create_user(self, user_id: str):
        response = self.session.post(f"{BASE_URL}/users", json={"user_id": user_id})
        response.raise_for_status()
        print(f"[{user_id}] User created successfully.")

    def set_preferences(self, user_id: str, tutor_config: dict):
        response = self.session.put(f"{BASE_URL}/users/{user_id}/preferences", json=tutor_config)
        response.raise_for_status()
        print(f"[{user_id}] Preferences set to: {tutor_config}")

# --- Main Simulation Logic ---
def run_single_simulation(experiment: dict, persona: dict, questions: pd.DataFrame):
    print("\n" + "="*50)
    print(f"Starting simulation: Experiment '{experiment['name']}' with Persona '{persona['name']}'")
    print("="*50)

    student = SimulatedStudent(persona)
    runner = EvaluationRunner()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_filename_base = f"{experiment['name'].replace(' ', '_')}_{persona['name'].replace(' ', '_')}_{timestamp}"
    detailed_log_dir = os.path.join(RESULTS_DIR, results_filename_base)
    os.makedirs(detailed_log_dir, exist_ok=True)

    runner.create_user(student.user_id)
    runner.set_preferences(student.user_id, experiment['tutor_config'])

    results = []
    skipped_questions = []
    max_tries = experiment.get('max_tries', 1)

    print(f"\n--- Starting Initial Question Loop (Max Tries per Question: {max_tries}) ---")
    for _, question in questions.iterrows():
        is_correct = False
        last_answer = None
        
        for i in range(max_tries):
            attempt_num = i + 1
            interaction_id = str(uuid.uuid4())
            
            log_entry = {
                "timestamp": datetime.now().isoformat(), "interaction_id": interaction_id,
                "experiment_name": experiment['name'], "persona_name": persona['name'],
                "user_id": student.user_id, "question_number": int(question['question_number']),
                "skill_id": question['skill_id'], "difficulty": question['difficulty'], 
                "attempt": attempt_num, "skipped": False,
                "simulated_time_spent_ms": None, "proactive_check_result": None,
                "initial_answer": None, "post_hint_answer": None,
                "initial_correctness": None, "initial_mastery": None,
                "feedback_rating": None, "post_hint_correctness": None, "post_hint_mastery": None,
                "revisit_correctness": None, "revisit_mastery": None,
                "hint_style_used": None
            }

            detailed_log = { "interaction_id": interaction_id, "pre_answer_knowledge_base": student.knowledge_base }
            print(f"--- Question {log_entry['question_number']} Attempt {attempt_num} ({log_entry['skill_id']}) ---")

            hint_data = None
            if attempt_num == 1:
                wait_time = student.persona.get('proactive_wait_seconds', 0)
                if wait_time > 0:
                    log_entry['simulated_time_spent_ms'] = wait_time * 1000
                    time.sleep(1)
                    payload = { "user_id": student.user_id, "question_number": int(question['question_number']), "time_spent_ms": wait_time * 1000 }
                    response = runner.session.post(f"{BASE_URL}/intervention-check", json=payload)
                    intervention_needed = response.json().get('intervention_needed', False)
                    log_entry["proactive_check_result"] = intervention_needed
                    print(f"[{student.user_id}] Proactive intervention check result: {intervention_needed}")

                    if intervention_needed:
                        acceptance_prob = float(student.persona.get('accept_proactive_hint_probability', 1.0))
                        if random.random() < acceptance_prob:
                            print(f"[{student.user_id}] Accepting proactive hint.")
                            hint_payload = {"user_id": student.user_id, "question_number": int(question['question_number']), "user_answer": "Not provided"}
                            hint_response = runner.session.post(f"{BASE_URL}/hints", json=hint_payload)
                            if hint_response.status_code == 200:
                                hint_data = hint_response.json()
                                student.learn_from_hint(hint_data['hint'])
                        else:
                            print(f"[{student.user_id}] Ignoring proactive hint.")

            if hint_data is None:
                hint_timing = student.persona.get("hint_request_timing")
                should_request_hint = student.decide_to_request_hint() and "No Hints" not in experiment['name']

                if (attempt_num == 1 and hint_timing == "before_answer" and should_request_hint):
                    print(f"[{student.user_id}] Requesting hint before answering.")
                    payload = {"user_id": student.user_id, "question_number": int(question['question_number']), "user_answer": "Not provided"}
                    response = runner.session.post(f"{BASE_URL}/hints", json=payload)
                    if response.status_code == 200:
                        hint_data = response.json()
                        student.learn_from_hint(hint_data['hint'])
                elif (attempt_num > 1 and hint_timing == "after_feedback" and should_request_hint):
                    print(f"[{student.user_id}] Requesting hint after incorrect answer.")
                    payload = {"user_id": student.user_id, "question_number": int(question['question_number']), "user_answer": last_answer}
                    response = runner.session.post(f"{BASE_URL}/hints", json=payload)
                    if response.status_code == 200:
                        hint_data = response.json()
                        student.learn_from_hint(hint_data['hint'])

            raw_answer = student.answer_question(question, hint=hint_data['hint'] if hint_data else None, previous_answer=last_answer)
            answer = parse_llm_answer(student.persona['name'], raw_answer)
            print(f"[{student.user_id}] Student's Answer: \"{answer}\"")
            
            if attempt_num == 1:
                log_entry["initial_answer"] = raw_answer
            else:
                log_entry["post_hint_answer"] = raw_answer

            last_answer = answer

            if "i don't know" in answer.lower() or "error:" in answer.lower():
                log_entry["skipped"] = True
                if question['question_number'] not in [q['question_number'] for q in skipped_questions]:
                    skipped_questions.append(question)
                results.append(log_entry)
                continue 

            payload = {
                "user_id": student.user_id, 
                "question_number": int(question['question_number']), 
                "user_answer": answer 
            }

            if hint_data:
                detailed_log.update({
                    "hint_text": hint_data.get("hint"),
                    "hint_style_used": hint_data.get("hint_style"),
                    "retrieved_context": hint_data.get("context"),
                    "final_prompt": hint_data.get("final_prompt")
                })
                hint_style = hint_data.get("hint_style")
                log_entry["hint_style_used"] = hint_style
                rating = student.rate_hint(hint_style)
                log_entry["feedback_rating"] = rating
                
                if rating is not None:
                    payload["feedback_rating"] = rating
                payload["hint_shown"] = True
                payload["hint_style_used"] = hint_style
                payload["hint_text"] = hint_data.get("hint")
                payload["pre_hint_mastery"] = hint_data.get("pre_hint_mastery")

            response = runner.session.post(f"{BASE_URL}/answer", json=payload)
            tutor_feedback = response.json()
            is_correct = tutor_feedback['correct']

            if hint_data:
                student.update_hint_experience(hint_data.get("hint_style"), is_correct)
            
            if hint_data or attempt_num > 1:
                log_entry.update({ "post_hint_correctness": is_correct, "post_hint_mastery": tutor_feedback['current_mastery'] })
            else:
                log_entry.update({ "initial_correctness": is_correct, "initial_mastery": tutor_feedback['current_mastery'] })

            print(f"[{student.user_id}] Tutor feedback: {tutor_feedback}")
            
            results.append(log_entry)
            with open(os.path.join(detailed_log_dir, f"{interaction_id}.json"), 'w') as f: json.dump(detailed_log, f, indent=2)
            
            if is_correct:
                skipped_questions = [q for q in skipped_questions if q['question_number'] != question['question_number']]
                break
        
    revisit_attempts = 0
    max_revisits = 2 
    while skipped_questions and revisit_attempts < max_revisits:
        revisit_attempts += 1
        print(f"\n--- Revisiting {len(skipped_questions)} Skipped Questions (Pass {revisit_attempts}) ---")
        
        questions_to_retry = skipped_questions[:]
        skipped_questions.clear()

        for question in questions_to_retry:
            interaction_id = str(uuid.uuid4())
            print(f"--- Re-attempting Question {question['question_number']} ---")
            
            log_entry = {
                "timestamp": datetime.now().isoformat(), "interaction_id": interaction_id,
                "experiment_name": experiment['name'], "persona_name": persona['name'],
                "user_id": student.user_id, "question_number": int(question['question_number']),
                "skill_id": question['skill_id'], "difficulty": question['difficulty'], 
                "attempt": max_tries + revisit_attempts, "skipped": False,
                "initial_answer": "I don't know",
                "revisit_correctness": None, "revisit_mastery": None,
            }

            raw_answer = student.answer_question(question, hint=None, previous_answer="I don't know")
            answer = parse_llm_answer(student.persona['name'], raw_answer)
            print(f"[{student.user_id}] Student's Answer: \"{answer}\"")

            log_entry["post_hint_answer"] = raw_answer

            if "i don't know" in answer.lower() or "error:" in answer.lower():
                log_entry["skipped"] = True
                skipped_questions.append(question)
                print(f"[{student.user_id}] Still doesn't know.")
            else:
                payload = { "user_id": student.user_id, "question_number": int(question['question_number']), "user_answer": answer }
                response = runner.session.post(f"{BASE_URL}/answer", json=payload)
                tutor_feedback = response.json()
                is_correct = tutor_feedback['correct']
                log_entry.update({ "revisit_correctness": is_correct, "revisit_mastery": tutor_feedback['current_mastery'] })
                print(f"[{student.user_id}] Revisit Tutor feedback: {tutor_feedback}")

            results.append(log_entry)

    results_df = pd.DataFrame(results)
    main_csv_path = os.path.join(RESULTS_DIR, f"{results_filename_base}.csv")
    results_df.to_csv(main_csv_path, index=False)

    print("\n" + "="*50)
    print(f"Simulation finished. Main results saved to {main_csv_path}")
    print(f"Detailed logs saved in directory: {detailed_log_dir}")
    print("="*50)

# --- Configuration Loading ---
def load_config(path: str) -> dict:
    """Loads a YAML configuration file."""
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def main():
    """Main function to run the evaluation."""
    print("--- Step 1: Preparing Data ---")
    if not convert_evaluation_questions():
        print("Data preparation failed. Aborting evaluation.")
        return
    
    print("\n--- Step 2: Loading Configurations ---")
    personas = load_config(PERSONAS_CONFIG_PATH)
    experiments = load_config(EXPERIMENTS_CONFIG_PATH)
    questions = pd.read_csv(QUESTIONS_PATH)

    print(f"Loaded {len(personas)} personas and {len(experiments)} experiments.")
    print(f"Loaded {len(questions)} questions.")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    for experiment in experiments:
        for persona in personas:
            run_single_simulation(experiment, persona, questions)

if __name__ == "__main__":
    main()