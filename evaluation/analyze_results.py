# evaluation/analyze_results.py
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import argparse
from scipy import stats
import numpy as np
import ast

# --- Configuration ---
RESULTS_DIR = "evaluation/results"
PLOTS_DIR = "evaluation/plots"

# --- Helper Functions ---
def safe_divide(numerator, denominator):
    if denominator == 0:
        return 0.0
    return numerator / denominator

def parse_list_safe(s):
    try:
        if isinstance(s, list): return s
        if pd.isna(s): return []
        return ast.literal_eval(str(s))
    except (ValueError, SyntaxError):
        return []

# --- Data Loading ---
def load_data(results_dir: str) -> pd.DataFrame:
    all_files = [os.path.join(root, file) for root, _, files in os.walk(results_dir) for file in files if file.endswith(".csv")]
    if not all_files:
        print(f"No CSV files found in '{results_dir}'.")
        return pd.DataFrame()

    df_list = []
    for f in all_files:
        try:
            temp = pd.read_csv(f)
            filename = os.path.basename(f).replace('.csv', '')
            parts = filename.split('_')
            if len(parts) >= 4:
                persona = "_".join(parts[-4:-2])
                experiment = "_".join(parts[:-4])
            else:
                experiment = "Unknown"; persona = "Unknown"

            temp['run_id'] = filename
            temp['experiment_name'] = experiment.replace('_', ' ')
            temp['persona_name'] = persona.replace('_', ' ')
            df_list.append(temp)
        except Exception as e:
            print(f"Skipping {f}: {e}")

    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)
    
    # Type conversions
    if 'is_correct' in df.columns: df['is_correct'] = df['is_correct'].astype(bool)
    if 'plausible_options' in df.columns:
        df['plausible_options'] = df['plausible_options'].apply(parse_list_safe)
        df['plausible_count'] = df['plausible_options'].apply(len)
    
    # Clean attempt number (handle 'revisit_2')
    def clean_attempt(a):
        if isinstance(a, str) and 'revisit' in a:
            try: return int(a.split('_')[1])
            except: return 2
        try: return int(a)
        except: return 1
        
    df['attempt_int'] = df['attempt_number'].apply(clean_attempt)
    
    # Normalize step
    df['step'] = df.groupby('run_id').cumcount() + 1
    return df

# --- Analysis Functions ---

def plot_trajectories(df: pd.DataFrame):
    print("\n" + "="*20 + " Plotting Trajectories " + "="*20)
    metrics = {
        'metric_grade': 'Running Grade (Unique Correct / Total Bank)',
        'metric_engagement': 'Engagement (Attempts / Opportunities)',
        'metric_accuracy': 'Accuracy (Correct / Attempts)',
        'mastery_after_event': 'BKT Mastery Belief'
    }
    
    for metric, label in metrics.items():
        if metric not in df.columns: continue
        plt.figure(figsize=(12, 7))
        # Use simple mean aggregation for lines
        sns.lineplot(data=df, x='step', y=metric, hue='experiment_name', style='persona_name')
        plt.title(f'Trajectory of {label}')
        plt.xlabel('Interaction Sequence (Step)')
        plt.ylabel(label)
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, f"traj_{metric}.png"))
        plt.close()

def analyze_skill_acquisition(df: pd.DataFrame):
    print("\n" + "="*20 + " Skill Acquisition (Transfer Learning) " + "="*20)
    if 'skill_id' not in df.columns: return

    # Filter for Attempt 1 only to measure initial capability
    first_attempts = df[df['attempt_int'] == 1].copy()
    
    # Calculate encounter number for each skill per user
    # We sort by timestamp/step to ensure correct order
    first_attempts = first_attempts.sort_values(['run_id', 'step'])
    first_attempts['skill_encounter'] = first_attempts.groupby(['run_id', 'skill_id']).cumcount() + 1
    
    # Plot: Does success rate increase with encounters?
    plt.figure(figsize=(12, 7))
    sns.lineplot(data=first_attempts, x='skill_encounter', y='is_correct', hue='experiment_name', style='persona_name', marker='o', errorbar=None)
    plt.title('Skill Acquisition: First-Attempt Success vs Encounter Number')
    plt.ylabel('First-Attempt Success Rate')
    plt.xlabel('Times Skill Encountered')
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "skill_acquisition.png"))
    plt.close()

def analyze_mastery_trajectory(df: pd.DataFrame):
    """Plots BKT Mastery growth over QUESTION NUMBER (not step) to align curricula."""
    print("\n" + "="*20 + " Mastery Trajectory Analysis " + "="*20)
    if 'mastery_after_event' not in df.columns: return
    
    # Take the FINAL state of mastery for each question
    final_q_states = df.loc[df.groupby(['run_id', 'question_number'])['step'].idxmax()].copy()
    
    plt.figure(figsize=(12, 7))
    sns.lineplot(data=final_q_states, x='question_number', y='mastery_after_event', hue='experiment_name', style='persona_name')
    plt.title('BKT Mastery Growth over Question Sequence')
    plt.xlabel('Question Number')
    plt.ylabel('Estimated Mastery (Probability)')
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "mastery_trajectory.png"))
    plt.close()

def analyze_skill_performance(df: pd.DataFrame):
    print("\n" + "="*20 + " Skill Performance Breakdown " + "="*20)
    if 'skill_id' not in df.columns: return
    
    # Use final status of each question
    final_states = df.loc[df.groupby(['run_id', 'question_number'])['step'].idxmax()].copy()
    final_states['is_correct_final'] = final_states['final_status'] == 'CORRECT'
    
    plt.figure(figsize=(14, 8))
    sns.barplot(data=final_states, x='skill_id', y='is_correct_final', hue='experiment_name')
    plt.title('Final Success Rate by Skill Topic')
    plt.xticks(rotation=45, ha='right')
    plt.ylabel('Success Rate')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "skill_performance.png"))
    plt.close()

