# evaluation/analyze_results.py
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import argparse
from scipy import stats

# --- Configuration ---
RESULTS_DIR = "evaluation/results"
PLOTS_DIR = "evaluation/plots"

# --- Data Loading and Preprocessing ---
def load_and_preprocess_data(results_dir: str) -> pd.DataFrame:
    """Loads all CSV files from the results directory into a single DataFrame."""
    all_files = []
    for root, _, files in os.walk(results_dir):
        for file in files:
            if file.endswith(".csv"):
                all_files.append(os.path.join(root, file))
    
    if not all_files:
        print(f"No CSV files found in '{results_dir}'. Aborting.")
        return pd.DataFrame()

    df_list = [pd.read_csv(f) for f in all_files]
    df = pd.concat(df_list, ignore_index=True)
    
    print(f"Loaded {len(df)} rows from {len(all_files)} CSV files.")

    # --- Data Cleaning and Feature Engineering ---
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Create a unified first-attempt correctness column to handle proactive hints
    df['is_first_attempt_correct'] = df.apply(
        lambda row: row['post_hint_correctness'] if row['attempt'] == 1 and pd.isna(row['initial_correctness']) else row['initial_correctness'],
        axis=1
    )
    
    # Combine all correctness columns for a final status
    df['is_correct'] = df['initial_correctness'].fillna(df['post_hint_correctness']).fillna(df['revisit_correctness'])

    # Create a clean, numeric attempt column to handle revisits
    def clean_attempt(attempt):
        if isinstance(attempt, str) and 'revisit_' in attempt:
            try:
                return 2 + int(attempt.split('_')[1])
            except (ValueError, IndexError):
                return 3
        return pd.to_numeric(attempt, errors='coerce')
    df['attempt_numeric'] = df['attempt'].apply(clean_attempt)
    
    # Calculate mastery gain only between the final attempts of questions
    df = df.sort_values(by=['user_id', 'timestamp'])
    df['mastery_filled'] = df['initial_mastery'].fillna(df['post_hint_mastery']).fillna(df['revisit_mastery'])
    
    final_attempts = df.loc[df.groupby(['user_id', 'question_number'])['timestamp'].idxmax()].copy()
    final_attempts.sort_values(by=['user_id', 'timestamp'], inplace=True)
    final_attempts['previous_mastery'] = final_attempts.groupby('user_id')['mastery_filled'].shift(1)
    final_attempts['mastery_gain'] = final_attempts['mastery_filled'] - final_attempts['previous_mastery']
    
    df = df.merge(
        final_attempts[['interaction_id', 'mastery_gain']],
        on='interaction_id',
        how='left'
    )
    
    print("Data preprocessing complete.")
    return df

