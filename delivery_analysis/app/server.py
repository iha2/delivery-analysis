from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from delivery_analysis.app.api import build_router
from delivery_analysis.app.context import AppContext, _utc_now
from delivery_analysis.app.refresh import RefreshWorker, sync_runner
from delivery_analysis.settings import Settings
from delivery_analysis.store.db import connect, current_version, migrate
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.store.upsert import unmapped_identities

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
PAGES: Dict[str, str] = {
    "/": "dashboard.html",
    "/rankings": "rankings.html",
    "/person": "person.html",
    "/selection": "selection.html",
    "/teams": "teams.html",
    "/sources": "sources.html",
    "/settings": "settings.html",
    "/ask": "ask.html",
}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _host_name(value: str) -> str:
    value = value.strip()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def create_app(
    db_path: Union[str, Path],
    *,
    settings: Optional[Settings] = None,
    environ: Optional[Mapping[str, str]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    worker: Optional[RefreshWorker] = None,
    clock: Optional[Callable[[], datetime]] = None,
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
) -> FastAPI:
    path = Path(db_path)
    settings = settings or Settings(db_path=path)
    env = dict(environ or {})
    worker = worker or RefreshWorker(sync_runner(path, settings, env, transport))
    ctx = AppContext(path, settings, env, worker, transport, clock or _utc_now)
    app = FastAPI(title="Delivery analytics")
    allowed = set(allowed_hosts)

    setup = connect(path)
    try:
        migrate(setup)
    finally:
        setup.close()

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        if _host_name(request.headers.get("host", "")) not in allowed:
            return JSONResponse({"detail": "This app only answers on localhost."}, status_code=403)
        origin = request.headers.get("origin")
        if request.method in WRITE_METHODS and origin and (urlparse(origin).hostname or "") not in allowed:
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        conn = connect(path)
        try:
            return {
                "schema_version": current_version(conn),
                "sources": list_sync_states(conn),
                "unmapped_identities": len(unmapped_identities(conn)),
            }
        finally:
            conn.close()

    app.include_router(build_router(ctx))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def page(filename: str) -> Callable[[], FileResponse]:
        def serve() -> FileResponse:
            return FileResponse(STATIC_DIR / filename)
        return serve

    for route, filename in PAGES.items():
        app.add_api_route(route, page(filename), methods=["GET"], include_in_schema=False)
    app.state.context = ctx
    return app
