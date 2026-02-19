from datetime import UTC, date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pycoingecko import CoinGeckoAPI
import requests
from sqlalchemy.orm import Session

from .... import crud, schemas
from ....database import get_db
from ....security import require_auth
from .cryptos_utils import clean_html_text as _clean_html_text

router = APIRouter()
cg = CoinGeckoAPI()


@router.post("/", response_model=schemas.Cryptocurrency)
def create_cryptocurrency(
    crypto: schemas.CryptocurrencyCreate,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=crypto.coingecko_id)
    if db_crypto:
        raise HTTPException(status_code=400, detail="Cryptocurrency with this CoinGecko ID already registered")
    return crud.create_cryptocurrency(db=db, crypto=crypto)


@router.get("/", response_model=List[schemas.Cryptocurrency])
def read_cryptocurrencies(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    cryptos = crud.get_cryptocurrencies(db, skip=skip, limit=limit)
    return cryptos


@router.get("/{coingecko_id}", response_model=schemas.Cryptocurrency)
def read_cryptocurrency(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")
    return db_crypto


@router.get("/{coingecko_id}/profile", response_model=schemas.CryptoProfileResponse)
def read_crypto_profile(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    try:
        response = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coingecko_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return schemas.CryptoProfileResponse(
            coingecko_id=coingecko_id,
            name=db_crypto.name,
            symbol=db_crypto.symbol.lower(),
            description="Descricao detalhada indisponivel no momento. O provedor externo nao respondeu.",
            homepage=None,
            genesis_date=None,
            categories=[],
        )

    description = _clean_html_text((payload.get("description") or {}).get("en"))
    if not description:
        description = "Descricao indisponivel no provedor."

    homepage_list = (payload.get("links") or {}).get("homepage") or []
    homepage = next((x for x in homepage_list if isinstance(x, str) and x.strip()), None)
    categories = [str(x) for x in (payload.get("categories") or []) if isinstance(x, str)]

    return schemas.CryptoProfileResponse(
        coingecko_id=coingecko_id,
        name=str(payload.get("name") or db_crypto.name),
        symbol=str(payload.get("symbol") or db_crypto.symbol).lower(),
        description=description,
        homepage=homepage,
        genesis_date=payload.get("genesis_date"),
        categories=categories[:12],
    )


@router.get("/{coingecko_id}/history", response_model=List[schemas.PriceHistory])
def read_price_history(
    coingecko_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    if start_date is None and end_date is None:
        return crud.get_price_history_all(db, crypto_id=db_crypto.id)

    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="Provide both start_date and end_date, or neither.")

    return crud.get_price_history(db, crypto_id=db_crypto.id, start_date=start_date, end_date=end_date)


@router.post("/{coingecko_id}/populate-history")
def populate_history_endpoint(
    coingecko_id: str,
    days: int = Query(default=30, ge=1, le=20000),
    full_history: bool = False,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found in database. Cannot populate history.")

    window = "max" if full_history else days
    success = crud.populate_price_history_from_coingecko(db, coingecko_id, window)
    if success:
        label = "full lifetime" if full_history else f"{days} days"
        return {"message": f"Successfully populated {coingecko_id} history for {label}."}
    raise HTTPException(status_code=500, detail=f"Failed to populate {coingecko_id} history. Check CoinGecko ID or API limits.")


@router.get("/{coingecko_id}/live", response_model=schemas.LivePriceResponse)
def read_live_price(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    provider_price: float | None = None
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        response = requests.get(
            url,
            params={"ids": coingecko_id, "vs_currencies": "usd"},
            timeout=4,
        )
        response.raise_for_status()
        payload = response.json()
        if payload and coingecko_id in payload and "usd" in payload[coingecko_id]:
            provider_price = float(payload[coingecko_id]["usd"])
    except Exception:
        provider_price = None

    if provider_price is not None:
        return schemas.LivePriceResponse(
            coingecko_id=coingecko_id,
            price_usd=provider_price,
            fetched_at=datetime.now(UTC),
            source="coingecko",
        )

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    if not history:
        raise HTTPException(status_code=502, detail="Live provider unavailable and no local history fallback")

    fallback_price = float(history[-1].price_usd)
    return schemas.LivePriceResponse(
        coingecko_id=coingecko_id,
        price_usd=fallback_price,
        fetched_at=datetime.now(UTC),
        source="fallback_history",
    )
