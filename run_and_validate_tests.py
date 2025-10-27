# run_and_validate_tests.py
import subprocess
import sys
import re
import requests
import json
from functools import reduce
import operator

# --- Configuration ---
EXPECTED_RESULTS_PATH = "docs/expected_results.py"
STAGE_TEST_SCRIPT_PATH = "docs/stage_test.py"
BASE_URL = "http://127.0.0.1:8000"

# --- ANSI Color Codes for Output ---
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_pass(message):
    print(f"{Colors.OKGREEN}[PASS]{Colors.ENDC} {message}")

def print_fail(message):
    print(f"{Colors.FAIL}[FAIL]{Colors.ENDC} {message}")

def print_header(message):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*10} {message} {'='*10}{Colors.ENDC}")

class Validator:
    """Encapsulates the logic for validating a block of text output."""
    def __init__(self, output_block):
        self.output_block = output_block
        self.json_cache = {}

    def _find_json_after(self, identifier):
        """Finds and parses the first JSON object after an identifier string."""
        if identifier in self.json_cache:
            return self.json_cache[identifier]
        
        try:
            # Find the start of the identifier
            start_index = self.output_block.index(identifier)
            # Find the first opening brace '{' after the identifier
            json_start_index = self.output_block.index('{', start_index)
            
            # Use a counter to find the matching closing brace '}'
            brace_count = 0
            json_end_index = -1
            for i in range(json_start_index, len(self.output_block)):
                if self.output_block[i] == '{':
                    brace_count += 1
                elif self.output_block[i] == '}':
                    brace_count -= 1
                
                if brace_count == 0:
                    json_end_index = i + 1
                    break
            
            if json_end_index == -1:
                return None

            json_str = self.output_block[json_start_index:json_end_index]
            parsed_json = json.loads(json_str)
            self.json_cache[identifier] = parsed_json
            return parsed_json
        except (ValueError, json.JSONDecodeError):
            return None

    def _get_from_path(self, obj, path):
        """Gets a value from a nested object using a dot-separated path."""
        try:
            # Handle numeric indices for lists
            path_parts = [int(part) if part.isdigit() else part for part in path.split('.')]
            return reduce(operator.getitem, path_parts, obj)
        except (KeyError, TypeError, IndexError):
            return None

    def check(self, check_obj):
        """Dispatches to the correct validation method based on the check type."""
        check_type = check_obj.get("type")
        if check_type == "string_contains":
            return self._check_string_contains(check_obj)
        elif check_type == "json_value_equals":
            return self._check_json_value_equals(check_obj)
        else:
            print_fail(f"Unknown check type: '{check_type}'")
            return False

    def _check_string_contains(self, check_obj):
        value = check_obj["value"]
        if value in self.output_block:
            print_pass(f"String found: '{value}'")
            return True
        else:
            print_fail(f"String not found: '{value}'")
            return False

    def _check_json_value_equals(self, check_obj):
        path_str = check_obj["path"]
        expected = check_obj["expected"]
        
        try:
            identifier, json_path = path_str.split(':', 1)
        except ValueError:
            print_fail(f"Invalid path format for JSON check: '{path_str}'")
            return False

        json_obj = self._find_json_after(identifier)
        if json_obj is None:
            print_fail(f"Could not find or parse JSON block identified by '{identifier}'")
            return False

        actual = self._get_from_path(json_obj, json_path.strip('.'))
        if actual == expected:
            print_pass(f"JSON check passed: '{json_path}' is '{expected}'")
            return True
        else:
            print_fail(f"JSON check failed: '{json_path}' is '{actual}', expected '{expected}'")
            return False

def check_server_status():
    # ... (same as before)
    print(f"Checking server status at {BASE_URL}...")
    try:
        response = requests.get(BASE_URL, timeout=2)
        if response.status_code == 200:
            print_pass("Server is running.")
            return True
        else:
            print_fail(f"Server responded with status code {response.status_code}.")
            return False
    except requests.ConnectionError:
        print_fail("Could not connect to the server.")
        print(f"{Colors.WARNING}Please ensure the Uvicorn server is running in a separate terminal:{Colors.ENDC}")
        print("  uvicorn app.main:app --reload")
        return False

