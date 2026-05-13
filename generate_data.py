from scraper import scrape_season
import json
import os
from datetime import datetime

SEASONS = [2024, 2025, 2026]


def main():
    all_games = []
    for season in SEASONS:
        games = scrape_season(season)
        for g in games:
            g["시즌"] = season
        all_games.extend(games)

    seen = set()
    unique = []
    for g in all_games:
        key = g.get("game_idx")
        if key and key not in seen:
            seen.add(key)
            unique.append(g)
        elif not key:
            unique.append(g)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(unique),
        "games": unique,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/games.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"완료: {len(unique)}경기 → data/games.json")


if __name__ == "__main__":
    main()
