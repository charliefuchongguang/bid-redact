from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, files, rules, system
from app.core.config import PROJECT_ROOT, settings
from app.services.worker import start_worker, stop_worker


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.init_db import init_db

    init_db()
    start_worker()
    try:
        yield
    finally:
        stop_worker()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(rules.router, prefix="/api")
app.include_router(system.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": "0.1.0"}


DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = DIST_DIR / "assets"

if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/")
def root():
    index = DIST_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"service": settings.app_name, "docs": "/docs", "health": "/api/health"}


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if DIST_DIR.is_dir():
        root_dir = DIST_DIR.resolve()
        target = (DIST_DIR / full_path).resolve()
        if target.is_file() and target.is_relative_to(root_dir):
            return FileResponse(target)
        index = DIST_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    return JSONResponse({"detail": "Not Found"}, status_code=404)