def run_stage_tests():
    # ... (same as before)
    print_header("RUNNING STAGE TESTS")
    
    # --- NEW: Apply database migrations ---
    print("Applying database migrations...")
    try:
        migration_process = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True, check=True
        )
        print_pass("Migrations applied successfully.")
    except subprocess.CalledProcessError as e:
        print_fail("Database migration failed.")
        print(f"Return Code: {e.returncode}")
        print(f"{Colors.FAIL}--- STDOUT ---{Colors.ENDC}\n{e.stdout}")
        print(f"{Colors.FAIL}--- STDERR ---{Colors.ENDC}\n{e.stderr}")
        return None
    # --- END NEW ---

    print(f"Executing script: {STAGE_TEST_SCRIPT_PATH}")
    try:
        process = subprocess.run(
            [sys.executable, STAGE_TEST_SCRIPT_PATH, "--clear-db"],
            capture_output=True, text=True, check=True
        )

        print_pass("Test script executed successfully.")
        return process.stdout
    except subprocess.CalledProcessError as e:
        print_fail("Test script execution failed.")
        print(f"Return Code: {e.returncode}")
        print(f"{Colors.FAIL}--- STDOUT ---{Colors.ENDC}\n{e.stdout}")
        print(f"{Colors.FAIL}--- STDERR ---{Colors.ENDC}\n{e.stderr}")
        return None

def validate_results(output, expected_results):
    print_header("VALIDATING RESULTS")
    stage_pattern = r"--- (.*?) ---"
    headers = list(re.finditer(stage_pattern, output))
    overall_success = True

    for i, header_match in enumerate(headers):
        # The full title is in group 1
        stage_name = header_match.group(1).strip()
        
        # Skip the known, non-test headers from the cleanup utility
        if "Dropping" in stage_name or "Recreating" in stage_name or "reset" in stage_name:
            continue
        
        # Get the start and end positions for this stage's output
        start_pos = header_match.end(0)
        
        # Find the start of the next header, or the end of the output
        end_pos = len(output)
        if i + 1 < len(headers):
            # Look ahead to the next match that isn't a cleanup header
            for next_header in headers[i+1:]:
                if "Dropping" not in next_header.group(1) and "Recreating" not in next_header.group(1) and "reset" not in next_header.group(1):
                    end_pos = next_header.start(0)
                    break
        
        stage_output = output[start_pos:end_pos]
        
        print(f"\n{Colors.OKBLUE}Validating: {stage_name}{Colors.ENDC}")
        
        if stage_name not in expected_results:
            print_fail(f"No expected results found for stage '{stage_name}'.")
            overall_success = False
            continue

        validator = Validator(stage_output)
        stage_checks = expected_results[stage_name]
        all_checks_passed = True
        for check_obj in stage_checks:
            if not validator.check(check_obj):
                all_checks_passed = False
                overall_success = False
        
        if not all_checks_passed:
            print(f"{Colors.WARNING}--- Output for {stage_name} ---{Colors.ENDC}\n{stage_output.strip()}\n")

    return overall_success

def main():
    print("Make sure the db is correct and the config file has the test cases and questions.")
    if not check_server_status():
        sys.exit(1)

    try:
        from docs.expected_results import EXPECTED_RESULTS
    except ImportError:
        print_fail(f"Could not import EXPECTED_RESULTS from '{EXPECTED_RESULTS_PATH}'.")
        sys.exit(1)

    test_output = run_stage_tests()

    if test_output:
        success = validate_results(test_output, EXPECTED_RESULTS)
        print_header("FINAL SUMMARY")
        if success:
            print_pass("All validation checks passed!")
        else:
            print_fail("Some validation checks failed. Please review the output above.")
            sys.exit(1)

if __name__ == "__main__":
    main()
