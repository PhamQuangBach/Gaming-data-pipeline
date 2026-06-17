import pytest
from unittest.mock import patch, MagicMock
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from rawg_client import fetch_games_released_on
 
 
FAKE_PAGE_1 = {
    "results": [{"id": 1, "name": "Game A", "released": "2026-06-15"},
                {"id": 2, "name": "Game B", "released": "2026-06-15"}],
    "next": "https://api.rawg.io/api/games?page=2&key=test"
}
FAKE_PAGE_2 = {
    "results": [{"id": 3, "name": "Game C", "released": "2026-06-15"}],
    "next": None
}
FAKE_EMPTY_DAY = {
    "results": [],
    "next": None
}
 
 
@patch("rawg_client.requests.get")
def test_fetch_games_released_on_paginates(mock_get):
    mock_resp_1 = MagicMock()
    mock_resp_1.json.return_value = FAKE_PAGE_1
    mock_resp_1.raise_for_status = MagicMock()
 
    mock_resp_2 = MagicMock()
    mock_resp_2.json.return_value = FAKE_PAGE_2
    mock_resp_2.raise_for_status = MagicMock()
 
    mock_get.side_effect = [mock_resp_1, mock_resp_2]
 
    games = fetch_games_released_on(api_key="test_key", target_date=date(2026, 6, 15))
 
    assert len(games) == 3
    assert games[0]["name"] == "Game A"
    assert games[2]["name"] == "Game C"
    assert mock_get.call_count == 2
 
 
@patch("rawg_client.requests.get")
def test_fetch_games_released_on_uses_dates_filter(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_PAGE_2  # single page, no next
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp
 
    fetch_games_released_on(api_key="test_key", target_date=date(2026, 6, 15))
 
    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["dates"] == "2026-06-15,2026-06-15"
 
 
@patch("rawg_client.requests.get")
def test_fetch_games_released_on_defaults_to_yesterday(mock_get):
    from datetime import timedelta
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_EMPTY_DAY
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp
 
    fetch_games_released_on(api_key="test_key")
 
    expected_yesterday = (date.today() - timedelta(days=1)).isoformat()
    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["dates"] == f"{expected_yesterday},{expected_yesterday}"
 
 
@patch("rawg_client.requests.get")
def test_fetch_games_released_on_handles_no_releases(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_EMPTY_DAY
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp
 
    games = fetch_games_released_on(api_key="test_key", target_date=date(2026, 1, 1))
 
    assert games == []