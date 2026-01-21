import re
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

from prepare_data import convert_evaluation_questions, SOURCE_QUESTIONS_PATH
from app.utils.config import settings # Import settings to access API key
import google.generativeai as genai
import PyPDF2

# --- Constants ---
BASE_URL = "http://127.0.0.1:8000"
PERSONAS_CONFIG_PATH = "evaluation/configs/personas.yaml"
EXPERIMENTS_CONFIG_PATH = "evaluation/configs/experiments.yaml"
QUESTIONS_PATH = SOURCE_QUESTIONS_PATH
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

# --- Knowledge Base Helper ---
def _update_knowledge_base(student, question: pd.Series, is_correct: bool, correct_answer_index: str, hint_text: str | None):
    """
    Formats and adds a memory of an interaction to the student's knowledge base.
    A memory is only added if the student received a hint OR answered correctly.
    """
    if not hint_text and not is_correct:
        return  # Do not learn anything if the attempt was wrong and no hint was given

    # Initialize the "learned" section if it's the first memory
    if len(student.knowledge_base) < 2 and student.knowledge_base:
        # This assumes knowledge_base[0] is the PDF text if it exists
        student.knowledge_base.append("\n\n--- Things Learned So Far ---")
    elif not student.knowledge_base:
        student.knowledge_base.append("\n\n--- Things Learned So Far ---")


    question_text = question['question_text']
    
    memory_parts = [f'- Question: "{question_text}"']

    if hint_text:
        memory_parts.append(f'Hint Received: "{hint_text}"')

    if is_correct:
        correct_answer_text = ""
        if question['question_type'] == 'multiple_choice' and correct_answer_index and correct_answer_index.isdigit():
            try:
                options_list = str(question['options']).split('|')
                answer_index = int(correct_answer_index) - 1
                if 0 <= answer_index < len(options_list):
                    correct_answer_text = options_list[answer_index]
            except (ValueError, IndexError):
                correct_answer_text = correct_answer_index  # Fallback
        else:
            correct_answer_text = correct_answer_index  # For FITB
        
        if correct_answer_text:
            memory_parts.append(f'Correct Answer: "{correct_answer_text}"')

    memory = " | ".join(memory_parts)
    student.knowledge_base.append(memory)
    print(f"[{student.user_id}] Added to knowledge base: {memory}")


