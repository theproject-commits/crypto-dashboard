from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timezone
from pathlib import Path

from .database import engine
from . import models
from .services.daily_update import DailyUpdateScheduler

app = FastAPI(
    title="TentacleLab API",
    description="API for fetching crypto data and eventually predictions.",
    version="0.1.0",
)

origins = [
    "http://localhost",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://[::1]:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://([a-zA-Z0-9\.\-\[\]:]+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

daily_update_scheduler = DailyUpdateScheduler()


@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)
    daily_update_scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    daily_update_scheduler.stop()

@app.get("/")
async def root():
    return {"message": "Welcome to the TentacleLab API!"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scheduler": {
            "running": daily_update_scheduler.running,
            "last_success_at": daily_update_scheduler.last_success_at,
            "last_error": daily_update_scheduler.last_error,
            "last_run_duration_seconds": daily_update_scheduler.last_run_duration_seconds,
        },
    }

# TODO: Add API endpoints for cryptocurrencies, price history, etc.
from .api.v1.endpoints import auth, cryptos, settings, updates
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(cryptos.router, prefix="/api/v1/cryptos", tags=["cryptos"])
app.include_router(updates.router, prefix="/api/v1/updates", tags=["updates"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])

frontend_dist = Path(__file__).resolve().parents[2] / "client" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
