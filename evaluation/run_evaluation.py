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
import hashlib

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from prepare_data import convert_evaluation_questions, SOURCE_QUESTIONS_PATH
from app.utils.config import settings # Import settings to access API key
import google.generativeai as genai
import PyPDF2
random.seed(42)

# --- Constants ---
BASE_URL = "http://127.0.0.1:8000"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_CONFIG_PATH = os.path.join(SCRIPT_DIR, "configs", "personas.yaml")
EXPERIMENTS_CONFIG_PATH = os.path.join(SCRIPT_DIR, "configs", "experiments.yaml")
QUESTIONS_PATH = SOURCE_QUESTIONS_PATH
EVALUATION_PDF_PATH = os.path.join(SCRIPT_DIR, "data", "evaluation_source.pdf")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
LLM_CACHE_PATH = os.path.join(SCRIPT_DIR, "data", "llm_cache.json")
CACHE_SCOPE_EXP_NAME = False # Set to True to scope cache by experiment name and prompt

# --- LLM Caching Mechanism ---
class LLMCache:
    """Persistent disk cache for LLM responses to reduce costs and latency."""
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"WARNING: Could not load LLM cache: {e}")
        return {}

    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        try:
            with open(self.cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"WARNING: Could not save LLM cache: {e}")

    def get(self, prompt: str) -> str | None:
        """Returns cached response for a prompt hash, or None."""
        prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        return self.cache.get(prompt_hash)

    def set(self, prompt: str, response: str):
        """Stores response in cache and persists to disk."""
        prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        self.cache[prompt_hash] = response
        self._save_cache()

# Global cache instance
llm_cache = LLMCache(LLM_CACHE_PATH)

# --- PDF Helper ---
PDF_CACHE = {}

def get_text_from_pdf(path: str, percentage: int, start_pct: int = 0) -> str:
    """Extracts a window of text from a PDF, using a cache."""
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
    
    start_index = int(len(full_text) * (start_pct / 100))
    end_index = int(len(full_text) * (min(start_pct + percentage, 100) / 100))
    
    print(f"Extracted {len(full_text)} chars, returning window {start_pct}%-{start_pct+percentage}% ({end_index - start_index} chars).")
    return full_text[start_index:end_index]

