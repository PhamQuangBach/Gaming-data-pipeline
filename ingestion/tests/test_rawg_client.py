import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from rawg_client import fetch_games_released_in_window, _filter_by_validated_release_date


FAKE_PAGE_1 = {
    "results": [{"id": 1, "name": "Game A", "released": "2026-06-15"},
                {"id": 2, "name": "Game B", "released": "2026-06-17"}],
    "next": "https://api.rawg.io/api/games?page=2&key=test"
}
FAKE_PAGE_2 = {
    "results": [{"id": 3, "name": "Game C", "released": "2026-06-20"}],
    "next": None
}
FAKE_EMPTY_WINDOW = {
    "results": [],
    "next": None
}


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_paginates(mock_get):
    """Should follow the `next` URL until it's None, across the whole window."""
    mock_resp_1 = MagicMock()
    mock_resp_1.json.return_value = FAKE_PAGE_1
    mock_resp_1.raise_for_status = MagicMock()

    mock_resp_2 = MagicMock()
    mock_resp_2.json.return_value = FAKE_PAGE_2
    mock_resp_2.raise_for_status = MagicMock()

    mock_get.side_effect = [mock_resp_1, mock_resp_2]

    games = fetch_games_released_in_window(api_key="test_key", end_date=date(2026, 6, 20), window_days=7)

    assert len(games) == 3
    assert games[0]["name"] == "Game A"
    assert games[2]["name"] == "Game C"
    assert mock_get.call_count == 2


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_uses_correct_date_range(mock_get):
    """A 7-day window ending 2026-06-20 should query dates=2026-06-14,2026-06-20."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_PAGE_2
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fetch_games_released_in_window(api_key="test_key", end_date=date(2026, 6, 20), window_days=7)

    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["dates"] == "2026-06-14,2026-06-20"


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_defaults_to_yesterday(mock_get):
    """With no end_date given, the window should end yesterday, not today."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_EMPTY_WINDOW
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fetch_games_released_in_window(api_key="test_key", window_days=7)

    expected_end = (date.today() - timedelta(days=1)).isoformat()
    expected_start = (date.today() - timedelta(days=7)).isoformat()
    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["dates"] == f"{expected_start},{expected_end}"


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_handles_no_releases(mock_get):
    """A quiet week with zero releases should return an empty list, not error."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_EMPTY_WINDOW
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    games = fetch_games_released_in_window(api_key="test_key", end_date=date(2026, 1, 1), window_days=7)

    assert games == []


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_respects_custom_window_size(mock_get):
    """window_days should change the start of the range, not just the default 7."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_EMPTY_WINDOW
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fetch_games_released_in_window(api_key="test_key", end_date=date(2026, 6, 20), window_days=3)

    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["dates"] == "2026-06-18,2026-06-20"


# --- Validation logic: don't blindly trust RAWG's `dates` filter ---

def test_validation_keeps_games_with_valid_in_range_released_date():
    games = [{"id": 1, "name": "Game A", "released": "2026-06-17"}]
    result = _filter_by_validated_release_date(games, date(2026, 6, 14), date(2026, 6, 20))
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_validation_drops_games_with_missing_released_field():
    games = [
        {"id": 1, "name": "Game A", "released": "2026-06-17"},
        {"id": 2, "name": "No Release Date", "released": None},
        {"id": 3, "name": "Missing Key"},  # no `released` key at all
    ]
    result = _filter_by_validated_release_date(games, date(2026, 6, 14), date(2026, 6, 20))
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_validation_drops_games_with_unparseable_released_date():
    games = [
        {"id": 1, "name": "Game A", "released": "2026-06-17"},
        {"id": 2, "name": "Bad Date", "released": "not-a-date"},
        {"id": 3, "name": "TBA", "released": "TBA"},
    ]
    result = _filter_by_validated_release_date(games, date(2026, 6, 14), date(2026, 6, 20))
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_validation_drops_games_with_released_date_outside_window():
    """The key case this guards against: RAWG's `dates` filter let a game
    through whose own `released` field doesn't actually match the window."""
    games = [
        {"id": 1, "name": "In Window", "released": "2026-06-17"},
        {"id": 2, "name": "Too Early", "released": "2026-05-01"},
        {"id": 3, "name": "Too Late", "released": "2026-07-01"},
    ]
    result = _filter_by_validated_release_date(games, date(2026, 6, 14), date(2026, 6, 20))
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_validation_boundary_dates_are_inclusive():
    games = [
        {"id": 1, "name": "Start boundary", "released": "2026-06-14"},
        {"id": 2, "name": "End boundary", "released": "2026-06-20"},
    ]
    result = _filter_by_validated_release_date(games, date(2026, 6, 14), date(2026, 6, 20))
    assert len(result) == 2


