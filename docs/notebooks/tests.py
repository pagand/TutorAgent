# docs/notebooks/test.py
import requests
import json
import time

# --- Stage 2: Test Hint Generation ---
print("--- Testing Stage 2: Hint Generation ---")
base_url = "http://127.0.0.1:8000"
user_id_2 = "stage2_test_user"
hint_payload_2 = {
    "user_id": user_id_2,
    "question_number": 1,
    "user_answer": "An incorrect answer"
}
hint_response_2 = requests.post(f"{base_url}/hints/", json=hint_payload_2)
print(f"Status Code for /hints: {hint_response_2.status_code}")
print("Response for /hints:", json.dumps(hint_response_2.json(), indent=2))
print("-" * 20)


# --- Stage 3: Test Answer Submission and BKT Update ---
print("\n--- Testing Stage 3: Answer Submission & BKT ---")
user_id_3 = "stage3_test_user"
answer_payload_3 = {
    "user_id": user_id_3,
    "question_number": 1,
    "user_answer": "4" # Assuming '4' is incorrect for question 1
}
answer_response_3 = requests.post(f"{base_url}/answer/", json=answer_payload_3)
print(f"Status Code for /answer: {answer_response_3.status_code}")
print("Response for /answer:", json.dumps(answer_response_3.json(), indent=2))

bkt_response_3 = requests.get(f"{base_url}/users/{user_id_3}/bkt")
print(f"Status Code for /bkt: {bkt_response_3.status_code}")
print("Response for /bkt:", json.dumps(bkt_response_3.json(), indent=2))
print("-" * 20)


# --- Stage 4: Test Basic Personalization & Feedback ---
print("\n--- Testing Stage 4: Personalization & Feedback ---")
user_id_4 = "stage4_test_user"
preferences_payload_4 = {
    "preferred_hint_style": "Analogy",
    "feedback_preference": "on_demand"
}
preferences_response = requests.put(f"{base_url}/users/{user_id_4}/preferences", json=preferences_payload_4)
hint_payload_4 = {"user_id": user_id_4, "question_number": 2}
hint_response_4 = requests.post(f"{base_url}/hints/", json=hint_payload_4)
hint_data_4 = hint_response_4.json()
feedback_payload_4 = {
    "user_id": user_id_4,
    "question_id": 2,
    "hint_style": hint_data_4.get("hint_style"),
    "rating": 5,
    "comment": "This analogy was very helpful!"
}
feedback_response_4 = requests.post(f"{base_url}/feedback/", json=feedback_payload_4)
print(f"Status Code for PUT /preferences: {preferences_response.status_code}")
print(f"Status Code for /hints: {hint_response_4.status_code}")
print(f"Status Code for /feedback: {feedback_response_4.status_code}")
print("Response for /feedback:", json.dumps(feedback_response_4.json(), indent=2))
print("-" * 20)


# --- Stage 4.5: Test Adaptive Hint Selection and Hybrid Feedback ---
print("\n--- Testing Stage 4.5: Adaptive Logic ---")
user_id_4_5 = "stage4_5_test_user"

# 1. Seed feedback to train the model
print("\n1. Seeding feedback...")
requests.post(f"{base_url}/feedback/", json={"user_id": user_id_4_5, "question_id": 1, "hint_style": "Analogy", "rating": 5})
requests.post(f"{base_url}/feedback/", json={"user_id": user_id_4_5, "question_id": 1, "hint_style": "Socratic Question", "rating": 1})
print("Feedback seeded.")

# 2. Test Adaptive Selection (Exploitation)
print("\n2. Testing Adaptive Hint Selection...")
requests.put(f"{base_url}/users/{user_id_4_5}/preferences", json={"preferred_hint_style": "Automatic", "feedback_preference": "on_demand"})
hint_payload_4_5 = {"user_id": user_id_4_5, "question_number": 2}
hint_response_4_5 = requests.post(f"{base_url}/hints/", json=hint_payload_4_5)
print(f"Status Code for /hints: {hint_response_4_5.status_code}")
print("Response for /hints:", json.dumps(hint_response_4_5.json(), indent=2))

# 3. Test Post-Hint BKT Performance Tracking
print("\n3. Testing Post-Hint BKT Performance Tracking...")
hint_response_4_5_2 = requests.post(f"{base_url}/hints/", json={"user_id": user_id_4_5, "question_number": 3})
answer_payload_4_5 = {
    "user_id": user_id_4_5,
    "question_number": 3,
    "user_answer": "1",
    "hint_shown": True
}
answer_response_4_5 = requests.post(f"{base_url}/answer/", json=answer_payload_4_5)
print(f"Status Code for /answer: {answer_response_4_5.status_code}")
print("Response for /answer:", json.dumps(answer_response_4_5.json(), indent=2))
print("Check server logs to confirm implicit feedback was recorded.")
print("-" * 20)
