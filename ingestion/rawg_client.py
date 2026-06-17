import requests
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://api.rawg.io/api"

def fetch_games(api_key: str, max_pages: int = 5) -> list[dict]:
    """
    Fetch games from RAWG API with automatic pagination.
    max_pages=5 fetches up to 500 games (100 per page) — good for testing.
    Set max_pages=None to fetch everything (~900k games, use carefully).
    """
    games = []
    url = f"{BASE_URL}/games"
    params = {"key": api_key, "page_size": 100, "ordering": "-rating"}
    page = 1

    while url and (max_pages is None or page <= max_pages):
        log.info(f"Fetching page {page} from RAWG...")
        response = requests.get(url, params=params if page == 1 else None, timeout=15)
        response.raise_for_status()
        data = response.json()

        batch = data.get("results", [])
        games.extend(batch)
        log.info(f"  Got {len(batch)} games (total so far: {len(games)})")

        url = data.get("next")   # RAWG gives us the full next-page URL
        params = None            # params are already baked into the next URL
        page += 1
        time.sleep(0.2)          # be polite to the API

    log.info(f"Done. Fetched {len(games)} games total.")
    return games


def fetch_genres(api_key: str) -> list[dict]:
    """Fetch the genres lookup table."""
    log.info("Fetching genres...")
    response = requests.get(f"{BASE_URL}/genres", params={"key": api_key}, timeout=15)
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_platforms(api_key: str) -> list[dict]:
    """Fetch the platforms lookup table."""
    log.info("Fetching platforms...")
    response = requests.get(f"{BASE_URL}/platforms", params={"key": api_key}, timeout=15)
    response.raise_for_status()
    return response.json().get("results", [])