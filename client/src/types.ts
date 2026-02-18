export interface Cryptocurrency {
    id: number;
    coingecko_id: string;
    symbol: string;
    name: string;
    image_url: string;
}

export interface PriceHistory {
    id: number;
    crypto_id: number;
    date: string;
    price_usd: number;
    market_cap_usd: number;
    total_volume_usd: number;
}
