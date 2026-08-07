"""Async admin UI package (see ADMIN_UI_PORT_PLAN.md).

Phase 1 lives here: app/admin/queries.py is the async data layer that
replaces streamlit_app/queries.py and streamlit_app/admin_ops.py.

Phase 2 (the router, app/endpoints/admin_ui.py) depends on this package but
lives under app/endpoints/ to match the existing router layout, not here.
"""