@patch("rawg_client.requests.get")
def test_fetch_games_released_in_window_drops_invalid_games_end_to_end(mock_get):
    """A game with a released date outside the window, even though RAWG
    returned it for the query, should not appear in the final result."""
    page_with_bad_data = {
        "results": [
            {"id": 1, "name": "Valid Game", "released": "2026-06-17"},
            {"id": 2, "name": "Bad Game", "released": "2099-01-01"},  # way outside window
        ],
        "next": None,
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = page_with_bad_data
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    games = fetch_games_released_in_window(api_key="test_key", end_date=date(2026, 6, 20), window_days=7)

    assert len(games) == 1
    assert games[0]["id"] == 1


# --- Description enrichment (detail endpoint) ---

from unittest.mock import patch, MagicMock
from rawg_client import fetch_game_detail, enrich_with_descriptions


@patch("rawg_client.requests.get")
def test_fetch_game_detail_returns_full_record(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 42, "name": "Game X", "description_raw": "A great game."}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    detail = fetch_game_detail(api_key="test_key", game_id=42)

    assert detail["id"] == 42
    assert detail["description_raw"] == "A great game."


@patch("rawg_client.requests.get")
def test_fetch_game_detail_returns_none_on_404(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    detail = fetch_game_detail(api_key="test_key", game_id=999999)

    assert detail is None


@patch("rawg_client.time.sleep", return_value=None)  # skip real pauses in tests
@patch("rawg_client.fetch_game_detail")
def test_enrich_with_descriptions_merges_detail_into_list_record(mock_detail, mock_sleep):
    mock_detail.return_value = {"id": 1, "name": "Game A", "description_raw": "Full description here."}

    games = [{"id": 1, "name": "Game A", "rating": 4.5}]  # list-endpoint record, no description
    enriched = enrich_with_descriptions(api_key="test_key", games=games)

    assert len(enriched) == 1
    assert enriched[0]["rating"] == 4.5  # original field preserved
    assert enriched[0]["description_raw"] == "Full description here."  # merged in


@patch("rawg_client.time.sleep", return_value=None)
@patch("rawg_client.fetch_game_detail")
def test_enrich_with_descriptions_keeps_original_record_on_404(mock_detail, mock_sleep):
    mock_detail.return_value = None  # simulates a 404

    games = [{"id": 1, "name": "Game A", "rating": 4.5}]
    enriched = enrich_with_descriptions(api_key="test_key", games=games)

    assert len(enriched) == 1
    assert enriched[0]["name"] == "Game A"
    assert "description_raw" not in enriched[0]


@patch("rawg_client.time.sleep", return_value=None)
@patch("rawg_client.fetch_game_detail")
def test_enrich_with_descriptions_handles_missing_id(mock_detail, mock_sleep):
    games = [{"name": "No ID Game"}]  # malformed entry, missing `id`
    enriched = enrich_with_descriptions(api_key="test_key", games=games)

    assert len(enriched) == 1
    assert enriched[0]["name"] == "No ID Game"
    mock_detail.assert_not_called()  # should never call the API for a record with no id