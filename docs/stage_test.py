# docs/notebooks/test.py
import requests
import json
import time

base_url = "http://127.0.0.1:8000"

# --- Helper to Create User ---
def create_user(user_id):
    """Creates a user if they don't exist."""
    try:
        response = requests.post(f"{base_url}/users/", json={"user_id": user_id})
        # 200 OK (created), 201 Created, or 409 Conflict (already exists) are all success conditions here
        if response.status_code in [200, 201, 409]:
            print(f"User '{user_id}' created or already exists.")
            return True
        else:
            print(f"Error: Failed to create user '{user_id}'. Status: {response.status_code}, Response: {response.text}")
            return False
    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error: Could not connect to the server at {base_url}.")
        print("Please ensure the Uvicorn server is running: uvicorn app.main:app --reload")
        return False

# --- Stage 2: Test Hint Generation ---
print("--- Testing Stage 2: Hint Generation ---")
user_id_2 = "stage2_test_user"
if create_user(user_id_2):
    hint_payload_2 = {
        "user_id": user_id_2,
        "question_number": 1,
        "user_answer": "An incorrect answer"
    }
    hint_response_2 = requests.post(f"{base_url}/hints/", json=hint_payload_2)
    print(f"Status Code for /hints: {hint_response_2.status_code}")
    if hint_response_2.status_code == 200:
        print("Response for /hints:", json.dumps(hint_response_2.json(), indent=2))
    else:
        print(f"Error: /hints/ endpoint returned status {hint_response_2.status_code}. Response: {hint_response_2.text}")
else:
    print(f"Error: Could not create user '{user_id_2}'. Skipping Stage 2 tests.")
print("-" * 20)


# --- Stage 3: Test Answer Submission and BKT Update ---
print("\n--- Testing Stage 3: Answer Submission & BKT ---")
user_id_3 = "stage3_test_user"
if create_user(user_id_3):
    answer_payload_3 = {
        "user_id": user_id_3,
        "question_number": 1,
        "user_answer": "4" # Assuming '4' is incorrect for question 1
    }
    answer_response_3 = requests.post(f"{base_url}/answer/", json=answer_payload_3)
    print(f"Status Code for /answer: {answer_response_3.status_code}")
    if answer_response_3.status_code == 200:
        print("Response for /answer:", json.dumps(answer_response_3.json(), indent=2))
    else:
        print(f"Error: /answer/ endpoint returned status {answer_response_3.status_code}. Response: {answer_response_3.text}")

    # MODIFIED FOR STAGE 5: Check the consolidated profile endpoint
    profile_response_3 = requests.get(f"{base_url}/users/{user_id_3}/profile")
    print(f"Status Code for /profile: {profile_response_3.status_code}")
    if profile_response_3.status_code == 200:
        print("Response for /profile:", json.dumps(profile_response_3.json(), indent=2))
    else:
        print(f"Error: /users/{{user_id}}/profile endpoint returned status {profile_response_3.status_code}. Response: {profile_response_3.text}")
else:
    print(f"Error: Could not create user '{user_id_3}'. Skipping Stage 3 tests.")
print("-" * 20)


