import requests
import time
import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://api.rawg.io/api"

def fetch_games(api_key: str, max_pages: int = 5) -> list[dict]:
    # Fetch games from RAWG API with automatic pagination.
    
    games = []
    url = f"{BASE_URL}/games"
    params = {"key": api_key, "page_size": 100, "ordering": "-rating"}
    page = 1

    while url and (max_pages is None or page <= max_pages):
        log.info(f"Fetching page {page} from RAWG")
        response = requests.get(url, params=params if page == 1 else None, timeout=15)
        response.raise_for_status()
        data = response.json()

        batch = data.get("results", [])
        games.extend(batch)
        log.info(f"  Got {len(batch)} games (total so far: {len(games)})")

        url = data.get("next")   
        params = None            
        page += 1
        time.sleep(0.2)          

    log.info(f"Done. Fetched {len(games)} games total.")
    return games

def fetch_games_released_on(api_key: str, target_date: date = None, max_pages: int = 20) -> list[dict]:

    if target_date is None:
        target_date = date.today() - timedelta(days=1)
 
    date_str = target_date.isoformat()
    games = []
    url = f"{BASE_URL}/games"
    params = {
        "key": api_key,
        "page_size": 100,
        "dates": f"{date_str},{date_str}", 
        "ordering": "-added",                 
    }
    page = 1
 
    log.info(f"Fetching games released on {date_str}...")
 
    while url and page <= max_pages:
        response = requests.get(url, params=params if page == 1 else None, timeout=15)
        response.raise_for_status()
        data = response.json()
 
        batch = data.get("results", [])
        games.extend(batch)
        log.info(f"  Page {page}: got {len(batch)} games (total so far: {len(games)})")
 
        url = data.get("next")
        params = None
        page += 1
        time.sleep(0.2)
 
    log.info(f"Done. {len(games)} games released on {date_str}.")
    return games

def fetch_games_released_in_window(
    api_key: str,
    end_date: date = None,
    window_days: int = 7,
    max_pages: int = 20,
) -> list[dict]:
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=window_days - 1)
 
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
 
    games = []
    url = f"{BASE_URL}/games"
    params = {
        "key": api_key,
        "page_size": 100,
        "dates": f"{start_str},{end_str}",
        "ordering": "-added",
    }
    page = 1
 
    log.info(f"Fetching games released {start_str} through {end_str} ({window_days}-day window)...")
 
    while url and page <= max_pages:
        response = requests.get(url, params=params if page == 1 else None, timeout=15)
        response.raise_for_status()
        data = response.json()
 
        batch = data.get("results", [])
        games.extend(batch)
        log.info(f"  Page {page}: got {len(batch)} games (total so far: {len(games)})")
 
        url = data.get("next")
        params = None
        page += 1
        time.sleep(0.2)
 
    validated = _filter_by_validated_release_date(games, start_date, end_date)

    log.info(f"Done. {len(validated)} games released in window {start_str}..{end_str}.")
    return validated

def _filter_by_validated_release_date(games: list[dict], start_date: date, end_date: date) -> list[dict]:
    validated = []
    for game in games:
        released_str = game.get("released")
        if not released_str:
            log.warning(f"Game id={game.get('id')} name={game.get('name')!r} has no `released` value — dropping.")
            continue
 
        try:
            released_date = date.fromisoformat(released_str)
        except ValueError:
            log.warning(
                f"Game id={game.get('id')} name={game.get('name')!r} has unparseable "
                f"`released` value {released_str!r} — dropping."
            )
            continue
 
        if not (start_date <= released_date <= end_date):
            log.warning(
                f"Game id={game.get('id')} name={game.get('name')!r} has `released`={released_date}, "
                f"outside the requested window {start_date}..{end_date} despite matching the dates "
                f"filter — dropping."
            )
            continue
 
        validated.append(game)
 
    return validated

def fetch_genres(api_key: str) -> list[dict]:
    log.info("Fetching genres")
    response = requests.get(f"{BASE_URL}/genres", params={"key": api_key}, timeout=15)
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_platforms(api_key: str) -> list[dict]:
    log.info("Fetching platforms")
    response = requests.get(f"{BASE_URL}/platforms", params={"key": api_key}, timeout=15)
    response.raise_for_status()
    return response.json().get("results", [])

def fetch_game_detail(api_key: str, game_id: int) -> dict | None:
    url = f"{BASE_URL}/games/{game_id}"
    response = requests.get(url, params={"key": api_key}, timeout=15)
 
    if response.status_code == 404:
        log.warning(f"Game id={game_id} returned 404 on detail endpoint — skipping.")
        return None
 
    response.raise_for_status()
    return response.json()

def enrich_with_descriptions(api_key: str, games: list[dict], pause_seconds: float = 0.3) -> list[dict]:
    enriched = []
    total = len(games)
 
    for i, game in enumerate(games, start=1):
        game_id = game.get("id")
        if game_id is None:
            log.warning(f"Game entry missing `id` — skipping enrichment for {game.get('name')!r}.")
            enriched.append(game)
            continue
 
        log.info(f"Enriching {i}/{total}: id={game_id} name={game.get('name')!r}")
        detail = fetch_game_detail(api_key, game_id)
 
        if detail is None:
            # Detail fetch failed/404 keep the original list-endpoint
            enriched.append(game)
        else:
            # Merge: keep all original list-endpoint fields, add detail fields
            merged = {**game, **detail}
            enriched.append(merged)
 
        time.sleep(pause_seconds)
 
    described_count = sum(1 for g in enriched if g.get("description_raw"))
    log.info(f"Enrichment complete: {described_count}/{total} games have a description.")
    return enriched