# --- Main Analysis Function ---
def analyze(df: pd.DataFrame):
    """Runs all analyses and generates plots."""
    if df.empty:
        return

    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    # --- Analysis 1: Does the Tutor Help Students Learn? ---
    print("\n" + "="*20 + " Analysis 1: Learning Effectiveness " + "="*20)
    
    learning_metrics = df.groupby(['experiment_name', 'persona_name']).agg(
        avg_mastery_gain=('mastery_gain', 'mean'),
        first_attempt_correctness=('is_first_attempt_correct', 'mean'),
        final_correctness=('is_correct', 'mean')
    ).reset_index()
    
    print("\n--- Key Metrics ---")
    print(learning_metrics.to_string())

    control_gains = df[df['experiment_name'] == 'Control Group (No Hints)']['mastery_gain'].dropna()
    treatment_gains = df[df['experiment_name'] == 'Treatment Group (Full Adaptive System)']['mastery_gain'].dropna()
    
    if not control_gains.empty and not treatment_gains.empty:
        t_stat, p_value = stats.ttest_ind(control_gains, treatment_gains, equal_var=False)
        print(f"\n--- Statistical Significance (Mastery Gain) ---")
        print(f"T-test between Control and Full Adaptive Group:")
        print(f"  T-statistic: {t_stat:.4f}")
        print(f"  P-value: {p_value:.4f}")
        if p_value < 0.05:
            print("  Result: The difference in mastery gain is statistically significant.")
        else:
            print("  Result: The difference in mastery gain is not statistically significant.")

    plt.figure(figsize=(12, 7))
    sns.barplot(data=learning_metrics, x='persona_name', y='avg_mastery_gain', hue='experiment_name')
    plt.title('Average BKT Mastery Gain per Question')
    plt.ylabel('Average Mastery Gain')
    plt.xlabel('Persona')
    plt.xticks(rotation=15)
    plt.tight_layout()
    plot_path = os.path.join(PLOTS_DIR, "1a_avg_mastery_gain.png")
    plt.savefig(plot_path)
    print(f"\nSaved plot: {plot_path}")
    plt.close()

    mastery_trajectory_df = df.dropna(subset=['mastery_filled'], how='all').copy()
    mastery_trajectory_df.loc[:, 'mastery_level'] = mastery_trajectory_df['mastery_filled']
    
    plt.figure(figsize=(14, 8))
    sns.lineplot(data=mastery_trajectory_df, x='question_number', y='mastery_level', hue='experiment_name', style='persona_name', marker='o')
    plt.title('Mastery Trajectory Over Session')
    plt.ylabel('BKT Mastery Level')
    plt.xlabel('Question Number')
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plot_path = os.path.join(PLOTS_DIR, "1b_mastery_trajectory.png")
    plt.savefig(plot_path)
    print(f"Saved plot: {plot_path}")
    plt.close()

    # --- Analysis 1.5: Learning Efficiency ---
    print("\n" + "="*20 + " Analysis 1.5: Learning Efficiency " + "="*20)
    
    df['attempts_to_correct'] = df.where(df['is_correct']).groupby(['user_id', 'question_number'])['attempt_numeric'].transform('min')
    attempts_df = df.dropna(subset=['attempts_to_correct']).drop_duplicates(subset=['user_id', 'question_number'])
    
    efficiency_metrics = attempts_df.groupby(['experiment_name', 'persona_name']).agg(
        avg_attempts_to_correct=('attempts_to_correct', 'mean')
    ).reset_index()

    print("\n--- Key Metrics ---")
    print(efficiency_metrics.to_string())

    plt.figure(figsize=(12, 7))
    sns.barplot(data=efficiency_metrics, x='persona_name', y='avg_attempts_to_correct', hue='experiment_name')
    plt.title('Average Attempts to Reach Correct Answer')
    plt.ylabel('Average Number of Attempts')
    plt.xlabel('Persona')
    plt.xticks(rotation=15)
    plt.tight_layout()
    plot_path = os.path.join(PLOTS_DIR, "1c_avg_attempts_to_correct.png")
    plt.savefig(plot_path)
    print(f"\nSaved plot: {plot_path}")
    plt.close()

    # --- NEW: Analysis 1.B: Skill Acquisition Over Time ---
    print("\n" + "="*20 + " Analysis 1.B: Skill Acquisition " + "="*20)
    
    # Determine the encounter number for each skill for each user
    df['skill_encounter'] = df.groupby(['user_id', 'skill_id']).cumcount() + 1
    
    # Calculate correctness on first attempt for each encounter
    skill_acquisition_metrics = df[df['attempt'] == 1].groupby(['experiment_name', 'persona_name', 'skill_encounter']).agg(
        first_attempt_correctness=('is_first_attempt_correct', 'mean')
    ).reset_index()

    print("\n--- Key Metrics ---")
    print(skill_acquisition_metrics.to_string())

    # Plot: Skill Acquisition
    plt.figure(figsize=(14, 8))
    sns.lineplot(data=skill_acquisition_metrics, x='skill_encounter', y='first_attempt_correctness', hue='experiment_name', style='persona_name', marker='o')
    plt.title('Skill Acquisition: First-Attempt Performance Over Time')
    plt.ylabel('First-Attempt Correctness (%)')
    plt.xlabel('Skill Encounter Number (e.g., 1st, 2nd, 3rd question of that skill)')
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plot_path = os.path.join(PLOTS_DIR, "1d_skill_acquisition.png")
    plt.savefig(plot_path)
    print(f"\nSaved plot: {plot_path}")
    plt.close()


    # --- Analysis 2: Do Hints Lead to Correct Answers? ---
    print("\n" + "="*20 + " Analysis 2: Hint Effectiveness " + "="*20)
    
    hint_opportunities = df[
        (df['attempt'] == 1) & (df['is_first_attempt_correct'] == False) &
        (df['experiment_name'] != 'Control Group (No Hints)')
    ].copy()
    
    second_attempts = df[df['attempt'] == 2]
    hint_opportunities = hint_opportunities.merge(
        second_attempts[['user_id', 'question_number', 'post_hint_correctness']],
        on=['user_id', 'question_number'],
        how='left'
    )
    
    if 'post_hint_correctness' not in hint_opportunities.columns:
        hint_opportunities['post_hint_correctness'] = False
    hint_opportunities['post_hint_correctness'] = hint_opportunities['post_hint_correctness'].fillna(False)

    hint_success_rate = hint_opportunities.groupby(['experiment_name', 'persona_name']).agg(
        hint_success_rate=('post_hint_correctness', 'mean')
    ).reset_index()
    
    print("\n--- Key Metrics ---")
    print(hint_success_rate.to_string())

    plt.figure(figsize=(12, 7))
    sns.barplot(data=hint_success_rate, x='persona_name', y='hint_success_rate', hue='experiment_name')
    plt.title('Hint Success Rate (Correct on 2nd Try After Failing 1st)')
    plt.ylabel('Success Rate (%)')
    plt.xlabel('Persona')
    plt.xticks(rotation=15)
    plt.tight_layout()
    plot_path = os.path.join(PLOTS_DIR, "2a_hint_success_rate.png")
    plt.savefig(plot_path)
    print(f"\nSaved plot: {plot_path}")
    plt.close()

    # --- Analysis 3: Is the Proactive Intervention System Effective? ---
    print("\n" + "="*20 + " Analysis 3: Proactive Intervention " + "="*20)
    
    proactive_df = df[
        (df['experiment_name'] == 'Treatment Group (Full Adaptive System)') &
        (df['attempt'] == 1)
    ].copy()

    if not proactive_df.empty:
        def get_intervention_status(row):
            if not row['proactive_check_result']:
                return 'Not Triggered'
            elif pd.notna(row['hint_style_used']):
                return 'Accepted'
            else:
                return 'Ignored'
        proactive_df['intervention_status'] = proactive_df.apply(get_intervention_status, axis=1)

        intervention_fired = proactive_df[proactive_df['proactive_check_result'] == True]
        precision = 1 - intervention_fired['is_first_attempt_correct'].mean() if not intervention_fired.empty else 0
        
        struggle_corr = proactive_df.groupby('intervention_status')['is_first_attempt_correct'].apply(lambda x: 1 - x.mean()).reset_index()
        struggle_corr.rename(columns={'is_first_attempt_correct': 'failure_rate'}, inplace=True)

        print("\n--- Key Metrics ---")
        print(f"Intervention Precision (How often an intervention correctly predicted failure): {precision:.2%}")
        print("\nStruggle Correlation (Failure rate based on intervention status):")
        print(struggle_corr.to_string())

        plt.figure(figsize=(10, 6))
        sns.barplot(data=struggle_corr, x='intervention_status', y='failure_rate', order=['Not Triggered', 'Ignored', 'Accepted'])
        plt.title('First-Attempt Failure Rate vs. Proactive Intervention Status')
        plt.ylabel('Failure Rate (%)')
        plt.xlabel('Intervention Status')
        plt.tight_layout()
        plot_path = os.path.join(PLOTS_DIR, "3a_proactive_struggle_correlation.png")
        plt.savefig(plot_path)
        print(f"\nSaved plot: {plot_path}")
        plt.close()
    else:
        print("No proactive intervention data to analyze.")

    # --- Analysis 4: Does the System Learn and Adapt to the User? ---
    print("\n" + "="*20 + " Analysis 4: System Adaptation " + "="*20)

    adaptive_df = df[
        (df['experiment_name'].str.contains('Treatment')) &
        (df['hint_style_used'].notna())
    ].copy()

    if not adaptive_df.empty:
        style_effectiveness = adaptive_df.groupby(['persona_name', 'hint_style_used']).agg(
            avg_rating=('feedback_rating', 'mean'),
            success_rate=('post_hint_correctness', 'mean'),
            usage_count=('interaction_id', 'count')
        ).reset_index()

        print("\n--- Hint Style Effectiveness & Usage ---")
        print(style_effectiveness.to_string())

        plt.figure(figsize=(14, 8))
        sns.countplot(data=adaptive_df, x='hint_style_used', hue='persona_name')
        plt.title('Frequency of Hint Style Usage per Persona')
        plt.ylabel('Number of Times Used')
        plt.xlabel('Hint Style')
        plt.xticks(rotation=15)
        plt.tight_layout()
        plot_path = os.path.join(PLOTS_DIR, "4a_hint_style_usage.png")
        plt.savefig(plot_path)
        print(f"\nSaved plot: {plot_path}")
        plt.close()

        for persona in adaptive_df['persona_name'].unique():
            persona_df = style_effectiveness[style_effectiveness['persona_name'] == persona]
            plt.figure(figsize=(10, 6))
            sns.scatterplot(data=persona_df, x='success_rate', y='usage_count', size='avg_rating', hue='hint_style_used', sizes=(100, 1000), legend=False)
            plt.title(f'Hint Effectiveness vs. Usage for {persona}')
            plt.xlabel('Hint Success Rate (%)')
            plt.ylabel('Usage Count')
            for i, row in persona_df.iterrows():
                plt.text(row['success_rate'] + 0.01, row['usage_count'], row['hint_style_used'])
            plt.grid(True)
            plt.tight_layout()
            plot_path = os.path.join(PLOTS_DIR, f"4b_effectiveness_vs_usage_{persona.replace(' ', '_')}.png")
            plt.savefig(plot_path)
            print(f"Saved plot: {plot_path}")
            plt.close()
    else:
        print("No adaptive data with hint styles found to analyze.")

    # --- NEW: Analysis 5: Student Behavior ---
    print("\n" + "="*20 + " Analysis 5: Simulated Student Behavior " + "="*20)

    behavioral_metrics = df.groupby(['experiment_name', 'persona_name']).apply(
        lambda x: pd.Series({
            'skip_rate': x[x['attempt'] == 1]['skipped'].mean(),
            'manual_hint_request_rate': x[(x['attempt'] > 1) & (x['hint_style_used'].notna())].shape[0] / x[x['attempt'] == 1]['initial_correctness'].eq(False).sum(),
            'proactive_hint_acceptance_rate': x[x['proactive_check_result'] == True]['hint_style_used'].notna().mean()
        })
    ).reset_index()

    print("\n--- Key Metrics ---")
    print(behavioral_metrics.to_string())

    # Plot: Behavioral Metrics
    fig, axes = plt.subplots(1, 3, figsize=(22, 7))
    fig.suptitle('Analysis of Simulated Student Behavior')

    sns.barplot(ax=axes[0], data=behavioral_metrics, x='persona_name', y='skip_rate', hue='experiment_name')
    axes[0].set_title('First-Attempt Skip Rate')
    axes[0].set_ylabel('Skip Rate (%)')
    axes[0].tick_params(axis='x', rotation=15)

    sns.barplot(ax=axes[1], data=behavioral_metrics, x='persona_name', y='manual_hint_request_rate', hue='experiment_name')
    axes[1].set_title('Manual Hint Request Rate (after failure)')
    axes[1].set_ylabel('Hint Request Rate (%)')
    axes[1].tick_params(axis='x', rotation=15)

    sns.barplot(ax=axes[2], data=behavioral_metrics, x='persona_name', y='proactive_hint_acceptance_rate', hue='experiment_name')
    axes[2].set_title('Proactive Hint Acceptance Rate')
    axes[2].set_ylabel('Acceptance Rate (%)')
    axes[2].tick_params(axis='x', rotation=15)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plot_path = os.path.join(PLOTS_DIR, "5a_student_behavior_summary.png")
    plt.savefig(plot_path)
    print(f"\nSaved plot: {plot_path}")
    plt.close()
    # --- END NEW ---

def main():
    """Main entry point for the analysis script."""
    parser = argparse.ArgumentParser(description="Analyze AI Tutor evaluation results.")
    parser.add_argument(
        "--results_dir", 
        type=str, 
        default=RESULTS_DIR, 
        help="Directory containing the simulation result CSV files."
    )
    args = parser.parse_args()

    df = load_and_preprocess_data(args.results_dir)
    analyze(df)

if __name__ == "__main__":
    main()