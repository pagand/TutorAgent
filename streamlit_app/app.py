# streamlit_app/app.py
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys, os
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.config import settings
from streamlit_app.queries import (
    get_all_user_ids, get_all_users_summary,
    get_user_profile, get_skill_mastery, get_interaction_history,
    get_raw_interaction_history, get_skill_mastery_trajectory, get_user_kpis,
    get_all_interaction_logs, get_chat_logs, get_intervention_logs, get_action_logs,
    reset_user_progress, delete_user, QUESTIONS_DF,
)

st.set_page_config(layout="wide", page_title="AI Tutor Admin Dashboard")

@st.cache_resource
def get_db_engine():
    db_url = settings.database_url
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return create_engine(sync_url)

engine = get_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

st.title("AI Tutor Admin Dashboard")

if 'success_message' in st.session_state:
    st.success(st.session_state.success_message, icon="✅")
    del st.session_state.success_message

db = SessionLocal()

# Sidebar
st.sidebar.title("Select View")
all_user_ids = get_all_user_ids(db)
VIEW_SYSTEM = "📊 System-Wide Analytics"
VIEW_EXPORT = "⬇️ Export Data"
view_options = [VIEW_SYSTEM, VIEW_EXPORT] + all_user_ids

selected_view = st.sidebar.selectbox(
    "Select a User ID or view:",
    options=view_options,
    index=0,
    key='view_selector'
)

# ─────────────────────────────────────────────
# SYSTEM-WIDE ANALYTICS
# ─────────────────────────────────────────────
if selected_view == VIEW_SYSTEM:
    st.header("System-Wide Analytics")

    users_df = get_all_users_summary(db)

    if users_df.empty:
        st.info("No users yet.")
    else:
        # Top-level KPI row
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Users", len(users_df))
        adaptive = (users_df['ab_group'] == 'adaptive').sum()
        free = (users_df['ab_group'] == 'free_choice').sum()
        col2.metric("Adaptive Group", adaptive)
        col3.metric("Free Choice Group", free)
        total_interactions = int(users_df['total_interactions'].sum())
        col4.metric("Total Interactions", total_interactions)

        st.markdown("---")

        # A/B group breakdown
        st.subheader("A/B Group Distribution")
        ab_counts = users_df['ab_group'].value_counts().reset_index()
        ab_counts.columns = ['group', 'count']
        st.bar_chart(ab_counts.set_index('group'))

        # Hint style breakdown (free_choice users)
        st.subheader("Hint Style Preferences (free_choice group)")
        fc_df = users_df[users_df['ab_group'] == 'free_choice']
        if not fc_df.empty:
            style_counts = fc_df['hint_style_pref'].value_counts().reset_index()
            style_counts.columns = ['style', 'count']
            st.bar_chart(style_counts.set_index('style'))
        else:
            st.info("No free_choice users yet.")

        st.markdown("---")

        # Per-user summary table
        st.subheader("All Users Summary")
        display_df = users_df.copy()
        display_df['created_at'] = display_df['created_at'].dt.strftime('%Y-%m-%d %H:%M')
        display_df['correctness'] = (
            display_df.apply(
                lambda r: f"{r['correct_answers']/r['total_interactions']:.0%}"
                if r['total_interactions'] > 0 else "—", axis=1
            )
        )
        cols_show = ['user_id', 'ab_group', 'hint_style_pref', 'created_at',
                     'total_interactions', 'correctness', 'hints_used', 'chat_messages']
        st.dataframe(display_df[[c for c in cols_show if c in display_df.columns]],
                     use_container_width=True)