# --- Stage 4: Test Personalization & Unified Feedback ---
print("\n--- Testing Stage 4: Personalization & Unified Feedback ---")
user_id_4 = "stage4_test_user"
if create_user(user_id_4):
    # Set a preference using the CORRECT, complete payload
    preferences_payload_4 = {
        "hint_style_preference": "Analogy",
        "intervention_preference": "manual"
    }
    preferences_response = requests.put(f"{base_url}/users/{user_id_4}/preferences/", json=preferences_payload_4)
    print(f"Status Code for PUT /preferences: {preferences_response.status_code}")
    if preferences_response.status_code != 200:
        print(f"Error setting preferences: {preferences_response.text}")

    # Get a hint
    hint_payload_4 = {"user_id": user_id_4, "question_number": 2, "user_answer": "Incorrect"}
    hint_response_4 = requests.post(f"{base_url}/hints/", json=hint_payload_4)
    print(f"Status Code for /hints: {hint_response_4.status_code}")
    
    if hint_response_4.status_code == 200:
        # CORRECTED: Capture hint_style and pre_hint_mastery from the response
        hint_data_4 = hint_response_4.json()
        hint_style_used_4 = hint_data_4.get("hint_style")
        pre_hint_mastery_4 = hint_data_4.get("pre_hint_mastery")
        hint_text_4 = hint_data_4.get("hint")
        print(f"Hint style received: {hint_style_used_4}, Pre-hint mastery: {pre_hint_mastery_4}")

        # Now, submit an answer and provide feedback at the same time
        print("\nSubmitting an answer with feedback...")
        answer_payload_4 = {
            "user_id": user_id_4,
            "question_number": 2,
            "user_answer": "A correct or incorrect answer",
            "hint_shown": True,
            "hint_style_used": hint_style_used_4,
            "pre_hint_mastery": pre_hint_mastery_4,
            "hint_text": hint_text_4,
            "feedback_rating": 5 
        }
        answer_response_4 = requests.post(f"{base_url}/answer/", json=answer_payload_4)
        print(f"Status Code for /answer with feedback: {answer_response_4.status_code}")
        
        if answer_response_4.status_code == 200:
            print("Response for /answer with feedback:", json.dumps(answer_response_4.json(), indent=2))
            
            # Verify feedback was saved by fetching user profile
            print("\nVerifying feedback was saved by fetching user profile...")
            profile_response_4 = requests.get(f"{base_url}/users/{user_id_4}/profile")
            print(f"Status Code for /profile: {profile_response_4.status_code}")
            if profile_response_4.status_code == 200:
                profile_data = profile_response_4.json()
                print("User Profile with feedback scores:", json.dumps(profile_data.get("feedback_scores"), indent=2))
            else:
                print(f"Error: Could not fetch profile for user '{user_id_4}'.")
        else:
            print(f"Error: /answer endpoint returned status {answer_response_4.status_code}. Response: {answer_response_4.text}")
    else:
        print(f"Error: /hints/ endpoint returned status {hint_response_4.status_code}. Response: {hint_response_4.text}")
else:
    print(f"Error: Could not create user '{user_id_4}'. Skipping Stage 4 tests.")
print("-" * 20)


