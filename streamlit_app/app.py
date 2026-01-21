# streamlit_app/app.py
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os
import pandas as pd

# Add project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.config import settings
from streamlit_app.queries import (
    get_all_user_ids, 
    get_user_profile, 
    get_skill_mastery, 
    get_interaction_history,
    get_raw_interaction_history,
    get_skill_mastery_trajectory,
    get_user_kpis,
    reset_user_progress,
    delete_user,
    QUESTIONS_DF # Import the loaded questions dataframe
)

# --- Page Config ---
st.set_page_config(layout="wide", page_title="AI Tutor Admin Dashboard")

# --- Database Connection ---
@st.cache_resource
def get_db_engine():
    """Creates a cached SQLAlchemy engine."""
    db_url = settings.database_url
    sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return create_engine(sync_db_url)

engine = get_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Main App ---
st.title("AI Tutor Admin Dashboard")

# --- Display Success/Error Messages from Session State ---
if 'success_message' in st.session_state:
    st.success(st.session_state.success_message, icon="✅")
    del st.session_state.success_message

db = SessionLocal()

# --- Sidebar for User Selection ---
st.sidebar.title("Select View")
view_options = ["System-Wide Analytics"] + get_all_user_ids(db)
selected_view = st.sidebar.selectbox(
    "Select a User ID or System-Wide Analytics:",
    options=view_options,
    index=0 if view_options else None,
    key='view_selector'
)

# --- Main App Logic ---
if selected_view == "System-Wide Analytics":
    st.header("System-Wide Analytics")
    st.info("System-wide analytics will be developed in a future iteration.")
    # Placeholder for future system-wide queries and plots

elif selected_view:
    selected_user_id = selected_view
    st.header(f"Displaying data for User: `{selected_user_id}`")

    # --- Main content area with tabs for individual user ---
    profile_tab, mastery_tab, history_tab, hint_analysis_tab, admin_tab = st.tabs([
        "User Profile & KPIs", "Skill Mastery", "Interaction History", "Hint & Intervention Analysis", "Admin Actions"
    ])

    with profile_tab:
        st.subheader("Key Performance Indicators")
        kpis = get_user_kpis(db, selected_user_id)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Overall Correctness", f"{kpis['overall_correctness']:.1%}")
        col2.metric("Avg. Attempts to Correct", f"{kpis['avg_attempts_to_correct']:.2f}")
        col3.metric("Total Hints Received", f"{kpis['total_hints']}")
        col4.metric("Average Hint Rating", f"{kpis['avg_hint_rating']}" if isinstance(kpis['avg_hint_rating'], str) else f"{kpis['avg_hint_rating']:.2f}")

        st.markdown("---")
        st.subheader("Raw User Profile Data")
        profile_data = get_user_profile(db, selected_user_id)
        if profile_data:
            st.json(profile_data, expanded=True)
        else:
            st.warning("Could not retrieve profile for this user.")

    with mastery_tab:
        st.subheader("Skill Mastery Trajectory")
        st.markdown("This chart shows the evolution of the user's BKT mastery score for each skill over time. Each point on the x-axis represents a single interaction (e.g., an answer submission).")
        
        # Use the new trajectory query
        trajectory_df = get_skill_mastery_trajectory(db, selected_user_id)

        if not trajectory_df.empty:
            # Clean column names for Streamlit plotting by removing special characters
            trajectory_df.columns = trajectory_df.columns.str.replace(r'\[|\]', '', regex=True)
            st.line_chart(trajectory_df)
            
            st.markdown("---")
            st.subheader("Current Skill Mastery Levels")
            mastery_df = get_skill_mastery(db, selected_user_id)
            if not mastery_df.empty:
                mastery_df.set_index('skill_id', inplace=True)
                st.bar_chart(mastery_df['mastery_level'])
                with st.expander("View Raw Data"):
                    st.dataframe(mastery_df)
            else:
                st.info("No final skill mastery records found for this user.")
        else:
            st.info("No interaction history found to build a mastery trajectory.")

    with history_tab:
        st.subheader("Detailed Interaction History (Raw Data)")
        history_df = get_interaction_history(db, selected_user_id)
        if not history_df.empty:
            st.dataframe(history_df, width='content')
        else:
            st.info("No interaction history found for this user.")

    with hint_analysis_tab:
        st.subheader("Analysis of Hints and Interventions")
        history_df = get_interaction_history(db, selected_user_id)
        if not history_df.empty:
            # Group interactions by question to show the full loop
            for q_id, group in history_df.groupby('question_id'):
                question_text = group['question'].iloc[0]
                status = "Correct" if group['is_correct'].any() else "Incorrect"
                
                expander_title = f"Q{q_id}: {question_text[:60]}... (Final Status: {status})"
                with st.expander(expander_title):
                    # Display each attempt for that question
                    for _, row in group.sort_values(by='timestamp').iterrows():
                        st.markdown(f"---")
                        st.markdown(f"**Attempt at {row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}**")
                        answer_display = f"`{row['user_answer']}`" if pd.notna(row['user_answer']) else "**Skipped**"
                        st.markdown(f"**User's Action:** {answer_display} (`{'Correct' if row['is_correct'] else 'Incorrect'}`)")
                        st.markdown(f"**BKT Change:** `{row['bkt_change']:.4f}`" if pd.notna(row['bkt_change']) else "**BKT Change:** `N/A`")

                        if row['hint_shown']:
                            st.markdown("##### Hint Details for this Attempt")
                            st.info(f"**Style:** `{row['hint_style_used']}`")
                            st.text_area("Hint Text", value=row['hint_text'], height=150, disabled=True, key=f"hint_{row['timestamp']}")
                            st.success(f"**User Feedback:** `{row['user_feedback_rating']}/5`" if pd.notna(row['user_feedback_rating']) else "**User Feedback:** `Not provided`")
                        else:
                            st.info("No hint was shown for this attempt.")
        else:
            st.info("No interaction history to analyze.")

    with admin_tab:
        st.subheader("Danger Zone")
        
        st.warning("These actions are irreversible. Please proceed with caution.", icon="⚠️")

        st.markdown("---")
        st.markdown("### Reset User Progress")
        st.markdown("This will delete all of a user's interaction history and skill mastery, but keep the user account.")
        if st.button("Reset Progress", type="secondary"):
            try:
                reset_user_progress(db, selected_user_id)
                st.session_state.success_message = f"Successfully reset progress for user `{selected_user_id}`."
                st.rerun()
            except Exception as e:
                st.error(f"An error occurred while resetting the user: {e}")

        st.markdown("---")
        st.markdown("### Delete User")
        st.markdown("This will permanently delete the user and all of their associated data.")
        if st.button("Delete User", type="primary"):
            try:
                deleted_user_id = selected_user_id
                delete_user(db, deleted_user_id)
                st.session_state.success_message = f"Successfully deleted user `{deleted_user_id}`."
                st.rerun()
            except Exception as e:
                st.error(f"An error occurred while deleting the user: {e}")

else:
    st.warning("No users found in the database. Please interact with the tutor to create users.")
    st.stop()

db.close()