from scraper import scrape_season
from boxscore import fetch_boxscore, generate_best_worst
import json
import time
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

    print(f"\n박스스코어 수집 중 ({len(unique)}경기)...")
    for i, g in enumerate(unique):
        gidx = g.get("game_idx")
        if not gidx:
            g["best"] = ["기록 없음"]
            g["worst"] = ["기록 없음"]
            continue

        bs = fetch_boxscore(gidx)
        best, worst = generate_best_worst(g, bs)
        g["best"]  = best
        g["worst"] = worst

        status = "✅" if best[0] != "상세 기록 미입력" else "⬜"
        print(f"  [{i+1:2d}/{len(unique)}] {status} {g['날짜']} vs {g['상대팀']}")
        time.sleep(0.5)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(unique),
        "games": unique,
    }

    with open("games_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    has_data = sum(1 for g in unique if g.get("best", [""])[0] != "상세 기록 미입력")
    print(f"\n완료: {len(unique)}경기 저장 (상세기록 {has_data}경기) → games_data.json")


if __name__ == "__main__":
    main()
