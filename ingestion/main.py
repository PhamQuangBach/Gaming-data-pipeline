import os
from dotenv import load_dotenv
from rawg_client import fetch_games_released_on, fetch_games, fetch_genres, fetch_platforms
from writer import write_jsonl, preview

def main():
    load_dotenv()
    api_key = os.getenv("RAWG_API_KEY")

    if not api_key:
        raise ValueError("RAWG_API_KEY not found")

    # Fetch data
    games = fetch_games_released_on(api_key, max_pages=2)
    genres = fetch_genres(api_key)
    platforms = fetch_platforms(api_key)

    # Write jsonl 
    games_path    = write_jsonl(games,     entity="games")
    genres_path   = write_jsonl(genres,    entity="genres")
    platforms_path = write_jsonl(platforms, entity="platforms")

    # Preview
    preview(games_path, n=2)

    print(f"Success! Files written:")
    print(f"  {games_path}    ({len(games)} games)")
    print(f"  {genres_path}   ({len(genres)} genres)")
    print(f"  {platforms_path} ({len(platforms)} platforms)")

if __name__ == "__main__":
    main()