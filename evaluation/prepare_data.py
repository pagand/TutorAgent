import pandas as pd
import json
import os

# Define file paths
SOURCE_QUESTIONS_PATH = os.path.join("evaluation", "data", "evaluation_questions.csv")
SERVER_READY_PATH = os.path.join("evaluation", "data", "server_ready_questions.csv")

def convert_evaluation_questions():
    """
    Converts the human-readable evaluation questions CSV into a format
    that the AI Tutor's QuestionService can directly load.
    """
    print(f"Loading source questions from: {SOURCE_QUESTIONS_PATH}")
    try:
        df = pd.read_csv(SOURCE_QUESTIONS_PATH)
    except FileNotFoundError:
        print(f"ERROR: Source file not found at '{SOURCE_QUESTIONS_PATH}'. Please create it first.")
        return False

    converted_data = []

    for _, row in df.iterrows():
        # Basic column mapping
        new_row = {
            "id": row["question_number"],
            "question": row["question_text"],
            "question_type": row["question_type"],
            "skill": row["skill_id"]
        }

        # Process options and correct_answer based on question type
        if row["question_type"] == "multiple_choice":
            # Ensure options are treated as a string before splitting
            options_str = str(row.get("options", ""))
            options = options_str.split('|')
            correct_answer_text = str(row["correct_answer"])

            # Convert options to a JSON string list
            new_row["options"] = json.dumps(options)

            # Find the 1-based index of the correct answer
            try:
                correct_index = options.index(correct_answer_text) + 1
                new_row["correct_answer"] = correct_index
            except ValueError:
                print(f"ERROR: Correct answer '{correct_answer_text}' not found in options for question {row['question_number']}.")
                print(f"       Options provided: {options}")
                return False
        else: # fill_in_the_blank
            new_row["options"] = ""
            new_row["correct_answer"] = row["correct_answer"]

        converted_data.append(new_row)

    # Create a new DataFrame and save to CSV
    converted_df = pd.DataFrame(converted_data)
    converted_df.to_csv(SERVER_READY_PATH, index=False)
    print(f"Successfully converted {len(converted_df)} questions.")
    print(f"Server-ready file saved to: {SERVER_READY_PATH}")
    return True

if __name__ == "__main__":
    convert_evaluation_questions()
