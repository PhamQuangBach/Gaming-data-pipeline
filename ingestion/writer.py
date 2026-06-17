import json
import os
from datetime import date
from pathlib import Path
import logging

log = logging.getLogger(__name__)

def write_jsonl(records: list[dict], entity: str, base_dir: str = "data/bronze") -> Path:
    # Output path: data/bronze/{entity}/{YYYY-MM-DD}/data.jsonl
    today = date.today().isoformat()
    output_dir = Path(base_dir) / entity / today
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / "data.jsonl"

    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    log.info(f"Wrote {len(records)} records to {output_path}")
    return output_path


def preview(path: Path, n: int = 2) -> None:
    # Preview
    print(f"\n--- Preview of {path} (first {n} records) ---")
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            record = json.loads(line)
 
            # RAWG occasionally returns a platforms/genres entry where the nested
            # object itself is null — guard against that instead of crashing.
            genre_names = [
                g["name"] for g in record.get("genres", []) or []
                if g and g.get("name")
            ]
            platform_names = [
                p["platform"]["name"] for p in record.get("platforms", []) or []
                if p and p.get("platform") and p["platform"].get("name")
            ]
 
            print(json.dumps({
                "id": record.get("id"),
                "name": record.get("name"),
                "released": record.get("released"),
                "rating": record.get("rating"),
                "metacritic": record.get("metacritic"),
                "genres": genre_names,
                "platforms": platform_names,
            }, indent=2))
    print("---\n")