# ─────────────────────────────────────────────
# EXPORT DATA
# ─────────────────────────────────────────────
elif selected_view == VIEW_EXPORT:
    st.header("Export Data")
    st.markdown("Filter and export any combination of logs as CSV.")

    with st.form("export_form"):
        col1, col2 = st.columns(2)

        with col1:
            user_scope = st.selectbox(
                "User scope",
                options=["All Users"] + all_user_ids,
                index=0,
            )
            log_type = st.selectbox(
                "Log type",
                options=["Interaction Logs", "Chat Logs", "Intervention Logs", "Action Logs"],
            )

        with col2:
            date_from = st.date_input("From date (optional)", value=None)
            date_to = st.date_input("To date (optional)", value=None)

        # Action type filter (only shown for relevant tables)
        action_type_filter = None
        if log_type == "Action Logs":
            action_types = [
                "— all —", "session_start", "session_complete", "timer_expired",
                "question_view", "question_navigate", "hint_request", "hint_display",
                "intervention_offered", "intervention_accepted", "intervention_rejected",
                "chat_message_sent", "answer_submit", "answer_skip",
                "profile_view", "preference_update",
            ]
            selected_action = st.selectbox("Action type filter", options=action_types)
            if selected_action != "— all —":
                action_type_filter = selected_action

        if log_type == "Interaction Logs":
            hint_only = st.checkbox("Only rows where hint was shown")
            correct_filter = st.selectbox("Correct filter", ["All", "Correct only", "Incorrect only"])
        else:
            hint_only = False
            correct_filter = "All"

        submitted = st.form_submit_button("Preview & Export")

    if submitted:
        selected_user = None if user_scope == "All Users" else user_scope

        # Fetch data
        if log_type == "Interaction Logs":
            df = get_all_interaction_logs(db, user_id=selected_user)
            if hint_only and not df.empty:
                df = df[df['hint_shown'] == True]
            if correct_filter == "Correct only" and not df.empty:
                df = df[df['is_correct'] == True]
            elif correct_filter == "Incorrect only" and not df.empty:
                df = df[df['is_correct'] == False]
        elif log_type == "Chat Logs":
            df = get_chat_logs(db, user_id=selected_user)
        elif log_type == "Intervention Logs":
            df = get_intervention_logs(db, user_id=selected_user)
        else:
            df = get_action_logs(db, user_id=selected_user, action_type=action_type_filter)

        # Date range filter
        if not df.empty and date_from:
            df = df[df['timestamp'].dt.date >= date_from]
        if not df.empty and date_to:
            df = df[df['timestamp'].dt.date <= date_to]

        if df.empty:
            st.warning("No data matches the selected filters.")
        else:
            # Field selector
            st.markdown(f"**{len(df):,} rows** match. Select fields to include in export:")
            all_cols = list(df.columns)
            selected_cols = st.multiselect(
                "Fields to export",
                options=all_cols,
                default=all_cols,
                key="export_cols",
            )
            if selected_cols:
                export_df = df[selected_cols]
                st.dataframe(export_df.head(100), use_container_width=True)
                if len(df) > 100:
                    st.caption(f"Preview shows first 100 of {len(df):,} rows. Full data in CSV.")

                filename = f"{log_type.lower().replace(' ', '_')}"
                if selected_user:
                    filename += f"_{selected_user}"
                filename += ".csv"

                st.download_button(
                    label=f"⬇️ Download {filename}",
                    data=export_df.to_csv(index=False).encode('utf-8'),
                    file_name=filename,
                    mime="text/csv",
                )
            else:
                st.warning("Select at least one field.")


