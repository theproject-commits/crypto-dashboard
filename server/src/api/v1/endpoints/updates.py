from fastapi import APIRouter, Depends

from ....security import require_auth
from ....services.daily_update import DailyUpdateScheduler

router = APIRouter()


def _scheduler() -> DailyUpdateScheduler:
    from ....main import daily_update_scheduler

    return daily_update_scheduler


@router.get("/status")
def get_update_status(_user: str = Depends(require_auth)):
    scheduler = _scheduler()
    return scheduler.get_status()


@router.post("/run")
def run_update_now(_user: str = Depends(require_auth)):
    scheduler = _scheduler()
    started = scheduler.trigger_async_update()
    return {
        "started": started,
        "message": "Update started" if started else "Update already running",
        "status": scheduler.get_status(),
    }