# --- Stage 4.5: Test Adaptive Hint Selection and Hybrid Feedback ---
print("\n--- Testing Stage 4.5: Adaptive Logic & Hybrid Feedback ---")
user_id_4_5 = "stage4_5_test_user"
if create_user(user_id_4_5):
    # 1. Seed feedback to train the model by forcing a specific style
    print("\n1. Seeding feedback by simulating an interaction...")
    # Set a preference to make the hint style predictable
    requests.put(f"{base_url}/users/{user_id_4_5}/preferences/", json={
        "hint_style_preference": "Socratic Question",
        "intervention_preference": "manual"
    })
    
    hint_payload_seed = {"user_id": user_id_4_5, "question_number": 1, "user_answer": "Incorrect"}
    hint_response_seed = requests.post(f"{base_url}/hints/", json=hint_payload_seed)
    
    if hint_response_seed.status_code == 200:
        hint_data_seed = hint_response_seed.json()
        hint_style_seed = hint_data_seed.get("hint_style")
        pre_hint_mastery_seed = hint_data_seed.get("pre_hint_mastery")
        hint_text_seed = hint_data_seed.get("hint")
        print(f"Seeding with hint style: {hint_style_seed}, Pre-hint mastery: {pre_hint_mastery_seed}")

        # Now, submit an answer to that question with a high rating
        answer_payload_seed = {
            "user_id": user_id_4_5,
            "question_number": 1,
            "user_answer": "3", # Correct answer for Q1
            "hint_shown": True,
            "hint_style_used": hint_style_seed,
            "pre_hint_mastery": pre_hint_mastery_seed,
            "hint_text": hint_text_seed,
            "feedback_rating": 5 
        }
        requests.post(f"{base_url}/answer/", json=answer_payload_seed)
        print("Feedback seeded with a high rating for the hint received.")
    else:
        print(f"Error getting a hint for seeding: {hint_response_seed.text}")

    # Verify seeded feedback
    print("\nVerifying seeded feedback by fetching user profile...")
    profile_response_4_5_seeded = requests.get(f"{base_url}/users/{user_id_4_5}/profile")
    if profile_response_4_5_seeded.status_code == 200:
        profile_data = profile_response_4_5_seeded.json()
        print("User Profile with seeded feedback scores:", json.dumps(profile_data.get("feedback_scores"), indent=2))
    else:
        print(f"Error: Could not fetch profile for user '{user_id_4_5}'.")

    # 2. Test Adaptive Selection (Exploitation)
    print("\n2. Testing Adaptive Hint Selection (should exploit the high-rated style)...")
    requests.put(f"{base_url}/users/{user_id_4_5}/preferences/", json={
        "hint_style_preference": "adaptive",
        "intervention_preference": "manual"
    })
    hint_payload_4_5 = {"user_id": user_id_4_5, "question_number": 2, "user_answer": "Incorrect"}
    hint_response_4_5 = requests.post(f"{base_url}/hints/", json=hint_payload_4_5)
    print(f"Status Code for /hints: {hint_response_4_5.status_code}")
    if hint_response_4_5.status_code == 200:
        print("Response for adaptive /hints:", json.dumps(hint_response_4_5.json(), indent=2))
    else:
        print(f"Error: /hints/ endpoint for adaptive selection returned status {hint_response_4_5.status_code}. Response: {hint_response_4_5.text}")

    # 3. Test Hybrid Feedback (Implicit + Explicit)
    print("\n3. Testing Hybrid Feedback (Implicit performance + Explicit rating)...")
    hint_response_4_5_2 = requests.post(f"{base_url}/hints/", json={"user_id": user_id_4_5, "question_number": 3, "user_answer": "Incorrect"})
    if hint_response_4_5_2.status_code == 200:
        # CORRECTED: Capture hint_style and pre_hint_mastery from the response
        hint_data_4_5_2 = hint_response_4_5_2.json()
        hint_style_4_5_2 = hint_data_4_5_2.get("hint_style")
        pre_hint_mastery_4_5_2 = hint_data_4_5_2.get("pre_hint_mastery")
        hint_text_4_5_2 = hint_data_4_5_2.get("hint")
        print(f"Testing hybrid feedback with hint style: {hint_style_4_5_2}, Pre-hint mastery: {pre_hint_mastery_4_5_2}")
        
        # This time, the user answers incorrectly (bad performance) and gives a low rating (bad explicit feedback)
        answer_payload_4_5 = {
            "user_id": user_id_4_5,
            "question_number": 3,
            "user_answer": "Incorrect Answer",
            "hint_shown": True,
            "hint_style_used": hint_style_4_5_2,
            "pre_hint_mastery": pre_hint_mastery_4_5_2,
            "hint_text": hint_text_4_5_2,
            "feedback_rating": 1 
        }
        answer_response_4_5 = requests.post(f"{base_url}/answer/", json=answer_payload_4_5)
        print(f"Status Code for /answer: {answer_response_4_5.status_code}")
        if answer_response_4_5.status_code == 200:
            print("Response for /answer:", json.dumps(answer_response_4_5.json(), indent=2))
            
            # Verify hybrid feedback was recorded
            print("\nVerifying hybrid feedback was recorded by fetching profile again...")
            profile_response_4_5_implicit = requests.get(f"{base_url}/users/{user_id_4_5}/profile")
            if profile_response_4_5_implicit.status_code == 200:
                profile_data = profile_response_4_5_implicit.json()
                print("User Profile after hybrid feedback:", json.dumps(profile_data.get("feedback_scores"), indent=2))
            else:
                print(f"Error: Could not fetch profile for user '{user_id_4_5}'.")
        else:
            print(f"Error: /answer/ endpoint for BKT tracking returned status {answer_response_4_5.status_code}. Response: {answer_response_4_5.text}")
        print("Check server logs to confirm hybrid feedback was recorded.")
    else:
        print(f"Error: /hints/ endpoint for BKT tracking returned status {hint_response_4_5_2.status_code}. Response: {hint_response_4_5_2.text}")
else:
    print(f"Error: Could not create user '{user_id_4_5}'. Skipping Stage 4.5 tests.")