def analyze_hint_convergence(df: pd.DataFrame):
    print("\n" + "="*20 + " Adaptive Hint Convergence " + "="*20)
    if 'hint_style_used' not in df.columns: return
    
    hints = df[df['hint_style_used'].notna()].copy()
    if hints.empty: return

    # Bin into Early/Late
    hints['phase'] = pd.qcut(hints['step'], 2, labels=['Early', 'Late'])
    
    # Count usage
    usage = hints.groupby(['phase', 'hint_style_used']).size().unstack(fill_value=0)
    # Normalize
    usage_pct = usage.div(usage.sum(axis=1), axis=0)
    
    if not usage_pct.empty:
        usage_pct.plot(kind='bar', stacked=True, figsize=(10, 6))
        plt.title('Hint Style Distribution: Early vs Late Session')
        plt.ylabel('Percentage of Usage')
        plt.xlabel('Session Phase')
        plt.legend(bbox_to_anchor=(1.05, 1))
        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, "hint_convergence.png"))
        plt.close()

def analyze_learning_efficiency(df: pd.DataFrame):
    print("\n" + "="*20 + " Learning Efficiency " + "="*20)
    # Filter for Correct Questions
    correct_qs = df[df['is_correct'] == True].copy()
    
    # Find attempt number where it was solved
    solved_at = correct_qs.groupby(['run_id', 'question_number'])['attempt_int'].min().reset_index()
    meta = df[['run_id', 'experiment_name', 'persona_name']].drop_duplicates()
    solved_at = solved_at.merge(meta, on='run_id')
    
    efficiency = solved_at.groupby(['experiment_name', 'persona_name'])['attempt_int'].mean().reset_index()
    print(efficiency.to_string())

    plt.figure(figsize=(10, 6))
    sns.barplot(data=efficiency, x='persona_name', y='attempt_int', hue='experiment_name')
    plt.title('Average Attempts Required to Solve a Question')
    plt.ylabel('Attempts')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "learning_efficiency.png"))
    plt.close()

def analyze_intervention_quality(df: pd.DataFrame):
    print("\n" + "="*20 + " Intervention Analysis " + "="*20)
    if 'proactive_offered' not in df.columns: return

    # Filter for Treatment, First Attempts
    proactive = df[(df['attempt_int'] == 1) & (df['experiment_name'].str.contains('Treatment'))].copy()
    if proactive.empty: return

    def get_status(row):
        if not row['proactive_offered']: return 'Not Triggered'
        if 'ACCEPTED' in str(row['hint_trigger']): return 'Accepted'
        return 'Ignored'
    
    proactive['status'] = proactive.apply(get_status, axis=1)
    proactive['failure'] = ~proactive['is_correct']
    
    summary = proactive.groupby('status')['failure'].mean().reset_index()
    print(summary.to_string())

    plt.figure(figsize=(8, 6))
    sns.barplot(data=summary, x='status', y='failure', order=['Not Triggered', 'Ignored', 'Accepted'])
    plt.title('Failure Rate by Proactive Intervention Status')
    plt.ylabel('Failure Rate')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "intervention_quality.png"))
    plt.close()

def analyze_student_behavior(df: pd.DataFrame):
    print("\n" + "="*20 + " Student Behavior Metrics " + "="*20)
    grouped = df.groupby(['experiment_name', 'persona_name'])
    
    def calc_behavior(x):
        total_ops = x[x['event_type'].isin(['ANSWER', 'SKIP'])].shape[0]
        skips = x[x['event_type'] == 'SKIP'].shape[0]
        return pd.Series({'skip_rate': skips / total_ops if total_ops > 0 else 0})

    behavior = grouped.apply(calc_behavior, include_groups=False).reset_index()
    print(behavior.to_string())

    plt.figure(figsize=(10, 6))
    sns.barplot(data=behavior, x='persona_name', y='skip_rate', hue='experiment_name')
    plt.title('Skip Rate (Lower = Higher Confidence)')
    plt.ylabel('Skip Rate')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "behavior_summary.png"))
    plt.close()

def analyze_final_outcomes(df: pd.DataFrame):
    print("\n" + "="*20 + " Final Outcomes Summary " + "="*20)
    final_states = df.loc[df.groupby('run_id')['step'].idxmax()].copy()
    metrics = ['metric_grade', 'metric_engagement', 'metric_accuracy']
    
    summary = final_states.groupby(['experiment_name', 'persona_name'])[metrics].mean().reset_index()
    print(summary.to_string())
    
    melted = final_states.melt(id_vars=['experiment_name'], value_vars=metrics, var_name='Metric', value_name='Score')
    plt.figure(figsize=(12, 6))
    sns.barplot(data=melted, x='Metric', y='Score', hue='experiment_name')
    plt.title('Overall System Performance Improvement')
    plt.ylim(0, 1.1)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "final_metrics_comparison.png"))
    plt.close()

def main():
    parser = argparse.ArgumentParser(description="Analyze AI Tutor Results")
    parser.add_argument("--results_dir", type=str, default=RESULTS_DIR)
    args = parser.parse_args()
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    df = load_data(args.results_dir)
    if df.empty: return

    plot_trajectories(df)
    analyze_skill_acquisition(df)
    analyze_mastery_trajectory(df)
    analyze_skill_performance(df)
    analyze_hint_convergence(df)
    analyze_learning_efficiency(df)
    analyze_intervention_quality(df)
    analyze_student_behavior(df)
    analyze_final_outcomes(df)

if __name__ == "__main__":
    main()
