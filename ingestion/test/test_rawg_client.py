import pytest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from rawg_client import fetch_games


FAKE_PAGE_1 = {
    "results": [{"id": 1, "name": "Game A"}, {"id": 2, "name": "Game B"}],
    "next": "https://api.rawg.io/api/games?page=2&key=test"
}
FAKE_PAGE_2 = {
    "results": [{"id": 3, "name": "Game C"}],
    "next": None
}


@patch("rawg_client.requests.get")
def test_fetch_games_paginates(mock_get):
    """Should follow the `next` URL until it's None."""
    mock_resp_1 = MagicMock()
    mock_resp_1.json.return_value = FAKE_PAGE_1
    mock_resp_1.raise_for_status = MagicMock()

    mock_resp_2 = MagicMock()
    mock_resp_2.json.return_value = FAKE_PAGE_2
    mock_resp_2.raise_for_status = MagicMock()

    mock_get.side_effect = [mock_resp_1, mock_resp_2]

    games = fetch_games(api_key="test_key", max_pages=10)

    assert len(games) == 3
    assert games[0]["name"] == "Game A"
    assert games[2]["name"] == "Game C"
    assert mock_get.call_count == 2


@patch("rawg_client.requests.get")
def test_fetch_games_respects_max_pages(mock_get):
    """Should stop after max_pages even if `next` keeps appearing."""
    always_has_next = {"results": [{"id": 1, "name": "X"}], "next": "https://api.rawg.io/api/games?page=99"}
    mock_resp = MagicMock()
    mock_resp.json.return_value = always_has_next
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    games = fetch_games(api_key="test_key", max_pages=3)

    assert len(games) == 3          # 1 per page × 3 pages
    assert mock_get.call_count == 3