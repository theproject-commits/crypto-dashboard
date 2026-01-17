import pytest
from unittest.mock import MagicMock, patch
from ...src.scripts import populate_db
from ...src import schemas

# Mock data for CoinGecko API responses
MOCK_MARKETS_DATA = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "image": "http://example.com/bitcoin.png"
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "image": "http://example.com/ethereum.png"
    }
]

MOCK_CHART_DATA = {
    "prices": [[1672531200000, 20000.0]], # Jan 1, 2023
    "market_caps": [[1672531200000, 400000000000]],
    "total_volumes": [[1672531200000, 15000000000]]
}

@patch('...src.scripts.populate_db.crud')
@patch('...src.scripts.populate_db.cg') # Patch the CoinGeckoAPI client instance
def test_populate_cryptocurrencies_new_crypto(mock_cg_client, mock_crud):
    """
    Tests that a new cryptocurrency from the API is added to the database.
    """
    # Arrange: Mock SDK method to return crypto data, and mock DB to say it doesn't exist
    mock_cg_client.get_coins_markets.return_value = [MOCK_MARKETS_DATA[0]]
    mock_crud.get_cryptocurrency_by_coingecko_id.return_value = None

    # Act: Run the function
    populate_db.populate_cryptocurrencies(db=MagicMock())

    # Assert: Check that the API was called and the create function was called with correct data
    mock_cg_client.get_coins_markets.assert_called_once()
    mock_crud.create_cryptocurrency.assert_called_once()
    
    # Check the content of the call
    call_args, call_kwargs = mock_crud.create_cryptocurrency.call_args
    assert call_kwargs['crypto'].coingecko_id == "bitcoin"
    assert call_kwargs['crypto'].name == "Bitcoin"
    assert call_kwargs['crypto'].symbol == "btc"


@patch('...src.scripts.populate_db.crud')
@patch('...src.scripts.populate_db.cg')
def test_populate_cryptocurrencies_existing_crypto(mock_cg_client, mock_crud):
    """
    Tests that an existing cryptocurrency from the API is NOT added to the database again.
    """
    # Arrange: Mock SDK to return one crypto, and mock DB to say it already exists
    mock_cg_client.get_coins_markets.return_value = [MOCK_MARKETS_DATA[0]]
    mock_crud.get_cryptocurrency_by_coingecko_id.return_value = MagicMock() # Simulate finding a crypto

    # Act: Run the function
    populate_db.populate_cryptocurrencies(db=MagicMock())

    # Assert: Check that the create function was NEVER called
    mock_crud.create_cryptocurrency.assert_not_called()


@patch('...src.scripts.populate_db.time.sleep')
@patch('...src.scripts.populate_db.crud')
@patch('...src.scripts.populate_db.cg')
def test_populate_price_history_new_entry(mock_cg_client, mock_crud, mock_sleep):
    """
    Tests that new price history data is added to the database.
    """
    # Arrange
    # Mock DB to return one cryptocurrency to get history for
    mock_crypto = schemas.Cryptocurrency(id=1, coingecko_id='bitcoin', symbol='btc', name='Bitcoin', image_url=None, last_updated='2023-01-01T00:00:00Z')
    mock_crud.get_cryptocurrencies.return_value = [mock_crypto]
    
    # Mock SDK to return chart data
    mock_cg_client.get_coin_market_chart_range_by_id.return_value = MOCK_CHART_DATA
    
    # Mock DB to say the price entry does not exist
    mock_crud.get_price_history_by_crypto_id_and_date.return_value = None

    # Act
    populate_db.populate_price_history(db=MagicMock(), days=1)

    # Assert
    mock_crud.get_cryptocurrencies.assert_called_once()
    mock_cg_client.get_coin_market_chart_range_by_id.assert_called_once()
    mock_crud.create_price_history_entry.assert_called_once()
    mock_sleep.assert_called_once_with(populate_db.REQUEST_DELAY_SECONDS)


@patch('...src.scripts.populate_db.time.sleep')
@patch('...src.scripts.populate_db.crud')
@patch('...src.scripts.populate_db.cg')
def test_populate_price_history_api_fails(mock_cg_client, mock_crud, mock_sleep):
    """
    Tests that if the API call for history fails, no data is added and we still sleep.
    """
    # Arrange
    mock_crypto = schemas.Cryptocurrency(id=1, coingecko_id='bitcoin', symbol='btc', name='Bitcoin', image_url=None, last_updated='2023-01-01T00:00:00Z')
    mock_crud.get_cryptocurrencies.return_value = [mock_crypto]
    
    # Mock SDK to raise an exception, simulating a failure
    mock_cg_client.get_coin_market_chart_range_by_id.side_effect = Exception("API is down")

    # Act
    populate_db.populate_price_history(db=MagicMock(), days=1)
    
    # Assert
    mock_crud.create_price_history_entry.assert_not_called()
    mock_sleep.assert_called_once_with(populate_db.REQUEST_DELAY_SECONDS)
