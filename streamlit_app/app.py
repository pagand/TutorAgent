# streamlit_app/app.py
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.config import settings
from streamlit_app.queries import (
    get_all_user_ids, 
    get_user_profile, 
    get_skill_mastery, 
    get_interaction_history,
    reset_user_progress,
    delete_user,
    load_questions
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

# --- Load Data ---
# Load questions once and cache the result
load_questions()

# --- Main App ---
st.title("AI Tutor Admin Dashboard")

# --- Display Success/Error Messages from Session State ---
if 'success_message' in st.session_state:
    st.success(st.session_state.success_message, icon="✅")
    del st.session_state.success_message # Clear the message after displaying

db = SessionLocal()

# --- Sidebar for User Selection ---
st.sidebar.title("User Selection")
try:
    user_ids = get_all_user_ids(db)
except Exception as e:
    st.sidebar.error(f"Failed to load users: {e}")
    user_ids = []

selected_user_id = st.sidebar.selectbox(
    "Select a User ID to view their data:",
    options=user_ids,
    index=0 if user_ids else None,
    key='user_selector' # Add a key to prevent state issues
)

if not selected_user_id:
    st.warning("No users found in the database. Please interact with the tutor to create users.")
    st.stop()

st.header(f"Displaying data for User: `{selected_user_id}`")

# --- Main content area with tabs ---
profile_tab, mastery_tab, history_tab, admin_tab = st.tabs([
    "User Profile", "Skill Mastery", "Interaction History", "Admin Actions"
])

with profile_tab:
    st.subheader("User Profile Details")
    profile_data = get_user_profile(db, selected_user_id)
    if profile_data:
        st.json(profile_data, expanded=True)
    else:
        st.warning("Could not retrieve profile for this user.")

with mastery_tab:
    st.subheader("Skill Mastery Levels")
    mastery_df = get_skill_mastery(db, selected_user_id)
    if not mastery_df.empty:
        st.dataframe(mastery_df, width='stretch', hide_index=True)
    else:
        st.info("No skill mastery records found for this user.")

with history_tab:
    st.subheader("Detailed Interaction History")
    history_df = get_interaction_history(db, selected_user_id)
    if not history_df.empty:
        st.dataframe(history_df, width='stretch', hide_index=True)
    else:
        st.info("No interaction history found for this user.")

with admin_tab:
    st.subheader("Danger Zone")
    
    st.warning("These actions are irreversible. Please proceed with caution.", icon="⚠️")

    # --- Reset User Progress ---
    st.markdown("---")
    st.markdown("### Reset User Progress")
    st.markdown("This will delete all of a user's interaction history and skill mastery, but keep the user account.")
    if st.button("Reset Progress", type="secondary"):
        try:
            reset_user_progress(db, selected_user_id)
            # Set the success message in session state before rerunning
            st.session_state.success_message = f"Successfully reset progress for user `{selected_user_id}`."
            st.rerun()
        except Exception as e:
            st.error(f"An error occurred while resetting the user: {e}")

    # --- Delete User ---
    st.markdown("---")
    st.markdown("### Delete User")
    st.markdown("This will permanently delete the user and all of their associated data.")
    if st.button("Delete User", type="primary"):
        try:
            # Store the user ID before it's deleted to use in the message
            deleted_user_id = selected_user_id
            delete_user(db, deleted_user_id)
            # Set the success message in session state before rerunning
            st.session_state.success_message = f"Successfully deleted user `{deleted_user_id}`."
            st.rerun()
        except Exception as e:
            st.error(f"An error occurred while deleting the user: {e}")

db.close()
