from fastapi import APIRouter

from . import cryptos_catalog, cryptos_composite, cryptos_predict_state, cryptos_research

router = APIRouter()
router.include_router(cryptos_catalog.router)
router.include_router(cryptos_predict_state.router)
router.include_router(cryptos_composite.router)
router.include_router(cryptos_research.router)