# --- Robust Parsing Helper ---
def parse_llm_answer(persona_name: str, raw_answer: str) -> str:
    """Strips persona-specific artifacts from the LLM's raw response using regex."""
    if "Expert" in persona_name:
        match = re.search(r'^(.*?)Verification:', raw_answer, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return raw_answer.strip()

# --- Knowledge Base Helper ---
def _update_knowledge_base(student, question: pd.Series, user_answer: str, is_correct: bool, correct_answer_index: str, hint_text: str | None):
    """
    Updates student memory with a structured log of attempts and outcomes.
    Groups attempts by question and eliminates 'trial and error' noise once correct.
    NOTE: Hints are no longer persisted to historical context to reduce prompt bloat.
    """
    question_text = question['question_text'].strip()
    
    # 1. Resolve display answer
    display_answer = user_answer
    options_list = []
    if question['question_type'] == 'multiple_choice':
        options_list = [opt.strip() for opt in str(question['options']).split('|')]
        if user_answer and user_answer.isdigit():
            try:
                idx = int(user_answer) - 1
                if 0 <= idx < len(options_list):
                    display_answer = options_list[idx]
            except: pass

    # 2. Extract existing state for this question to rebuild it
    existing_failures = []
    new_kb = []
    for entry in student.knowledge_base:
        # Check if this entry block is for the current question
        if entry.startswith(f'## QUESTION SUMMARY: "{question_text}"'):
            # Extract previous failed answers from the "- your answer:" lines
            for line in entry.split('\n'):
                if line.strip().startswith("- your answer:"):
                    # Extract text after the colon
                    raw_val = line.split(":", 1)[1].strip()
                    existing_failures.append(raw_val)
        else:
            new_kb.append(entry)
    
    student.knowledge_base = new_kb

    # 3. Build new entry block
    if is_correct:
        entry = f'## QUESTION SUMMARY: "{question_text}" ##\nStatus: CORRECT\nYour verified correct answer: <{display_answer}>'
    else:
        # Add current failure if it's a real answer (not a skip/error)
        if display_answer and "i don't know" not in display_answer.lower() and not display_answer.lower().startswith("error"):
            if display_answer not in existing_failures:
                existing_failures.append(display_answer)
        
        entry_lines = [f'## QUESTION SUMMARY: "{question_text}" ##', "Status: INCORRECT / NEEDS REVISIT"]
        if existing_failures:
            entry_lines.append("Previous Failed Attempts (DO NOT REPEAT):")
            for f in existing_failures:
                entry_lines.append(f"- your answer: {f}")
        
        if question['question_type'] == 'multiple_choice':
            remaining = [opt for opt in options_list if opt not in existing_failures]
            if remaining:
                entry_lines.append(f"Remaining possible options: {', '.join(remaining)}")
            
        entry = "\n".join(entry_lines)

    student.knowledge_base.append(entry)
    print(f"[{student.user_id}] Memory updated for question: {question_text[:50]}...")


# --- Simulated Student Class ---
class SimulatedStudent:
    """Represents an LLM-based agent simulating a student."""
    def __init__(self, persona_config: dict, experiment_name: str):
        self.user_id = f"sim_{persona_config['name'].lower().replace(' ', '_')}_{int(time.time())}"
        self.persona = persona_config
        self.experiment_name = experiment_name
        self.hint_style_experience = {}
        
        knowledge_source = self.persona.get('initial_knowledge_prompt', '')
        print(f"Found knowledge source for persona '{self.persona['name']}': {knowledge_source}")
        
        # Knowledge base stores Learning History (attempts/outcomes)
        self.knowledge_base = [] 
        
        # Static Context (PDF excerpts seeded at init)
        self.static_context = ""
        
        if knowledge_source.startswith('[PDF_TEXT_PERCENT:'):
            try:
                percentage = int(knowledge_source.split(':')[1].strip(']'))
                self.static_context = get_text_from_pdf(EVALUATION_PDF_PATH, percentage)
            except (ValueError, IndexError):
                pass 
        elif knowledge_source == "[Expert]":
            # Expert uses heuristic chunking per question; no static context seeded.
            print(f"[{self.user_id}] Expert Persona: Static context will be dynamically loaded per question.")
            pass
        
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set in the environment.")
        genai.configure(api_key=settings.google_api_key)
        self.llm_client = genai.GenerativeModel(settings.google_model_name)
        
        print(f"Initialized student: {self.user_id} with persona '{self.persona['name']}' in experiment '{self.experiment_name}'")
        # Report initial knowledge based on static context
        initial_word_count = len(self.static_context.split()) if self.static_context else 0
        print(f"Knowledge base seeded with {initial_word_count} words.")

    def _get_system_prompt(self) -> str:
        return """
You are a Simulated Student participating in an educational evaluation. 
Your goal is to answer the [QUESTION] accurately by leveraging your [KNOWLEDGE BASE] and your [LEARNING HISTORY].

**GUIDELINES FOR DECISION MAKING:**
1. **Domain Knowledge:** Analyze the provided reference text (e.g., PDF excerpts) for direct answers or relevant concepts.
2. **Learning from Experience:** Review your "Learning History" (previous interactions recorded in the Knowledge Base).
    - If you see a previous attempt at the SAME question marked as "INCORRECT," use that feedback to eliminate that specific option and rethink your logic.
    - If you see a previous "CORRECT" answer from a related question, use that acquired knowledge to derive the answer to the current question.
3. **Metacognition:** Reflect on your past mistakes and successes. Do not repeat failed strategies. Use all feedback provided by the tutor (results and hints) to evolve your understanding.

**TASK:**
1. **Evaluate Confidence (0-100):** How well is the answer supported by your combined knowledge and history?
    - 100: Explicitly stated or verified in history.
    - 50: Partial information or logical deduction required.
    - 0: No information; purely guessing.
2. **List Plausible Options:**
    - For Multiple Choice: List the indices (e.g., ["1", "3"]) of all remaining options that are likely correct. You MUST remove any options you have already tried and found to be INCORRECT.
    - For Fill-in-the-Blank: List the most likely phrase(s).

**OUTPUT FORMAT:**
Only output a JSON object:
{
  "score": <int>,
  "options": ["<opt1>", "<opt2>", ...]
}
"""

    def answer_question(self, question: pd.Series, hint: str | None = None, is_revisit: bool = False) -> tuple[str, str, str, list]:
        options_text = ""
        if question['question_type'] == 'multiple_choice':
            options_list = str(question['options']).split('|')
            options_text = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options_list))
            options_text = f"\n**Multiple Choice Options:**\n{options_text}"

        # --- 1. Build Domain Context ---
        dynamic_context = self.static_context
        if self.persona.get('initial_knowledge_prompt') == "[Expert]":
            segment = int(question.get('context_segment', 1))
            # 35% chunks with overlap to ensure full coverage
            windows = {
                1: (0, 35),      # Segment 1: 0% to 35%
                2: (32.5, 35),   # Segment 2: 32.5% to 67.5%
                3: (65, 35)      # Segment 3: 65% to 100%
            }
            
            distractor_id = 1 if segment == 2 else 2
            
            # Load Target
            s1, sp1 = windows.get(segment, (0, 100))
            t1 = get_text_from_pdf(EVALUATION_PDF_PATH, sp1, s1)
            
            # Load Distractor
            s2, sp2 = windows.get(distractor_id, (0, 100))
            t2 = get_text_from_pdf(EVALUATION_PDF_PATH, sp2, s2)
            
            dynamic_context = t1 + "\n\n" + t2
            print(f"[{self.user_id}] Expert Context: Target {segment} + Distractor {distractor_id}")

        # --- 2. Build History Window (5/10 Rule) ---
        question_text = question['question_text'].strip()
        current_failure_block = None
        other_history = []
        
        for entry in self.knowledge_base:
            if entry.startswith(f'## QUESTION SUMMARY: "{question_text}"'):
                current_failure_block = entry
            else:
                other_history.append(entry)
        
        # Window size logic: 10 for revisit rounds, 5 for initial/retry rounds
        window_size = 10 if is_revisit else 5
        history_window = other_history[-window_size:]
        
        # Always include current question failure (signal) regardless of window size
        if current_failure_block:
            history_window.append(current_failure_block)
            
        history_text = "\n\n".join(history_window) if history_window else "No previous history available."

        # --- 3. Construct Prompt with Explicit Section Blocks ---
        prompt = f"""
{self._get_system_prompt()}

# ***[SECTION: DOMAIN KNOWLEDGE - PDF REFERENCE]***
{dynamic_context}


# ***[SECTION: STUDENT LEARNING HISTORY & PREVIOUS RESULTS]***
--- LEARNING HISTORY ---
{history_text}


# ***[SECTION: TUTOR FEEDBACK - IMMEDIATE HINT]***

{hint if hint else "None provided for this specific attempt."}

# ***[SECTION: CURRENT EVALUATION TASK]***

**QUESTION:** {question_text}
{options_text}

Analyze the references above and provide your evaluation in JSON format:
"""
        print(f"[{self.user_id}] Evaluating question: {question_text[:50]}...")
        raw_response = ""
        try:
            # --- Check Cache First ---
            if CACHE_SCOPE_EXP_NAME:
                cache_key = f"{self.experiment_name}::{prompt}"
            else:
                cache_key = prompt
                
            cached_response = llm_cache.get(cache_key)
            
            if cached_response:
                print(f"   [CACHE HIT]")
                raw_response = cached_response
            else:
                print(f"   [API CALL] Generating answer (pacing 2s)...")
                time.sleep(2)
                response = self.llm_client.generate_content(prompt)
                raw_response = response.text.strip()
                llm_cache.set(cache_key, raw_response)

            # Robust JSON extraction: Try to find all valid JSON blocks
            # We use a non-greedy regex to find candidates
            json_candidates = re.findall(r'(\{.*?\})', raw_response, re.DOTALL)
            
            data = None
            
            # Try parsing each candidate
            for candidate in json_candidates:
                try:
                    # --- FIX: Handle LaTeX backslashes ---
                    # LLMs often output \sqrt or \epsilon which are invalid JSON escapes.
                    # We escape them by doubling the backslash, while preserving valid ones like \"
                    fixed_candidate = re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', candidate)
                    candidate_data = json.loads(fixed_candidate)
                    
                    # Verify schema minimally
                    if "score" in candidate_data and "options" in candidate_data:
                        data = candidate_data
                        break # Found a valid JSON block matching our schema
                except json.JSONDecodeError:
                    continue
            
            if data is None:
                # Fallback: if no non-greedy match worked (e.g. nested objects), try greedy as last resort
                greedy_match = re.search(r'(\{.*\})', raw_response, re.DOTALL)
                if greedy_match:
                    data = json.loads(greedy_match.group(1))
                else:
                    # No braces found at all
                    raise json.JSONDecodeError("No JSON object found in response", raw_response, 0)

            confidence = data.get("score", 0)
            plausible = data.get("options", [])

            # --- Strict Numerical Filtering for MC ---
            if question['question_type'] == 'multiple_choice':
                options_count = len(str(question['options']).split('|'))
                valid_indices = {str(i+1) for i in range(options_count)}
                plausible = [p for p in plausible if str(p) in valid_indices]

            print(f"   -> Score: {confidence}, Options: {plausible}")

            risk_tolerance = self.persona.get('guess_probability', 0.5)
            confidence_threshold = (1.0 - risk_tolerance) * 100

            final_answer = "I don't know"
            if confidence >= confidence_threshold and plausible and plausible != [""]:
                final_answer = random.choice(plausible)

            return prompt, raw_response, str(final_answer), plausible

        except Exception as e:
            print(f"\n[{self.user_id}] FATAL ERROR in answer generation: {e}")
            print(f"=========================================================")
            print(f"RAW RESPONSE:\n{raw_response}")
            print(f"=========================================================")
            print(f"PROMPT (LAST 500 CHARS):\n...{prompt[-500:]}")
            print(f"=========================================================")
            print("Stopping experiment to avoid corrupted results.")
            sys.exit(1)

    def learn_from_hint(self, hint_text: str):
        # Processing logic moved to _update_knowledge_base
        print(f"[{self.user_id}] Received hint: {hint_text[:50]}...")
        pass

    def decide_to_request_hint(self) -> bool:
        return random.random() < self.persona.get('hint_request_probability', 1.0)

    def rate_hint(self, is_correct: bool, is_skipped: bool) -> int:
        """Deterministic rating logic: 5=Correct, 3=Skip, 1=Wrong."""
        if is_skipped: return 3
        if is_correct: return 5
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
    if question['question_type'] == 'multiple_choice':
        # Student answers with index; source CSV stores text. Convert text -> index.
        options_list = str(question['options']).split('|')
        try:
            correct_index = str(options_list.index(question['correct_answer'].strip()) + 1)
            return user_answer.strip() == correct_index
        except ValueError:
            return False

    correct_answer_clean = question['correct_answer'].strip().lower()
    user_answer_clean = user_answer.strip().lower()
    
    # Token-based inclusion (Option C)
    import re
    stop_words = {"a", "an", "the", "of", "and", "in", "on", "at", "to", "is", "are", "was", "were"}
    
    # Use regex to find all alphanumeric words, effectively splitting on hyphens and punctuation
    correct_tokens = [t for t in re.findall(r'\w+', correct_answer_clean) if t not in stop_words]
    
    if not correct_tokens:
        correct_tokens = [t for t in re.findall(r'\w+', correct_answer_clean) if t]

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
    exp_name = experiment['name'].replace(' ', '-')
    pers_name = persona['name'].replace(' ', '-')
    return f"{exp_name}___{pers_name}___{timestamp}"

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
    is_revisit = attempt_type in ['revisit', 'revisit_retry']
    
    print(f"--- Question {int(question['question_number'])} Attempt {attempt_str} (ID: {interaction_id}) ---")

    json_log_path = os.path.join(detailed_log_dir, f"{interaction_id.replace(':', '_').replace('.', '_')}.json")
    json_log_for_attempt = {
        "interaction_id": interaction_id, "run_id": run_id, "user_id": student.user_id,
        "experiment_name": experiment_name, "persona_name": persona_name,
        "question_number": int(question['question_number']), "attempt_number": attempt_str,
        "pre_attempt_knowledge_base": "\n\n".join(student.knowledge_base),
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
        print(f"[{student.user_id}] Proactive check: {proactive_offered}")
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
        
        print(f"   [API CALL] Fetching hint (pacing 2s)...")
        time.sleep(2)
        response = runner.session.post(f"{BASE_URL}/hints", json=payload)
        if response.status_code == 200:
            hint_data = response.json()
            if hint_data.get("hint_style") == "error":
                print(f"[{student.user_id}] FATAL: Backend reported an API Error in hint generation.")
                sys.exit(1)

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
            print(f"CRITICAL ERROR: Hint request failed with status {response.status_code}")
            sys.exit(1)

    # 4. Generate Answer
    prompt, raw_json_response, parsed_answer, plausible_options = student.answer_question(question, hint=final_hint_text, is_revisit=is_revisit)
    
    print(f"[{student.user_id}] Parsed Answer: \"{parsed_answer}\" ")
    answer_event_details = { "llm_prompt": prompt, "llm_raw_response": raw_json_response, "parsed_answer": parsed_answer }

    # 5. Handle Skip/Answer and Feedback
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

    _update_knowledge_base(student, question, parsed_answer, is_correct, tutor_feedback.get('correct_answer'), final_hint_text)
    
    return is_correct, is_skip


def run_single_simulation(experiment: dict, persona: dict, questions: pd.DataFrame):
    """Orchestrates a single simulation run for one experiment-persona combination."""
    print("\n" + "="*50)
    print(f"Starting simulation: Experiment '{experiment['name']}' with Persona '{persona['name']}'")
    print("="*50)

    student = SimulatedStudent(persona, experiment['name'])
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
    final_correct = len(unique_correct_q)
    final_grade_percent = (final_correct / total_questions) * 100 if total_questions > 0 else 0

    print("\n" + "="*50)
    print(f"Simulation finished. Results: {final_correct}/{total_questions} ({final_grade_percent:.1f}%)")
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