# --- Simulated Student Class ---
class SimulatedStudent:
    """Represents an LLM-based agent simulating a student."""
    def __init__(self, persona_config: dict):
        self.user_id = f"sim_{persona_config['name'].lower().replace(' ', '_')}_{int(time.time())}"
        self.persona = persona_config
        self.hint_style_experience = {}
        
        knowledge_source = self.persona.get('initial_knowledge_prompt', '')
        print(f"Found knowledge source for persona '{self.persona['name']}': {knowledge_source}")
        
        # Knowledge base is now a list to keep hints separate and clean
        self.knowledge_base = [] 
        
        if knowledge_source.startswith('[PDF_TEXT_PERCENT:'):
            try:
                percentage = int(knowledge_source.split(':')[1].strip(']'))
                initial_knowledge = get_text_from_pdf(EVALUATION_PDF_PATH, percentage)
                if initial_knowledge:
                    self.knowledge_base.append(initial_knowledge)
            except (ValueError, IndexError):
                pass # Knowledge base remains empty
        
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set in the environment.")
        genai.configure(api_key=settings.google_api_key)
        self.llm_client = genai.GenerativeModel(settings.google_model_name)
        
        print(f"Initialized student: {self.user_id} with persona '{self.persona['name']}'")
        # Report initial knowledge based on the first element if it exists
        initial_word_count = len(self.knowledge_base[0].split()) if self.knowledge_base else 0
        print(f"Knowledge base seeded with {initial_word_count} words.")

    def _get_system_prompt(self) -> str:
        # Impartial Evaluator Prompt
        return """
You are an impartial Knowledge Base Evaluator.
Your task is to analyze the provided [KNOWLEDGE BASE] and determine if it contains the answer to the [QUESTION].

**INSTRUCTIONS:**
1. **Analyze:** Search the [KNOWLEDGE BASE] (including "Things Learned So Far" and "IMMEDIATE HINT") for the answer.
2. **Evaluate Confidence:** Assign a score (0-100) representing how supported the answer is by the text.
    - 100: The exact answer is explicitly stated.
    - 75: The answer is strongly implied or requires a minor logical step.
    - 50: Partial information is present, or multiple options are plausible.
    - 25: Very little relevant information; mostly guessing.
    - 0: No relevant information found.
3. **List Plausible Options:**
    - If **Multiple Choice**: List the indices (e.g., ["1", "3"]) of all options that are NOT contradicted by the text. Eliminate clearly wrong ones.
    - If **Fill-in-the-Blank**: List the most likely phrase(s) found in the text. If unknown, return [""].
4. **Format:** Output ONLY a JSON object.

**JSON FORMAT:**
{
  "score": <int 0-100>,
  "options": ["<option1>", "<option2>", ...]
}
"""

    def answer_question(self, question: pd.Series, hint: str | None = None, previous_answer: str | None = None) -> tuple[str, str, str, list]:
        options_text = ""
        if question['question_type'] == 'multiple_choice':
            options_list = str(question['options']).split('|')
            options_text = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options_list))
            options_text = f"\n**Multiple Choice Options:**\n{options_text}"

        # --- Build Knowledge Context ---
        knowledge_base_text = "\n".join(self.knowledge_base)
        
        prompt = f"""
{self._get_system_prompt()}

[KNOWLEDGE BASE]
{knowledge_base_text}

[IMMEDIATE HINT]
{hint if hint else "None"}

[QUESTION]
{question['question_text']}
{options_text}

Provide your evaluation in JSON format:
"""
        print(f"[{self.user_id}] Evaluating question: {question['question_text']}")
        try:
            response = self.llm_client.generate_content(prompt)
            raw_response = response.text.strip()
            
            # Clean up potential markdown formatting (```json ... ```)
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            confidence = data.get("score", 0)
            plausible = data.get("options", [])
            
            print(f"   -> Score: {confidence}, Options: {plausible}")
            
            # --- Systematic Decision Logic ---
            # guess_probability acts as Risk Tolerance (0.0 = Coward, 1.0 = Daredevil)
            # Threshold = (1 - Risk Tolerance) * 100
            
            risk_tolerance = self.persona.get('guess_probability', 0.5)
            confidence_threshold = (1.0 - risk_tolerance) * 100
            
            final_answer = "I don't know"
            
            # Check if sufficient confidence AND plausible options exist
            if confidence >= confidence_threshold and plausible and plausible != [""]:
                # Pick randomly from the plausible set
                final_answer = random.choice(plausible)
            
            # Return raw_response (JSON) for debug log, but final_answer (String) for CSV/Logic
            return prompt, raw_response, str(final_answer), plausible

        except Exception as e:
            print(f"[{self.user_id}] ERROR in answer generation: {e}")
            return prompt, "Error", "I don't know", []

    def learn_from_hint(self, hint_text: str):
        # This method is now a placeholder; learning is handled by _update_knowledge_base
        print(f"[{self.user_id}] Received hint: {hint_text}")
        pass

    def decide_to_request_hint(self) -> bool:
        return random.random() < self.persona.get('hint_request_probability', 1.0)

    def rate_hint(self, is_correct: bool, is_skipped: bool) -> int:
        """Deterministic rating logic: 5=Correct, 3=Skip, 1=Wrong."""
        if is_skipped:
            return 3
        if is_correct:
            return 5
        return 1

    def update_hint_experience(self, hint_style: str, was_successful: bool):
        self.hint_style_experience[hint_style] = was_successful

    def get_simulated_think_time(self) -> int:
        """Generates a random think time based on persona."""
        min_ms = self.persona.get('min_think_time_ms', 3000)
        max_ms = self.persona.get('max_think_time_ms', 10000)
        return random.randint(min_ms, max_ms)

def _proxy_backend_validation_for_simulation(question: pd.Series, user_answer: str) -> bool:
    """
    PROXY FUNCTION: Duplicates the backend's validation logic (app.services.question_service.check_answer).
    """
    correct_answer_clean = question['correct_answer'].strip().lower()
    user_answer_clean = user_answer.strip().lower()
    
    if question['question_type'] == 'multiple_choice':
        return user_answer_clean == correct_answer_clean
    
    # Token-based inclusion (Option C)
    stop_words = {"a", "an", "the", "of", "and", "in", "on", "at", "to", "is", "are", "was", "were"}
    correct_tokens = [t for t in correct_answer_clean.split() if t not in stop_words]
    
    if not correct_tokens:
        correct_tokens = [t for t in correct_answer_clean.split() if t]

    if not correct_tokens:
        return user_answer_clean == correct_answer_clean
        
    for token in correct_tokens:
        if token not in user_answer_clean:
            return False
    return True

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

