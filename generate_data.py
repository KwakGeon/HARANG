from scraper import scrape_season
from boxscore import fetch_boxscore, generate_best_worst, extract_player_stats
import json
import re
import time
from datetime import datetime

SEASONS = [2024, 2025, 2026]


def _short_name(name):
    """'곽건(32)' → '곽건'  (집계 키용)"""
    m = re.match(r'^([가-힣]{2,5})', name)
    return m.group(1) if m else name


def calc_season_mvp(season_ps_list, total_games, season):
    """
    season_ps_list: extract_player_stats() 결과 리스트 (경기별)
    total_games   : 해당 시즌 집계 대상 경기 수
    """
    if not season_ps_list or total_games == 0:
        return None

    bat = {}   # short_name -> 누적 dict
    bat_nm = {}  # short_name -> display name
    pit = {}
    pit_nm = {}

    for ps in season_ps_list:
        n_pit = max(len(ps.get("pitchers", [])), 1)
        gi    = ps.get("game_innings", 7) or 7

        for b in ps.get("batters", []):
            nm    = b["name"]
            short = _short_name(nm)
            if not short:
                continue
            bat_nm[short] = nm
            if short not in bat:
                bat[short] = dict(경기=0, 타수=0, 안타=0, 타점=0, 득점=0,
                                  도루=0, 볼넷=0, 사구=0, 삼진=0,
                                  실책출루=0, 홈런=0, 삼루타=0, 이루타=0)
            d = bat[short]
            d["경기"] += 1
            for k in ["타수", "안타", "타점", "득점", "도루", "볼넷", "사구",
                      "삼진", "실책출루", "홈런", "삼루타", "이루타"]:
                d[k] += b.get(k, 0)

        for p in ps.get("pitchers", []):
            nm    = p["name"]
            short = _short_name(nm)
            if not short:
                continue
            pit_nm[short] = nm
            if short not in pit:
                pit[short] = dict(경기=0, 삼진=0, 자책점=0, 실점=0, 이닝=0.0)
            d = pit[short]
            d["경기"]  += 1
            d["삼진"]  += p.get("삼진", 0)
            d["자책점"] += p.get("자책점", 0)
            d["실점"]  += p.get("실점", 0)
            d["이닝"]  += gi / n_pit  # 이닝 균등 배분 추정

    # ── 타자 파생 지표 ──────────────────────────────────
    batters = []
    for short, d in bat.items():
        ab = d["타수"]
        if ab < 5:
            continue
        h      = d["안타"]
        h_adj  = h + d["실책출루"]      # 실책 출루 포함 안타
        bb     = d["볼넷"]
        hbp    = d["사구"]
        hr     = d["홈런"]
        tri    = d["삼루타"]
        dbl    = d["이루타"]
        single = max(0, h - dbl - tri - hr)
        pa     = ab + bb + hbp
        obp    = round((h + bb + hbp) / pa, 3) if pa > 0 else 0.0
        tb     = single + dbl*2 + tri*3 + hr*4
        slg    = round(tb / ab, 3)      if ab > 0 else 0.0
        batters.append({
            "name":   bat_nm.get(short, short),
            "경기":   d["경기"],
            "출석률": round(d["경기"] / total_games * 100, 1),
            "타수":   ab,
            "타율":   round(h_adj / ab, 3) if ab > 0 else 0.0,
            "타점":   d["타점"],
            "도루":   d["도루"],
            "삼진":   d["삼진"],
            "볼넷":   bb,
            "홈런":   hr,
            "득점":   d["득점"],
            "OBP":    obp,
            "SLG":    slg,
            "OPS":    round(obp + slg, 3),
        })

    # ── 투수 파생 지표 ──────────────────────────────────
    pitchers = []
    for short, d in pit.items():
        g_cnt  = d["경기"]
        innings = d["이닝"]
        # 방어율: 자책점/이닝 × 7 (7이닝 기준)
        era = round(d["자책점"] / innings * 7, 2) if innings > 0 else 99.99
        pitchers.append({
            "name":   pit_nm.get(short, short),
            "경기":   g_cnt,
            "이닝":   round(innings, 1),
            "삼진":   d["삼진"],
            "자책점": d["자책점"],
            "실점":   d["실점"],
            "방어율": era,
        })

    return {
        "season":      season,
        "total_games": total_games,
        "batter":      batters,
        "pitcher":     pitchers,
    }


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

    # MVP 집계용 (시즌별)
    season_ps = {}  # season -> list of extract_player_stats results

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

        # MVP 집계 (게임 JSON에는 저장 안 함)
        ps = extract_player_stats(bs)
        if ps["batters"] or ps["pitchers"]:
            season = g.get("시즌", 0)
            season_ps.setdefault(season, []).append(ps)

        status = "[O]" if best[0] != "상세 기록 미입력" else "[ ]"
        print(f"  [{i+1:2d}/{len(unique)}] {status} {g['날짜']} vs {g['상대팀']}")
        time.sleep(0.5)

    # ── MVP 통계 계산 (최신 시즌 기준) ────────────────────
    mvp_stats = None
    if season_ps:
        cur_season = max(season_ps.keys())
        total_cur  = sum(1 for g in unique if g.get("시즌") == cur_season and g.get("game_idx"))
        mvp_stats  = calc_season_mvp(season_ps[cur_season], total_cur, cur_season)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total":        len(unique),
        "games":        unique,
        "mvp_stats":    mvp_stats,
    }

    with open("games_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    has_data = sum(1 for g in unique if g.get("best", [""])[0] != "상세 기록 미입력")
    print(f"\n완료: {len(unique)}경기 저장 (상세기록 {has_data}경기) → games_data.json")
    if mvp_stats:
        print(f"MVP 집계: {mvp_stats['season']}시즌 타자 {len(mvp_stats['batter'])}명 · 투수 {len(mvp_stats['pitcher'])}명")


if __name__ == "__main__":
    main()
