# docs/expected_results.py

# This file defines the expected outcomes for each stage of the test script.
# It uses a list of "check" dictionaries, allowing for more granular validation.
#
# Supported Check Types:
# 1.  {"type": "string_contains", "value": "some string"}
#     - Checks if the given string is present in the stage's output.
#
# 2.  {"type": "json_value_equals", "path": "Identifier Text:.key1.key2", "expected": value}
#     - Finds the first JSON block *after* "Identifier Text:".
#     - Navigates the JSON using the dot-separated path.
#     - Asserts that the final value is equal to the expected value.

EXPECTED_RESULTS = {
    "Testing Stage 2: Hint Generation": [
        {"type": "string_contains", "value": "User 'stage2_test_user' created or already exists."},
        {"type": "string_contains", "value": "Status Code for /hints: 200"},
        {"type": "json_value_equals", "path": "Response for /hints:.question_number", "expected": 1},
        {"type": "json_value_equals", "path": "Response for /hints:.user_id", "expected": "stage2_test_user"},
    ],
    "Testing Stage 3: Answer Submission & BKT": [
        {"type": "string_contains", "value": "Status Code for /answer: 200"},
        {"type": "string_contains", "value": "Status Code for /profile: 200"},
        {"type": "json_value_equals", "path": "Response for /answer:.correct", "expected": False},
        {"type": "json_value_equals", "path": "Response for /profile:.user_id", "expected": "stage3_test_user"},
    ],
    "Testing Stage 4: Personalization & Unified Feedback": [
        {"type": "string_contains", "value": "Status Code for PUT /preferences: 200"},
        {"type": "string_contains", "value": "Status Code for /answer with feedback: 200"},
        {"type": "string_contains", "value": "Status Code for /profile: 200"},
        {"type": "json_value_equals", "path": "User Profile with feedback scores:.Analogy.count", "expected": 1},
    ],
    "Testing Stage 4.5: Adaptive Logic & Hybrid Feedback": [
        {"type": "string_contains", "value": "Feedback seeded with a high rating for the hint received."},
        {"type": "json_value_equals", "path": "User Profile with seeded feedback scores:.Socratic Question.count", "expected": 1},
        {"type": "string_contains", "value": "Response for adaptive /hints:"},
        {"type": "json_value_equals", "path": "User Profile after hybrid feedback:.Socratic Question.count", "expected": 2},
    ],
    "Testing Stage 5: Consolidated User Profile": [
        {"type": "string_contains", "value": "Status Code for /profile: 200"},
        {"type": "json_value_equals", "path": "Response for /profile:.interaction_history.0.hint_shown", "expected": True},
        {"type": "json_value_equals", "path": "Response for /profile:.interaction_history.1.hint_shown", "expected": False},
    ],
    "Testing Stage 5.5: Expanded User Model & Question Types": [
        {"type": "string_contains", "value": "Status Code for MC answer: 200"},
        {"type": "string_contains", "value": "Status Code for correct FITB answer: 200"},
        {"type": "json_value_equals", "path": "Final User Profile:.skill_mastery.1.skill_id", "expected": "[Supervised Learning]"},
    ],
    "Verifying Refactor: Consolidated Interaction Log": [
        {"type": "string_contains", "value": "SUCCESS: The interaction log is consolidated and correct."},
        {"type": "json_value_equals", "path": "Latest log entry:.user_feedback_rating", "expected": 4},
    ],
    "Verifying Refactor: History-Informed Prompt": [
        {"type": "string_contains", "value": ">>> VERIFICATION STEP <<<"},
    ]
}