import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from auth.router import router as auth_router
from config import settings
from database import close_db, create_all_tables
from routers import (
    aptitude,
    bot,
    dashboard,
    dsa,
    hr,
    interviews,
    practice,
    reports,
    realtime,
    resume,
    roadmaps,
    settings as settings_router,
    stream,
    technical,
)
from services.chroma import init_chroma
from services.file_service import cleanup_expired_resume_uploads, resume_upload_cleanup_loop
from services.repositories.manager import persistence_manager
from services.runtime_health import provider_health_snapshot, runtime_health_snapshot
from services.store import store
from services.workflow_queue import workflow_queue_health


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interviewos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    await run_in_threadpool(persistence_manager.hydrate_store, store)
    init_chroma()
    await cleanup_expired_resume_uploads()
    resume_cleanup_task = asyncio.create_task(resume_upload_cleanup_loop())
    try:
        yield
    finally:
        resume_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await resume_cleanup_task
        await close_db()
        await run_in_threadpool(persistence_manager.close)


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

LOCAL_DEV_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1):\d+$"


def configured_frontend_origins() -> list[str]:
    configured = [settings.frontend_url, *settings.frontend_urls.split(",")]
    origins: list[str] = []
    for origin in configured:
        normalized = origin.strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        *configured_frontend_origins(),
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=LOCAL_DEV_ORIGIN_REGEX,
    allow_credentials=True,
    allow_private_network=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logger(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "%s %s %s %.2fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.middleware("http")
async def private_network_cors(request: Request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled backend error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": settings.app_env,
        "db": "configured" if settings.database_url else "development-store",
        "persistence": "postgres" if persistence_manager.enabled else "development-store",
        "chroma": "configured",
        "runtime": runtime_health_snapshot(),
        "providers": provider_health_snapshot(),
        "frontendOrigins": configured_frontend_origins(),
    }


@app.get("/api/health/workflow")
async def workflow_health():
    return await workflow_queue_health()


# Auth is mounted in both places because the backend prompt uses `/auth/*`,
# while the frontend architecture doc reserves `/api/auth/*`.
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
app.include_router(dsa.router, prefix="/api/dsa", tags=["dsa"])
app.include_router(aptitude.router, prefix="/api/aptitude", tags=["aptitude"])
app.include_router(technical.router, prefix="/api/technical", tags=["technical"])
app.include_router(hr.router, prefix="/api/hr", tags=["hr"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(roadmaps.router, prefix="/api/roadmaps", tags=["roadmaps"])
app.include_router(resume.router, prefix="/api/resume", tags=["resume"])
app.include_router(bot.router, prefix="/api/bot", tags=["bot"])
app.include_router(practice.router, prefix="/api/practice", tags=["practice"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(stream.router, prefix="/api/stream", tags=["stream"])
app.include_router(realtime.router, prefix="/api/realtime", tags=["realtime"])