# ─────────────────────────────────────────────
# INDIVIDUAL USER VIEW
# ─────────────────────────────────────────────
elif selected_view and selected_view in all_user_ids:
    selected_user_id = selected_view
    profile_data = get_user_profile(db, selected_user_id)
    prefs = profile_data.get('preferences', {}) or {}
    ab_group = prefs.get('ab_group', 'unknown')
    ab_badge = "🔵 Adaptive" if ab_group == "adaptive" else "🟢 Free Choice"

    st.header(f"User: `{selected_user_id}`")
    st.caption(f"A/B Group: **{ab_badge}** | Hint style: **{prefs.get('hint_style_preference', '—')}** | Intervention: **{prefs.get('intervention_preference', '—')}**")

    profile_tab, mastery_tab, history_tab, hint_tab, chat_tab, actions_tab, admin_tab = st.tabs([
        "KPIs & Profile", "Skill Mastery", "Interaction History",
        "Hints & Interventions", "Chat Log", "Action Log", "Admin"
    ])

    with profile_tab:
        st.subheader("Key Performance Indicators")
        kpis = get_user_kpis(db, selected_user_id)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall Correctness", f"{kpis['overall_correctness']:.1%}")
        c2.metric("Avg. Attempts to Correct", f"{kpis['avg_attempts_to_correct']:.2f}")
        c3.metric("Total Hints Received", kpis['total_hints'])
        avg_r = kpis['avg_hint_rating']
        c4.metric("Avg. Hint Rating", avg_r if isinstance(avg_r, str) else f"{avg_r:.2f}")
        st.markdown("---")
        st.subheader("Raw Profile Data")
        st.json(profile_data, expanded=True)

    with mastery_tab:
        st.subheader("Skill Mastery Trajectory")
        trajectory_df = get_skill_mastery_trajectory(db, selected_user_id)
        if not trajectory_df.empty:
            trajectory_df.columns = trajectory_df.columns.str.replace(r'\[|\]', '', regex=True)
            st.line_chart(trajectory_df)
            st.markdown("---")
            mastery_df = get_skill_mastery(db, selected_user_id)
            if not mastery_df.empty:
                mastery_df.set_index('skill_id', inplace=True)
                st.bar_chart(mastery_df['mastery_level'])
                with st.expander("Raw Data"):
                    st.dataframe(mastery_df)
        else:
            st.info("No interaction history to build trajectory.")

    with history_tab:
        st.subheader("Interaction History")
        history_df = get_interaction_history(db, selected_user_id)
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True)
            st.download_button(
                "⬇️ Download CSV",
                data=history_df.to_csv(index=False).encode('utf-8'),
                file_name=f"interactions_{selected_user_id}.csv",
                mime="text/csv",
            )
        else:
            st.info("No interaction history.")

    with hint_tab:
        st.subheader("Hints & Interventions")
        history_df = get_interaction_history(db, selected_user_id)
        if not history_df.empty:
            for q_id, group in history_df.groupby('question_id'):
                question_text = group['question'].iloc[0] if 'question' in group.columns and pd.notna(group['question'].iloc[0]) else f"Question {q_id}"
                status = "✓ Correct" if group['is_correct'].any() else "✗ Incorrect"
                title = f"Q{q_id}: {str(question_text)[:70]}… ({status})"
                with st.expander(title):
                    for _, row in group.sort_values('timestamp').iterrows():
                        st.markdown(f"**{row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}**")
                        ans = f"`{row['user_answer']}`" if pd.notna(row['user_answer']) else "**Skipped**"
                        st.markdown(f"Answer: {ans} — `{'✓ Correct' if row['is_correct'] else '✗ Incorrect'}`")
                        if pd.notna(row.get('bkt_change')):
                            st.markdown(f"BKT Δ: `{row['bkt_change']:.4f}`")
                        if row.get('hint_shown'):
                            st.info(f"Hint style: `{row['hint_style_used']}` | Rating: `{row['user_feedback_rating'] or '—'}/5`")
                            if pd.notna(row.get('hint_text')):
                                st.text_area("Hint text", value=row['hint_text'], height=100,
                                             disabled=True, key=f"ht_{q_id}_{row['timestamp']}")
                        st.markdown("---")
        else:
            st.info("No data.")

        st.subheader("Intervention Events")
        iv_df = get_intervention_logs(db, selected_user_id)
        if not iv_df.empty:
            iv_df['accepted_label'] = iv_df['accepted'].map({True: '✓ Accepted', False: '✗ Rejected', None: '— Offered'})
            st.dataframe(iv_df[['timestamp', 'question_number', 'time_on_question_ms',
                                 'mastery_at_trigger', 'accepted_label']], use_container_width=True)
        else:
            st.info("No intervention events logged.")

    with chat_tab:
        st.subheader("Chat Log")
        chat_df = get_chat_logs(db, selected_user_id)
        if not chat_df.empty:
            for _, row in chat_df.sort_values('timestamp').iterrows():
                with st.container():
                    st.markdown(f"**Q{row['question_number']} — {row['timestamp'].strftime('%H:%M:%S')}**")
                    st.markdown(f"🧑 **Student:** {row['user_message']}")
                    st.markdown(f"🤖 **Tutor:** {row['tutor_response']}")
                    st.markdown("---")
            st.download_button(
                "⬇️ Download Chat CSV",
                data=chat_df.to_csv(index=False).encode('utf-8'),
                file_name=f"chat_{selected_user_id}.csv",
                mime="text/csv",
            )
        else:
            st.info("No chat messages.")

    with actions_tab:
        st.subheader("Action Log")
        act_df = get_action_logs(db, selected_user_id)
        if not act_df.empty:
            action_filter = st.multiselect(
                "Filter by action type",
                options=sorted(act_df['action_type'].unique()),
                default=[],
                key="action_filter_user",
            )
            display_df = act_df[act_df['action_type'].isin(action_filter)] if action_filter else act_df
            st.dataframe(display_df[['timestamp', 'action_type', 'question_number', 'action_data']],
                         use_container_width=True)
        else:
            st.info("No action events logged yet.")

    with admin_tab:
        st.subheader("Danger Zone")
        st.warning("These actions are irreversible.", icon="⚠️")
        st.markdown("### Reset User Progress")
        st.markdown("Deletes all interaction history and skill mastery; keeps the user account.")
        if st.button("Reset Progress", type="secondary"):
            try:
                reset_user_progress(db, selected_user_id)
                st.session_state.success_message = f"Reset progress for `{selected_user_id}`."
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
        st.markdown("---")
        st.markdown("### Delete User")
        st.markdown("Permanently deletes the user and all data.")
        if st.button("Delete User", type="primary"):
            try:
                delete_user(db, selected_user_id)
                st.session_state.success_message = f"Deleted user `{selected_user_id}`."
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

else:
    st.warning("No users found in the database.")
    st.stop()

db.close()