print("-" * 20)

# --- Stage 5: Test User Profile Endpoint ---
print("\n--- Testing Stage 5: Consolidated User Profile ---")
user_id_5 = "stage5_profile_user"
if create_user(user_id_5):
    # Make a few calls to populate the user's history realistically
    print("\n1. Answering a question without a hint...")
    requests.post(f"{base_url}/answer/", json={"user_id": user_id_5, "question_number": 1, "user_answer": "Incorrect answer 1"})
    
    print("\n2. Requesting a hint for another question...")
    hint_response_5 = requests.post(f"{base_url}/hints/", json={"user_id": user_id_5, "question_number": 2, "user_answer": "Incorrect answer 2"})
    hint_data_5 = hint_response_5.json()
    hint_style_5 = hint_data_5.get("hint_style")
    pre_hint_mastery_5 = hint_data_5.get("pre_hint_mastery")
    hint_text_5 = hint_data_5.get("hint")
    print(f"Hint received with style: {hint_style_5}, Pre-hint mastery: {pre_hint_mastery_5}")

    print("\n3. Answering the second question after seeing the hint...")
    requests.post(f"{base_url}/answer/", json={
        "user_id": user_id_5, 
        "question_number": 2, 
        "user_answer": "A better answer", 
        "hint_shown": True,
        "hint_style_used": hint_style_5,
        "pre_hint_mastery": pre_hint_mastery_5,
        "hint_text": hint_text_5
    })
    
    # Fetch the consolidated profile
    print("\n4. Fetching the final consolidated profile...")
    profile_response_5 = requests.get(f"{base_url}/users/{user_id_5}/profile")
    print(f"Status Code for /profile: {profile_response_5.status_code}")
    if profile_response_5.status_code == 200:
        print("Response for /profile:", json.dumps(profile_response_5.json(), indent=2))
    else:
        print(f"Error: /users/{{user_id}}/profile endpoint returned status {profile_response_5.status_code}. Response: {profile_response_5.text}")
else:
    print(f"Error: Could not create user '{user_id_5}'. Skipping Stage 5 tests.")
print("-" * 20)



# --- Stage 5.5: Test Expanded User Model & Multiple Question Types ---
print("\n--- Testing Stage 5.5: Expanded User Model & Question Types ---")
user_id_5_5 = f"stage5_5_test_user_{int(time.time())}"
if create_user(user_id_5_5):
    # 1. Answer a multiple_choice question incorrectly
    print("\n1. Answering a multiple-choice question incorrectly...")
    mc_payload = {
        "user_id": user_id_5_5,
        "question_number": 1,
        "user_answer": "1",  # Correct is 3
    }
    mc_response = requests.post(f"{base_url}/answer/", json=mc_payload)
    print(f"Status Code for MC answer: {mc_response.status_code}")
    print("Response:", json.dumps(mc_response.json(), indent=2))

    # 2. Answer a fill_in_the_blank question incorrectly
    print("\n2. Answering a fill-in-the-blank question incorrectly...")
    fitb_payload = {
        "user_id": user_id_5_5,
        "question_number": 6,
        "user_answer": "LinearRegression",  # Correct is "LogisticRegression"
    }
    fitb_response = requests.post(f"{base_url}/answer/", json=fitb_payload)
    print(f"Status Code for FITB answer: {fitb_response.status_code}")
    print("Response:", json.dumps(fitb_response.json(), indent=2))

    # 3. Request a hint, which should now be informed by the history
    print("\n3. Requesting a hint (should be history-informed)...")
    hint_payload_5_5 = {
        "user_id": user_id_5_5,
        "question_number": 6,
    }
    hint_response_5_5 = requests.post(f"{base_url}/hints/", json=hint_payload_5_5)
    print(f"Status Code for hint: {hint_response_5_5.status_code}")
    print("Response:", json.dumps(hint_response_5_5.json(), indent=2))
    print(">>> CHECK THE SERVER LOGS to see the '{user_history}' block sent to the LLM. <<<")

    # 4. Answer the fill-in-the-blank question correctly
    print("\n4. Answering the fill-in-the-blank question correctly...")
    fitb_correct_payload = {
        "user_id": user_id_5_5,
        "question_number": 6,
        "user_answer": "LogisticRegression",
    }
    fitb_correct_response = requests.post(f"{base_url}/answer/", json=fitb_correct_payload)
    print(f"Status Code for correct FITB answer: {fitb_correct_response.status_code}")
    print("Response:", json.dumps(fitb_correct_response.json(), indent=2))

    # 5. Retrieve the user's profile to verify the full interaction history
    print("\n5. Retrieving final user profile to verify history...")
    profile_response_5_5 = requests.get(f"{base_url}/users/{user_id_5_5}/profile")
    print(f"Status Code for profile: {profile_response_5_5.status_code}")
    if profile_response_5_5.status_code == 200:
        print("Final User Profile:", json.dumps(profile_response_5_5.json(), indent=2))
    else:
        print(f"Error: Could not fetch profile for user '{user_id_5_5}'.")