# --- New Logging and Simulation Logic ---
def _generate_run_id(experiment: dict, persona: dict) -> str:
    """Creates a unique, descriptive ID for a single simulation run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{experiment['name'].replace(' ', '_')}_{persona['name'].replace(' ', '_')}_{timestamp}"

def _log_csv_event(
    results_log: list, interaction_id: str, question: pd.Series,
    attempt_number: str, event_type: str, simulated_duration_ms: int,
    common_log_data: dict, event_specific_data: dict
):
    """A centralized function to append a new event row to the results list for the CSV."""
    log_entry = {
        "interaction_id": interaction_id,
        "question_number": int(question['question_number']),
        "skill_id": question['skill_id'],
        "difficulty": question['difficulty'],
        "attempt_number": attempt_number,
        "event_type": event_type,
        "simulated_duration_ms": simulated_duration_ms,
        **common_log_data,
        **event_specific_data
    }
    results_log.append(log_entry)


def _run_question_attempt(
    question: pd.Series, student: 'SimulatedStudent', runner: 'EvaluationRunner',
    attempt_type: str, cumulative_attempt_num: int, results_log: list, detailed_log_dir: str,
    run_id: str, experiment_name: str, persona_name: str
) -> tuple[bool, bool]:
    """
    Runs a SINGLE attempt for a question. 
    Returns: (is_correct, is_skipped)
    """
    interaction_id = datetime.now().strftime("%H:%M:%S.%f")
    attempt_str = f"revisit_{cumulative_attempt_num}" if attempt_type == 'revisit' else str(cumulative_attempt_num)
    
    print(f"--- Question {int(question['question_number'])} Attempt {attempt_str} (ID: {interaction_id}) ---")

    json_log_path = os.path.join(detailed_log_dir, f"{interaction_id.replace(':', '_').replace('.', '_')}.json")
    json_log_for_attempt = {
        "interaction_id": interaction_id, "run_id": run_id, "user_id": student.user_id,
        "experiment_name": experiment_name, "persona_name": persona_name,
        "question_number": int(question['question_number']), "attempt_number": attempt_str,
        "pre_attempt_knowledge_base": "\n".join(student.knowledge_base),
        "events": []
    }

    simulated_duration_ms = student.get_simulated_think_time()
    proactive_offered = False
    hint_data = None
    hint_trigger = "NONE"
    final_hint_text = None

    # 1. Proactive Intervention Check
    if cumulative_attempt_num == 1:
        payload = { "user_id": student.user_id, "question_number": int(question['question_number']), "time_spent_ms": simulated_duration_ms }
        response = runner.session.post(f"{BASE_URL}/intervention-check", json=payload)
        proactive_offered = response.json().get('intervention_needed', False)
        print(f"[{student.user_id}] Proactive check (waited {simulated_duration_ms}ms): {proactive_offered}")
        if proactive_offered and random.random() < student.persona.get('accept_proactive_hint_probability', 1.0):
            hint_trigger = "PROACTIVE_ACCEPTED"
        elif proactive_offered:
            hint_trigger = "PROACTIVE_IGNORED"

    # 2. Manual Hint Request Logic
    if hint_trigger == "NONE" and student.decide_to_request_hint() and "No Hints" not in experiment_name:
        hint_timing = student.persona.get("hint_request_timing")
        if cumulative_attempt_num == 1 and hint_timing == "before_answer":
            hint_trigger = "MANUAL_BEFORE_ANSWER"
        elif cumulative_attempt_num > 1:
            hint_trigger = "MANUAL_AFTER_FEEDBACK"

    # 3. Fetch Hint
    if hint_trigger in ["PROACTIVE_ACCEPTED", "MANUAL_BEFORE_ANSWER", "MANUAL_AFTER_FEEDBACK"]:
        print(f"[{student.user_id}] Requesting hint (Trigger: {hint_trigger}).")
        payload = {"user_id": student.user_id, "question_number": int(question['question_number']), "user_answer": "Not provided"}
        response = runner.session.post(f"{BASE_URL}/hints", json=payload)
        if response.status_code == 200:
            hint_data = response.json()
            final_hint_text = hint_data.get('hint')
            student.learn_from_hint(final_hint_text)
            _log_csv_event(
                results_log, interaction_id, question, attempt_str, "HINT", simulated_duration_ms,
                common_log_data={"proactive_offered": proactive_offered},
                event_specific_data={ "mastery_after_event": hint_data.get("pre_hint_mastery"), "hint_trigger": hint_trigger, "hint_style_used": hint_data.get("hint_style"), "feedback_rating": None, "answer_submitted": None, "plausible_options": None, "is_correct": None }
            )
            json_log_for_attempt['events'].append({'type': 'HINT', 'details': { "trigger": hint_trigger, **hint_data }})
            simulated_duration_ms = student.get_simulated_think_time()
        else:
            print(f"CRITICAL ERROR: Hint request failed with status {response.status_code}: {response.text}")
            json_log_for_attempt['events'].append({'type': 'HINT_FAILED', 'details': { "trigger": hint_trigger, "status_code": response.status_code, "error": response.text }})

    # 4. Generate Answer (unpack 4 values now)
    prompt, raw_json_response, parsed_answer, plausible_options = student.answer_question(question, hint=final_hint_text, previous_answer=None)
    
    print(f"[{student.user_id}] Student's Parsed Answer: \"{parsed_answer}\" ")
    answer_event_details = { "llm_prompt": prompt, "llm_raw_response": raw_json_response, "parsed_answer": parsed_answer }

    # 5. Handle Skip/Answer and Feedback
    # Fix: stricter check for "error" to avoid flagging "quantization error" as a skip
    is_skip = "i don't know" in parsed_answer.lower() or parsed_answer.strip().lower().startswith("error")
    
    if not is_skip:
        local_correct = _proxy_backend_validation_for_simulation(question, parsed_answer)
        rating = student.rate_hint(is_correct=local_correct, is_skipped=False) if hint_data else None
    else:
        local_correct = False
        rating = student.rate_hint(is_correct=False, is_skipped=True) if hint_data else None

    payload = {"user_id": student.user_id, "question_number": int(question['question_number'])}
    if is_skip:
        payload["skipped"] = True
        event_type = "SKIP"
    else:
        payload["user_answer"] = parsed_answer
        event_type = "ANSWER"
        
    if hint_data:
        payload.update({
            "hint_shown": True, 
            "hint_style_used": hint_data.get("hint_style"), 
            "hint_text": final_hint_text, 
            "pre_hint_mastery": hint_data.get("pre_hint_mastery"), 
            "feedback_rating": rating 
        })

    # 6. Submit to Server
    response = runner.session.post(f"{BASE_URL}/answer", json=payload)
    tutor_feedback = response.json()
    is_correct = tutor_feedback.get('correct', False)

    if hint_data:
        student.update_hint_experience(hint_data.get("hint_style"), is_correct)

    _log_csv_event(
        results_log, interaction_id, question, attempt_str, event_type, simulated_duration_ms,
        common_log_data={"proactive_offered": proactive_offered},
        event_specific_data={ "answer_submitted": parsed_answer, "plausible_options": str(plausible_options), "is_correct": is_correct, "mastery_after_event": tutor_feedback.get('current_mastery'), "hint_trigger": hint_trigger, "hint_style_used": hint_data.get("hint_style") if hint_data else None, "feedback_rating": rating }
    )
    answer_event_details['tutor_feedback'] = tutor_feedback
    json_log_for_attempt['events'].append({'type': event_type, 'details': answer_event_details})
    with open(json_log_path, 'w') as f: json.dump(json_log_for_attempt, f, indent=2)

    _update_knowledge_base(student, question, is_correct, tutor_feedback.get('correct_answer'), final_hint_text)
    
    return is_correct, is_skip


def run_single_simulation(experiment: dict, persona: dict, questions: pd.DataFrame):
    """Orchestrates a single simulation run for one experiment-persona combination."""
    print("\n" + "="*50)
    print(f"Starting simulation: Experiment '{experiment['name']}' with Persona '{persona['name']}'")
    print("="*50)

    student = SimulatedStudent(persona)
    runner = EvaluationRunner()
    run_id = _generate_run_id(experiment, persona)
    detailed_log_dir = os.path.join(RESULTS_DIR, run_id)
    os.makedirs(detailed_log_dir, exist_ok=True)

    runner.create_user(student.user_id)
    runner.set_preferences(student.user_id, experiment['tutor_config'])

    results_log = []
    unresolved_questions = list(questions.to_dict('records'))
    max_tries = experiment.get('max_tries', 2)
    
    question_attempts_tracker = {int(q['question_number']): 0 for q in unresolved_questions}
    
    # --- Round 1 ---
    print(f"\n--- Round 1: Initial Attempts ---")
    questions_for_revisit = []
    
    for question_dict in unresolved_questions:
        question = pd.Series(question_dict)
        q_num = int(question['question_number'])
        
        question_attempts_tracker[q_num] += 1
        is_correct, is_skip = _run_question_attempt(
            question, student, runner, "initial", question_attempts_tracker[q_num],
            results_log, detailed_log_dir, run_id, experiment['name'], persona['name']
        )
        
        if is_correct: continue
        if is_skip:
            if question_attempts_tracker[q_num] < max_tries:
                questions_for_revisit.append(question_dict)
            continue
            
        # Immediate Retry for Failure
        if not is_correct and not is_skip and question_attempts_tracker[q_num] < max_tries:
             question_attempts_tracker[q_num] += 1
             _run_question_attempt(
                question, student, runner, "immediate_retry", question_attempts_tracker[q_num],
                results_log, detailed_log_dir, run_id, experiment['name'], persona['name']
            )

    # --- Round 2 ---
    if questions_for_revisit:
        print(f"\n--- Round 2: Revisiting {len(questions_for_revisit)} Skipped Questions ---")
        for question_dict in questions_for_revisit:
            question = pd.Series(question_dict)
            q_num = int(question['question_number'])
            
            question_attempts_tracker[q_num] += 1
            is_correct, is_skip = _run_question_attempt(
                question, student, runner, "revisit", question_attempts_tracker[q_num],
                results_log, detailed_log_dir, run_id, experiment['name'], persona['name']
            )
            
            if not is_correct and not is_skip and question_attempts_tracker[q_num] < max_tries:
                 question_attempts_tracker[q_num] += 1
                 _run_question_attempt(
                    question, student, runner, "revisit_retry", question_attempts_tracker[q_num],
                    results_log, detailed_log_dir, run_id, experiment['name'], persona['name']
                )

    # --- Metrics ---
    results_df = pd.DataFrame(results_log)
    
    final_status_map = {}
    for q_num, group in results_df.groupby('question_number'):
        last_event = group.sort_values('interaction_id').iloc[-1]
        if last_event['event_type'] == 'ANSWER' and last_event['is_correct']:
            final_status_map[q_num] = 'CORRECT'
        elif last_event['event_type'] == 'SKIP':
            final_status_map[q_num] = 'SKIPPED'
        else: 
            final_status_map[q_num] = 'INCORRECT'
    results_df['final_status'] = results_df['question_number'].map(final_status_map)

    cum_actual_attempts = 0
    cum_opportunities = 0
    cum_correct = 0
    unique_correct_q = set()
    unique_seen_q = set()
    
    engagement_list = []
    accuracy_list = []
    grade_list = []

    # Re-verify results_df order? It should be appended sequentially.
    for _, row in results_df.iterrows():
        event_type = row['event_type']
        q_num = int(row['question_number'])
        
        unique_seen_q.add(q_num)
        
        if event_type == 'ANSWER':
            cum_opportunities += 1
            cum_actual_attempts += 1
            if row['is_correct']:
                cum_correct += 1
                unique_correct_q.add(q_num)
        elif event_type == 'SKIP':
            cum_opportunities += 1
            
        engagement = cum_actual_attempts / cum_opportunities if cum_opportunities > 0 else 0
        accuracy = cum_correct / cum_actual_attempts if cum_actual_attempts > 0 else 0
        grade = len(unique_correct_q) / len(unique_seen_q) if unique_seen_q else 0
        
        engagement_list.append(engagement)
        accuracy_list.append(accuracy)
        grade_list.append(grade)

    results_df['metric_engagement'] = engagement_list
    results_df['metric_accuracy'] = accuracy_list
    results_df['metric_grade'] = grade_list

    main_csv_path = os.path.join(RESULTS_DIR, f"{run_id}.csv")
    results_df.to_csv(main_csv_path, index=False)

    total_questions = len(questions)
    final_correct = len(unique_correct_q) # Use the set length, which is safe.
    final_grade_percent = (final_correct / total_questions) * 100 if total_questions > 0 else 0

    print("\n" + "="*50)
    print(f"Simulation finished. Main results saved to {main_csv_path}")
    print(f"Detailed logs saved in directory: {detailed_log_dir}")
    print(f"\n--- FINAL METRICS ---")
    print(f"Correct (Unique): {final_correct}/{total_questions} ({final_grade_percent:.1f}%)")
    print(f"Total Correct Events: {cum_correct}")
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
