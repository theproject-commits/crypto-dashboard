from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from .... import crud, schemas, models
from ....database import get_db

router = APIRouter()

@router.post("/", response_model=schemas.Cryptocurrency)
def create_cryptocurrency(crypto: schemas.CryptocurrencyCreate, db: Session = Depends(get_db)):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=crypto.coingecko_id)
    if db_crypto:
        raise HTTPException(status_code=400, detail="Cryptocurrency with this CoinGecko ID already registered")
    return crud.create_cryptocurrency(db=db, crypto=crypto)

@router.get("/", response_model=List[schemas.Cryptocurrency])
def read_cryptocurrencies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    cryptos = crud.get_cryptocurrencies(db, skip=skip, limit=limit)
    return cryptos

@router.get("/{coingecko_id}/history", response_model=List[schemas.PriceHistory])
def read_price_history(
    coingecko_id: str,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db)
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")
    
    price_history = crud.get_price_history(db, crypto_id=db_crypto.id, start_date=start_date, end_date=end_date)
    return price_history