else:
    print(f"Error: Could not create user '{user_id_5_5}'. Skipping Stage 5.5 tests.")
print("-" * 20)


# --- Database Cleanup Utility ---
def clear_test_database(interactive=True):
    """
    Connects to the database specified in the .env file and drops/recreates all tables.
    This will DELETE ALL DATA in the database.
    """
    import asyncio
    import os
    import sys

    # This is necessary to import the application's modules
    # Correct the path to be relative to this script's location
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from sqlalchemy.ext.asyncio import create_async_engine
    from app.models.user import Base
    from app.utils.config import settings

    async def _reset_db():
        # Create an engine to connect to the database
        engine = create_async_engine(settings.database_url, echo=False)
        
        async with engine.begin() as conn:
            print("--- Dropping all database tables... ---")
            await conn.run_sync(Base.metadata.drop_all)
            print("--- Recreating all database tables... ---")
            await conn.run_sync(Base.metadata.create_all)
        
        # Dispose of the engine connection
        await engine.dispose()
        print("--- Database has been successfully reset. ---")

    if interactive:
        print("WARNING: This action is irreversible and will delete all data in the database.")
        choice = input("Are you sure you want to clear the database? (yes/no): ").lower().strip()
    else:
        choice = 'yes'
    
    if choice == 'yes':
        try:
            asyncio.run(_reset_db())
        except Exception as e:
            print(f"An error occurred during database reset: {e}")
            print("Please ensure your .env file is configured correctly and the database server is running.")
    else:
        print("Database cleanup cancelled.")

