# evaluation/poc_analysis.py
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import argparse
import json
import glob
from analyze_results import load_and_preprocess_data, RESULTS_DIR

# --- Configuration ---
POC_PLOTS_DIR = "evaluation/plots/poc"
sns.set_theme(style="whitegrid") # Set a professional theme for all plots

# --- Plotting Functions ---

def plot_persona_performance(df: pd.DataFrame, plots_dir: str):
    """Generates a bar chart comparing performance across personas."""
    plt.figure(figsize=(12, 7))
    
    # Melt the DataFrame to have a single column for metric type and one for value
    plot_df = df.melt(id_vars='persona_name', 
                      value_vars=['First Attempt Correct Rate', 'Final_Success_Rate'],
                      var_name='Metric', value_name='Success Rate (%)')

    ax = sns.barplot(data=plot_df, x='persona_name', y='Success Rate (%)', hue='Metric', palette="viridis")
    
    plt.title('Persona Performance: Success Rates', fontsize=16)
    plt.xlabel('Student Persona', fontsize=12)
    plt.ylabel('Success Rate (%)', fontsize=12)
    plt.xticks(rotation=10, ha='right')
    plt.ylim(0, 100)
    plt.legend(title='Metric')
    
    # Add labels to the bars
    for p in ax.patches:
        ax.annotate(f'{p.get_height():.1f}%', (p.get_x() + p.get_width() / 2., p.get_height()),
                    ha='center', va='center', fontsize=10, color='black', xytext=(0, 5),
                    textcoords='offset points')

    plt.tight_layout()
    plot_path = os.path.join(plots_dir, "persona_performance_rates.png")
    plt.savefig(plot_path)
    print(f"Saved plot: {plot_path}")
    plt.close()

def plot_intervention_funnel(total_attempts, triggered, accepted, plots_dir: str):
    """Generates a bar chart for the proactive intervention funnel."""
    data = {
        'Stage': ['Total First Attempts', 'Interventions Triggered', 'Hints Accepted'],
        'Count': [total_attempts, triggered, accepted]
    }
    df = pd.DataFrame(data)

    plt.figure(figsize=(10, 6))
    ax = sns.barplot(data=df, x='Stage', y='Count', palette='magma')

    plt.title('Proactive Intervention Funnel', fontsize=16)
    plt.xlabel('')
    plt.ylabel('Number of Interactions', fontsize=12)

    # Add labels to the bars
    for p in ax.patches:
        ax.annotate(f'{int(p.get_height())}', (p.get_x() + p.get_width() / 2., p.get_height()),
                    ha='center', va='center', fontsize=11, color='black', xytext=(0, 5),
                    textcoords='offset points')

    plt.tight_layout()
    plot_path = os.path.join(plots_dir, "proactive_intervention_funnel.png")
    plt.savefig(plot_path)
    print(f"Saved plot: {plot_path}")
    plt.close()

# --- Analysis Functions ---

def generate_case_study(session_df: pd.DataFrame, results_dir: str):
    """
    Generates a step-by-step case study narrative from a session DataFrame.
    """
    first_row = session_df.iloc[0]
    persona_name, q_num, skill_id = first_row['persona_name'], first_row['question_number'], first_row['skill_id']

    print(f"\n--- Case Study: '{persona_name}' on Question #{q_num} (Skill: {skill_id}) ---")
    last_mastery = first_row['initial_mastery']

    for _, row in session_df.iterrows():
        print(f"\n[Attempt {row['attempt_numeric']}]")
        correctness = row['is_correct']
        status = "CORRECT" if correctness else "INCORRECT"
        answer = row['final_answer'] if 'final_answer' in row and pd.notna(row['final_answer']) else row['post_hint_answer'] if pd.notna(row['post_hint_answer']) else row['initial_answer']

        print(f"- BKT Mastery (Before Answer): {last_mastery:.3f}")
        print(f"- Student Answered: \"{str(answer)[:100].strip()}...\" ({status})")
        
        current_mastery = row['mastery_filled']
        if pd.isna(current_mastery):
            print(f"- BKT Mastery (After Answer):  [No Update - Data Not Available]")
        else:
            print(f"- BKT Mastery (After Answer):  {current_mastery:.3f}")
            last_mastery = current_mastery

        if not correctness and pd.notna(row['hint_style_used']):
            interaction_id = row['interaction_id']
            search_pattern = os.path.join(results_dir, '**', f"{interaction_id}.json")
            file_paths = glob.glob(search_pattern, recursive=True)
            
            if file_paths:
                with open(file_paths[0], 'r') as f: hint_data = json.load(f)
                hint_text = hint_data.get('hint_text', '[Hint text not found in JSON]')
                print("\n  [Intervention]")
                print(f"  - System selected a '{row['hint_style_used']}' hint.")
                print(f"  - Hint Text: \"{hint_text[:150].strip()}...\"")
            else:
                 print(f"\n  [Intervention] - WARNING: Could not load JSON for interaction {interaction_id} to get hint text.")

    final_status = "SUCCESS" if session_df['is_correct'].any() else "FAILURE"
    print(f"\n- Final Outcome for Question #{q_num}: {final_status}")


