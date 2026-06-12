"""
Backward-compatible API entrypoint.

Run:  uvicorn api_app:app --reload

Implementation lives in the ``api`` package (routers, schemas, helpers).
"""

from api.app import app, create_app

__all__ = ["app", "create_app"]
