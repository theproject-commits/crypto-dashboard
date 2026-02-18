from fastapi import APIRouter, HTTPException, status

from .... import schemas
from ....security import verify_credentials

router = APIRouter()


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest):
    if not verify_credentials(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return {"message": "Login successful"}
