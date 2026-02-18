import json
import os
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, status

from .... import schemas
from ....security import require_auth

router = APIRouter()

_settings_lock = Lock()
_settings_path = Path(__file__).resolve().parents[4] / "runtime_settings.json"
_allowed_themes = {"light", "dark"}


def _get_env_default_theme() -> str:
    value = os.getenv("APP_THEME_DEFAULT", "light").strip().lower()
    return value if value in _allowed_themes else "light"


def _read_settings() -> dict:
    if not _settings_path.exists():
        return {}
    try:
        return json.loads(_settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_settings(data: dict) -> None:
    _settings_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


@router.get("/theme", response_model=schemas.ThemeSettingsResponse)
def get_theme_settings():
    with _settings_lock:
        data = _read_settings()
    theme = str(data.get("theme", _get_env_default_theme())).strip().lower()
    if theme not in _allowed_themes:
        theme = _get_env_default_theme()
    return {"theme": theme, "source": "file" if "theme" in data else "env_default"}


@router.put("/theme", response_model=schemas.ThemeSettingsResponse)
def update_theme_settings(
    payload: schemas.ThemeSettingsUpdateRequest, _user: str = Depends(require_auth)
):
    theme = payload.theme.strip().lower()
    if theme not in _allowed_themes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="theme must be 'light' or 'dark'",
        )
    with _settings_lock:
        data = _read_settings()
        data["theme"] = theme
        _write_settings(data)
    return {"theme": theme, "source": "file"}