# --- Main Execution Block ---
# To run the tests and then be prompted to clear the database,
# simply run the script directly: python docs/stage_test.py

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run stage tests for the AI Tutor API.")
    parser.add_argument("--clear-db", action="store_true", help="Clear the database after running tests.")
    args = parser.parse_args()

    # --- Verification Test for Consolidated Interaction Log (Post-Refactor) ---
    print("\n--- Verifying Refactor: Consolidated Interaction Log ---")
    user_id_log_refactor = f"log_refactor_user_{int(time.time())}"
    if create_user(user_id_log_refactor):
        # 1. Request a hint for a question
        print("\n1. Requesting a hint...")
        hint_payload = {"user_id": user_id_log_refactor, "question_number": 4}
        hint_response = requests.post(f"{base_url}/hints/", json=hint_payload)
        hint_data = hint_response.json()
        hint_style_used = hint_data.get("hint_style")
        pre_hint_mastery = hint_data.get("pre_hint_mastery")
        hint_text = hint_data.get("hint")
        print(f"Hint received with style: {hint_style_used}, Pre-hint mastery: {pre_hint_mastery}")

        # 2. Submit an answer for that question, including all hint and feedback details
        print("\n2. Submitting an answer with full context...")
        answer_payload = {
            "user_id": user_id_log_refactor,
            "question_number": 4,
            "user_answer": "An answer after a hint",
            "hint_shown": True,
            "hint_style_used": hint_style_used,
            "pre_hint_mastery": pre_hint_mastery,
            "hint_text": hint_text,
            "feedback_rating": 4
        }
        answer_response = requests.post(f"{base_url}/answer/", json=answer_payload)
        print(f"Status Code for answer: {answer_response.status_code}")

        # 3. Fetch the profile and verify the interaction log
        print("\n3. Fetching profile to verify the log...")
        profile_response = requests.get(f"{base_url}/users/{user_id_log_refactor}/profile")
        if profile_response.status_code == 200:
            profile_data = profile_response.json()
            print("Profile fetched successfully.")
            
            print("\n" + "="*60)
            print(">>> VERIFICATION STEP <<<")
            print("Checking the 'interaction_history' in the user profile...")
            history = profile_data.get("interaction_history", [])
            if history:
                latest_log = history[0]
                print("Latest log entry:", json.dumps(latest_log, indent=2))
                if (latest_log.get("hint_shown") is True and
                    latest_log.get("hint_style_used") == hint_style_used and
                    latest_log.get("user_feedback_rating") == 4):
                    print("\nSUCCESS: The interaction log is consolidated and correct.")
                else:
                    print("\nERROR: The interaction log does not contain the correct hint/feedback details.")
            else:
                print("\nERROR: No interaction history found in the profile.")
            print("="*60)
        else:
            print(f"Error: Could not fetch profile. Status: {profile_response.status_code}, Response: {profile_response.text}")
    else:
        print(f"Error: Could not create user '{user_id_log_refactor}'.")
    print("-" * 20)

    # --- Verification Test for History-Informed Prompt (Post-Refactor) ---
    print("\n--- Verifying Refactor: History-Informed Prompt ---")
    user_id_refactor = f"refactor_test_user_{int(time.time())}"
    if create_user(user_id_refactor):
        # 1. Submit a very specific, incorrect answer to create a clear history entry.
        print("\n1. Submitting a unique incorrect answer...")
        answer_payload = {
            "user_id": user_id_refactor,
            "question_number": 5,
            "user_answer": "My cat's name is Whiskers",
        }
        answer_response = requests.post(f"{base_url}/answer/", json=answer_payload)
        print(f"Status Code for answer: {answer_response.status_code}")

        # 2. Immediately request a hint for the same question.
        print("\n2. Requesting a hint for the same question...")
        hint_payload = {
            "user_id": user_id_refactor,
            "question_number": 5,
            "user_answer": "My cat's name is Whiskers", # The user might try the same answer again
        }
        hint_response = requests.post(f"{base_url}/hints/", json=hint_payload)
        print(f"Status Code for hint: {hint_response.status_code}")
        if hint_response.status_code == 200:
            print("Hint Response:", json.dumps(hint_response.json(), indent=2))
        
        print("\n" + "="*60)
        print(">>> VERIFICATION STEP <<<")
        print("Check the Uvicorn server logs running in your terminal.")
        print("You should see a log entry for the RAG agent that includes a")
        print("'user_history' section containing the line:")
        print("  '- Q5: Answered 'My cat's name is Whiskers' (Incorrect).'\"")
        print("This confirms the user's history is now correctly passed to the LLM.")
        print("="*60)
    else:
        print(f"Error: Could not create user '{user_id_refactor}'. Skipping refactor verification test.")
    print("-" * 20)


    # --- Stage 5.7: Test Proactive Intervention Check ---
    print("\n--- Testing Stage 5.7: Proactive Intervention ---")
    user_id_5_7 = f"stage5_7_intervention_user_{int(time.time())}"
    if create_user(user_id_5_7):
        # Scenario 1: Intervention preference is 'manual'. Should return False.
        print("\n1. User intervention preference is 'manual'. Intervention should be false.")
        requests.put(f"{base_url}/users/{user_id_5_7}/preferences/", json={"intervention_preference": "manual"})
        check_payload_1 = {"user_id": user_id_5_7, "question_number": 1, "time_spent_ms": 99999}
        check_response_1 = requests.post(f"{base_url}/intervention-check", json=check_payload_1)
        print(f"Status Code: {check_response_1.status_code}")
        print("Response for check (preference):", json.dumps(check_response_1.json(), indent=2))

        # --- SETUP for time-based tests: Create a user with a "middle" mastery level ---
        print("\nSetting up for time-based check by creating a user with mid-level mastery...")
        # Answer incorrectly once, then correctly once, to land mastery above the 0.4 threshold but not too high.
        requests.post(f"{base_url}/answer/", json={"user_id": user_id_5_7, "question_number": 2, "user_answer": "wrong answer"})
        requests.post(f"{base_url}/answer/", json={"user_id": user_id_5_7, "question_number": 2, "user_answer": "1"}) # Correct answer is "1"
        # --- END SETUP ---

        # Scenario 2: Preference is 'proactive', but time spent is BELOW threshold. Should return False.
        print("\n2. User intervention preference is 'proactive' but time is below threshold. Intervention should be false.")
        requests.put(f"{base_url}/users/{user_id_5_7}/preferences/", json={"intervention_preference": "proactive"})
        check_payload_2 = {"user_id": user_id_5_7, "question_number": 2, "time_spent_ms": 100} # Very short time
        check_response_2 = requests.post(f"{base_url}/intervention-check", json=check_payload_2)
        print(f"Status Code: {check_response_2.status_code}")
        print("Response for check (time below):", json.dumps(check_response_2.json(), indent=2))

        # Scenario 3: Preference is 'proactive' AND time spent is ABOVE threshold. Should return True.
        print("\n3. User intervention preference is 'proactive' and time is above threshold. Intervention should be true.")
        check_payload_3 = {"user_id": user_id_5_7, "question_number": 2, "time_spent_ms": 99999} # Very long time
        check_response_3 = requests.post(f"{base_url}/intervention-check", json=check_payload_3)
        print(f"Status Code: {check_response_3.status_code}")
        print("Response for check (time above):", json.dumps(check_response_3.json(), indent=2))
    else:
        print(f"Error: Could not create user '{user_id_5_7}'. Skipping Stage 5.7 tests.")
    print("-" * 20)


    # --- Verification Test for Skipped Question Logic ---
    print("\n--- Verifying Refactor: Skipped Question Logic ---")
    user_id_skip = f"skip_test_user_{int(time.time())}"
    if create_user(user_id_skip):
        # 1. Get initial mastery for a skill
        profile_before = requests.get(f"{base_url}/users/{user_id_skip}/profile").json()
        mastery_before = 0.2 # Default
        for skill in profile_before.get("skill_mastery", []):
            if skill['skill_id'] == '[LoRA-Quantization-Basics]':
                mastery_before = skill['mastery_level']
        print(f"Initial mastery for [LoRA-Quantization-Basics]: {mastery_before}")

        # 2. Submit a skipped answer
        print("\n1. Submitting a skipped answer...")
        skip_payload = {
            "user_id": user_id_skip,
            "question_number": 1,
            "skipped": True
        }
        skip_response = requests.post(f"{base_url}/answer/", json=skip_payload)
        print(f"Status Code for skipped answer: {skip_response.status_code}")

        # 3. Fetch profile and verify mastery is unchanged and skip is logged
        print("\n2. Fetching profile to verify...")
        profile_after = requests.get(f"{base_url}/users/{user_id_skip}/profile").json()
        mastery_after = 0.2 # Default
        for skill in profile_after.get("skill_mastery", []):
            if skill['skill_id'] == '[LoRA-Quantization-Basics]':
                mastery_after = skill['mastery_level']
        print(f"Mastery after skip: {mastery_after}")
        
        print("\n" + "="*60)
        print(">>> VERIFICATION STEP <<<")
        print("Verifying BKT mastery was not changed by the skipped question...")
        if mastery_before == mastery_after:
            print("\nSUCCESS: BKT mastery is unchanged.")
        else:
            print(f"\nERROR: BKT mastery changed. Before: {mastery_before}, After: {mastery_after}")
        
        history = profile_after.get("interaction_history", [])
        if history and history[0].get("user_answer") is None:
             print("\nSUCCESS: Interaction log correctly shows a skipped answer (user_answer is null).")
        else:
             print("\nERROR: Interaction log does not correctly reflect the skipped answer.")
        print("="*60)

    else:
        print(f"Error: Could not create user '{user_id_skip}'.")
    print("-" * 20)


    if args.clear_db:
        clear_test_database(interactive=False)
