from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Union

from fastapi import FastAPI
from fastapi.responses import FileResponse

from delivery_analysis.store.db import connect, current_version, migrate
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.store.upsert import unmapped_identities

STATIC_DIR = Path(__file__).parent / "static"
PAGES = ["/", "/rankings", "/selection", "/teams", "/sources", "/settings", "/ask"]


def create_app(db_path: Union[str, Path]) -> FastAPI:
    app = FastAPI(title="Delivery analytics")

    setup = connect(db_path)
    try:
        migrate(setup)
    finally:
        setup.close()

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        conn = connect(db_path)
        try:
            return {
                "schema_version": current_version(conn),
                "sources": list_sync_states(conn),
                "unmapped_identities": len(unmapped_identities(conn)),
            }
        finally:
            conn.close()

    def shell() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    for page in PAGES:
        app.add_api_route(page, shell, methods=["GET"], include_in_schema=False)

    return app