def find_and_select_case_study(df: pd.DataFrame, results_dir: str):
    """Finds the best session for a case study and triggers its generation."""
    print("\n" + "="*20 + " Analysis 5: Anatomy of an Interaction (Case Study) " + "="*20)
    session_counts = df.groupby(['user_id', 'question_number']).size()
    multi_attempt_sessions = session_counts[session_counts > 1].index
    
    possible_cases = []
    for user_id, q_num in multi_attempt_sessions:
        session_df = df[(df['user_id'] == user_id) & (df['question_number'] == q_num)].sort_values('attempt_numeric')
        was_incorrect_first = not session_df['is_first_attempt_correct'].iloc[0]
        hint_shown = session_df['hint_style_used'].notna().any()
        later_correct = session_df['is_correct'].iloc[1:].any()
        if was_incorrect_first and hint_shown and later_correct:
            possible_cases.append(session_df)

    if not possible_cases:
        print("\n[INFO] No sessions matched all three criteria for a case study.")
        return

    possible_cases.sort(key=len, reverse=True)
    generate_case_study(possible_cases[0], results_dir)


def analyze_proactive_system(df: pd.DataFrame, plots_dir: str):
    """Analyzes the proactive intervention system's performance."""
    print("\n" + "="*20 + " Analysis 3: Proactive Intervention Funnel " + "="*20)
    first_attempts_df = df[df['attempt_numeric'] == 1].copy()
    total_questions = len(first_attempts_df)
    triggered_checks = first_attempts_df['proactive_check_result'].eq(True).sum()
    
    if triggered_checks == 0:
        print("The proactive intervention system was not triggered in this dataset.")
        return

    proactive_offers = first_attempts_df[first_attempts_df['proactive_check_result'] == True]
    accepted_offers = proactive_offers['hint_style_used'].notna().sum()
    acceptance_rate = (accepted_offers / triggered_checks) * 100 if triggered_checks > 0 else 0
    
    print(f"\nThis funnel shows how often the proactive system intervened and was accepted.")
    print(f"- Total First Attempts: {total_questions}")
    print(f"- Proactive Interventions Triggered: {triggered_checks} ({triggered_checks/total_questions:.1%})")
    print(f"- Proactive Hints Accepted by Student: {accepted_offers}")
    print(f"- Proactive Hint Acceptance Rate: {acceptance_rate:.1f}%")
    
    plot_intervention_funnel(total_questions, triggered_checks, accepted_offers, plots_dir)


def analyze_poc(df: pd.DataFrame, results_dir: str):
    """Runs a descriptive analysis focused on showcasing system mechanics."""
    if df.empty: return
    os.makedirs(POC_PLOTS_DIR, exist_ok=True)

    print("\n" + "="*20 + " Analysis 1: Persona Performance Profiles " + "="*20)
    final_attempts = df.loc[df.groupby(['user_id', 'question_number'])['timestamp'].idxmax()]
    first_attempts = df[df['attempt_numeric'] == 1]
    
    profile_agg = {'Total Questions': ('question_number', 'nunique'), 'First Attempt Correct Rate': ('is_first_attempt_correct', lambda x: x.mean() * 100), 'Hints Received': ('hint_style_used', 'count')}
    first_attempt_profiles = first_attempts.groupby('persona_name').agg(**profile_agg).reset_index()
    final_success_profiles = final_attempts.groupby('persona_name').agg(Final_Success_Rate=('is_correct', lambda x: x.mean() * 100)).reset_index()
    persona_profiles = pd.merge(first_attempt_profiles, final_success_profiles, on='persona_name')
    
    print("\nThis table provides a high-level summary of each simulated student's performance.")
    print(persona_profiles.to_string(index=False, float_format="%.1f"))
    plot_persona_performance(persona_profiles, POC_PLOTS_DIR)

    print("\n" + "="*20 + " Analysis 2: BKT Learning Trajectory " + "="*20)
    mastery_trajectory_df = df.dropna(subset=['mastery_filled']).copy()
    mastery_trajectory_df['mastery_level'] = mastery_trajectory_df['mastery_filled']
    
    plt.figure(figsize=(14, 8))
    sns.lineplot(data=mastery_trajectory_df, x='question_number', y='mastery_level', hue='persona_name', style='persona_name', marker='o', errorbar='sd')
    plt.title('BKT Mastery Trajectory for Each Persona', fontsize=16)
    plt.ylabel('BKT Mastery Score (Belief of Knowledge)', fontsize=12)
    plt.xlabel('Question Number', fontsize=12)
    plt.grid(True, which='both', linestyle='--', linewidth=0.5); plt.legend(title='Persona'); plt.tight_layout()
    plot_path = os.path.join(POC_PLOTS_DIR, "bkt_mastery_trajectory.png")
    plt.savefig(plot_path)
    print(f"\nThis plot visualizes how the system's belief about each student's knowledge evolves.")
    print(f"Saved plot: {plot_path}"); plt.close()

    analyze_proactive_system(df, POC_PLOTS_DIR)
    find_and_select_case_study(df, results_dir)


def main():
    parser = argparse.ArgumentParser(description="Run descriptive analysis for the AI Tutor POC paper.")
    parser.add_argument("--results_dir", type=str, default=RESULTS_DIR, help="Directory containing the simulation result CSV files.")
    args = parser.parse_args()

    full_df = load_and_preprocess_data(args.results_dir)
    treatment_df = full_df[full_df['experiment_name'].str.contains('Treatment', na=False)].copy()
    
    if not treatment_df.empty:
        print(f"Successfully loaded and filtered {len(treatment_df)} rows for Treatment Groups.")
        analyze_poc(treatment_df, args.results_dir)
    else:
        print("No data found for any 'Treatment Group' experiments. Aborting analysis.")

if __name__ == "__main__":
    main()
