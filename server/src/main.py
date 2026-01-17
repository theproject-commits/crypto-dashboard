from fastapi import FastAPI

app = FastAPI(
    title="Crypto Dashboard API",
    description="API for fetching crypto data and eventually predictions.",
    version="0.1.0",
)

@app.get("/")
async def root():
    return {"message": "Welcome to the Crypto Dashboard API!"}

# TODO: Add API endpoints for cryptocurrencies, price history, etc.
# from .api.v1.endpoints import cryptos
# app.include_router(cryptos.router, prefix="/api/v1/cryptos", tags=["cryptos"])
