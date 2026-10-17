"""CRUD services. Plain functions `fn(session, ...)`; they flush but never commit, the caller
owns the transaction (see app.db.session.session_scope). Import the modules, not the functions:

    from app.services import companies, profiles
"""
