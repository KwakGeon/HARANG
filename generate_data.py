from scraper import scrape_season, fetch_pitcher_ranking, fetch_hitter_ranking, scrape_next_opponent, scrape_upcoming_by_league
from boxscore import fetch_boxscore, generate_best_worst, extract_player_stats
import json
import re
import time
from datetime import datetime, date

SEASONS = [2024, 2025, 2026]


def _parse_innings(s):
    """'11.1' → 11.333, '18.2' → 18.667, '5' → 5.0  (아웃카운트 기반 표기 변환)"""
    try:
        s = str(s)
        if '.' in s:
            full, outs = s.split('.', 1)
            return int(full) + int(outs) / 3
        return float(s)
    except Exception:
        return 0.0


def _parse_box_innings(s):
    """박스스코어 이닝 파싱: '3 할' '2' '7.1' 등 → 실수
    이닝 셀에 한글 접미사가 붙는 경우 숫자 앞부분만 추출."""
    m = re.match(r'(\d+(?:\.\d+)?)', str(s or '0').strip())
    return _parse_innings(m.group(1)) if m else 0.0


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
                                  실책출루=0, 홈런=0, 삼루타=0, 이루타=0,
                                  실책_기록=[])
            d = bat[short]
            d["경기"] += 1
            for k in ["타수", "안타", "타점", "득점", "도루", "볼넷", "사구",
                      "삼진", "실책출루", "홈런", "삼루타", "이루타"]:
                d[k] += b.get(k, 0)
            실책_플레이 = b.get("실책_플레이", [])
            if 실책_플레이:
                d["실책_기록"].append({
                    "날짜":   ps.get("날짜", ""),
                    "상대팀": ps.get("상대팀", ""),
                    "플레이": 실책_플레이,
                })

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
        ab  = d["타수"]
        bb  = d["볼넷"]
        hbp = d["사구"]
        pa  = ab + bb + hbp
        if pa == 0:
            continue
        h      = d["안타"]
        h_adj  = h + d["실책출루"]      # 실책 출루 포함 안타
        hr     = d["홈런"]
        tri    = d["삼루타"]
        dbl    = d["이루타"]
        single = max(0, h - dbl - tri - hr)
        obp    = round((h + bb + hbp) / pa, 3) if pa > 0 else 0.0
        tb     = single + dbl*2 + tri*3 + hr*4
        slg    = round(tb / ab, 3)      if ab > 0 else 0.0
        batters.append({
            "name":    bat_nm.get(short, short),
            "경기":    d["경기"],
            "출석률":  round(d["경기"] / total_games * 100, 1),
            "타수":    ab,
            "정규타율": round(h / ab, 3) if ab > 0 else 0.0,
            "타율":    round(h_adj / ab, 3) if ab > 0 else 0.0,
            "실책_기록": d.get("실책_기록", []),
            "타점":    d["타점"],
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


def _compute_scouting(next_opp, unique, cur_season):
    """예정 경기 1건에 대한 전력분석 dict를 반환. 데이터 없으면 None."""
    opp_name   = next_opp["상대팀"]
    opp_idx    = next_opp.get("상대팀_idx")
    opp_league = next_opp.get("리그", "")

    our_season_games  = [g for g in unique if g.get("시즌") == cur_season]
    is_current_league = any(g.get("리그") == opp_league for g in our_season_games)

    head_to_head = [g for g in unique
                    if g.get("상대팀") == opp_name
                    and g.get("리그") == opp_league]

    opp_batters  = []
    opp_pitchers = []
    priority     = None

    if is_current_league and head_to_head:
        priority = "head_to_head"
        bat_agg = {}
        pit_agg = {}

        for g in head_to_head:
            gidx = g.get("game_idx")
            if not gidx:
                continue
            bs = fetch_boxscore(gidx)
            if not bs:
                continue

            for b in bs.get("opp_batters", []):
                nm = b.get("name", "")
                if not nm or len(nm) < 2 or (b["타수"] == 0 and b["안타"] == 0):
                    continue
                plays = b.get("plays", [])
                볼넷 = sum(1 for p in plays if "4구" in p)
                사구 = sum(1 for p in plays if "몸맞" in p)
                삼진 = sum(1 for p in plays if "삼진" in p)
                if nm not in bat_agg:
                    bat_agg[nm] = dict(경기=0, 타수=0, 안타=0, 타점=0,
                                       득점=0, 도루=0, 볼넷=0, 사구=0,
                                       삼진=0, 홈런=0, 삼루타=0, 이루타=0)
                d = bat_agg[nm]
                d["경기"] += 1
                d["타수"] += b["타수"]; d["안타"] += b["안타"]
                d["타점"] += b["타점"]; d["득점"] += b["득점"]
                d["도루"] += b["도루"]; d["볼넷"] += 볼넷
                d["사구"] += 사구;       d["삼진"] += 삼진
                for play in plays:
                    if "홈런" in play:
                        d["홈런"] += 1
                    elif any(x in play for x in ["월3", "중3", "우중3", "좌중3"]):
                        d["삼루타"] += 1
                    elif any(x in play for x in ["월2", "중2", "우중2", "좌중2"]):
                        d["이루타"] += 1

            for p in bs.get("opp_pitchers", []):
                nm = p.get("name", "")
                if not nm or len(nm) < 2:
                    continue
                if nm not in pit_agg:
                    pit_agg[nm] = dict(경기=0, 삼진=0, 볼넷=0,
                                       자책점=0, 실점=0, 이닝=0.0)
                d = pit_agg[nm]
                d["경기"]  += 1
                d["삼진"]  += p.get("삼진", 0)
                d["볼넷"]  += p.get("볼넷", 0)
                d["자책점"] += p.get("자책점", 0)
                d["실점"]  += p.get("실점", 0)
                d["이닝"]  += _parse_box_innings(p.get("이닝", "0"))

        for nm, d in bat_agg.items():
            ab = d["타수"]; bb = d["볼넷"]; hbp = d["사구"]
            pa = ab + bb + hbp
            if pa == 0:
                continue
            h      = d["안타"]
            hr     = d["홈런"]; tri = d["삼루타"]; dbl = d["이루타"]
            single = max(0, h - dbl - tri - hr)
            obp    = round((h + bb + hbp) / pa, 3)
            tb     = single + dbl*2 + tri*3 + hr*4
            slg    = round(tb / ab, 3) if ab > 0 else 0.0
            opp_batters.append({
                "name": nm, "경기": d["경기"], "타수": ab, "안타": h,
                "타율": round(h / ab, 3) if ab > 0 else 0.0,
                "타점": d["타점"], "도루": d["도루"], "삼진": d["삼진"],
                "볼넷": bb, "홈런": hr, "득점": d["득점"],
                "OBP": obp, "SLG": slg, "OPS": round(obp + slg, 3),
            })

        for nm, d in pit_agg.items():
            innings = d["이닝"]
            era = round(d["자책점"] / innings * 7, 2) if innings > 0 else 99.99
            opp_pitchers.append({
                "name": nm, "경기": d["경기"],
                "이닝": str(round(innings, 1)),
                "삼진": d["삼진"], "볼넷": d["볼넷"],
                "실점": d["실점"], "자책점": d["자책점"], "방어율": era,
            })

    elif opp_idx:
        if is_current_league:
            priority = "current_league"
        else:
            priority = "next_league"
        opp_batters  = fetch_hitter_ranking(cur_season, opp_idx)
        opp_pitchers = fetch_pitcher_ranking(cur_season, opp_idx)
        opp_batters  = [b for b in opp_batters  if b.get("경기", 0) > 0]
        opp_pitchers = [p for p in opp_pitchers if p.get("경기", 0) > 0]

    if not priority:
        return None

    return {
        "league":             opp_league,
        "opponent":           opp_name,
        "opponent_idx":       opp_idx,
        "game_date":          next_opp["날짜"],
        "priority":           priority,
        "head_to_head_count": len(head_to_head),
        "batters":            opp_batters,
        "pitchers":           opp_pitchers,
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
            ps["날짜"]  = g.get("날짜", "")
            ps["상대팀"] = g.get("상대팀", "")
            season = g.get("시즌", 0)
            season_ps.setdefault(season, []).append(ps)

        status = "[O]" if best[0] != "상세 기록 미입력" else "[ ]"
        print(f"  [{i+1:2d}/{len(unique)}] {status} {g['날짜']} vs {g['상대팀']}")
        time.sleep(0.5)

    # ── MVP 통계 계산 (최신 시즌 기준) ────────────────────
    mvp_stats = None
    cur_season = None
    if season_ps:
        cur_season = max(season_ps.keys())
        total_cur  = sum(1 for g in unique if g.get("시즌") == cur_season and g.get("game_idx"))
        mvp_stats  = calc_season_mvp(season_ps[cur_season], total_cur, cur_season)

        # 투수: gameone.kr 랭킹 페이지 실제값 + 규정이닝(경기수×1) 필터
        pit_ranking = fetch_pitcher_ranking(cur_season)
        if pit_ranking and mvp_stats:
            qualified = [p for p in pit_ranking
                         if _parse_innings(p["이닝"]) >= total_cur]
            mvp_stats["pitcher"] = qualified

        # 타자: gameone.kr 랭킹 페이지 공식 집계 사용
        # 실책_기록(툴팁용)만 박스스코어에서 병합
        hit_ranking = fetch_hitter_ranking(cur_season)
        if hit_ranking and mvp_stats:
            reach_map = {}
            for ps in season_ps.get(cur_season, []):
                for b in ps.get("batters", []):
                    실책_플레이 = b.get("실책_플레이", [])
                    if 실책_플레이:
                        short = _short_name(b["name"])
                        reach_map.setdefault(short, []).append({
                            "날짜":   ps.get("날짜", ""),
                            "상대팀": ps.get("상대팀", ""),
                            "플레이": 실책_플레이,
                        })

            batters = []
            for b in hit_ranking:
                short   = _short_name(b["name"])
                records = reach_map.get(short, [])
                실책출루  = sum(len(r["플레이"]) for r in records)
                ab      = b["타수"]
                h       = b["안타"]
                타율     = round((h + 실책출루) / ab, 3) if ab > 0 else 0.0
                batters.append({
                    "name":     b["name"],
                    "경기":     b["경기"],
                    "출석률":   round(b["경기"] / total_cur * 100, 1),
                    "타수":     ab,
                    "타석":     b["타석"],
                    "정규타율": b["정규타율"],
                    "타율":     타율,
                    "실책_기록": records,
                    "타점":     b["타점"],
                    "도루":     b["도루"],
                    "삼진":     b["삼진"],
                    "볼넷":     b["볼넷"],
                    "홈런":     b["홈런"],
                    "득점":     b["득점"],
                    "OBP":      b["OBP"],
                    "SLG":      b["SLG"],
                    "OPS":      b["OPS"],
                })
            mvp_stats["batter"] = batters

        # MVP 데이터가 커버하는 리그 목록 (브라우저 필터 연동용)
        cur_season_leagues = list(dict.fromkeys(
            g.get("리그", "") for g in unique
            if g.get("시즌") == cur_season and g.get("리그") and g.get("game_idx")
        ))
        mvp_stats["leagues"] = cur_season_leagues

    # ── 전력분석: 리그별 예정 경기 기준 ────────────────────────────────
    scouting          = None
    scouting_by_league = []
    if cur_season:
        print("\n전력분석 수집 중...")
        today = datetime.today().date()
        next_by_league = scrape_upcoming_by_league(cur_season, today)

        if not next_by_league:
            print("  다음 예정 경기 없음")
        else:
            for league, next_opp in next_by_league.items():
                print(f"  [{league}] {next_opp['날짜']} vs {next_opp['상대팀']}")
                entry = _compute_scouting(next_opp, unique, cur_season)
                if entry:
                    scouting_by_league.append(entry)
                    print(f"    -> {entry['priority']}: 타자 {len(entry['batters'])}명 · 투수 {len(entry['pitchers'])}명")
                else:
                    print(f"    -> 스카우팅 건너뜀 (상대팀 idx 없음)")

        # backward compat: scouting = 리그 전체 기준 가장 빠른 경기
        scouting = scouting_by_league[0] if scouting_by_league else None

    data = {
        "generated_at":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total":             len(unique),
        "games":             unique,
        "mvp_stats":         mvp_stats,
        "scouting":          scouting,
        "scouting_by_league": scouting_by_league,
    }

    with open("games_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    has_data = sum(1 for g in unique if g.get("best", [""])[0] != "상세 기록 미입력")
    print(f"\n완료: {len(unique)}경기 저장 (상세기록 {has_data}경기) → games_data.json")
    if mvp_stats:
        print(f"MVP 집계: {mvp_stats['season']}시즌 타자 {len(mvp_stats['batter'])}명 · 투수 {len(mvp_stats['pitcher'])}명")
    print(f"전력분석 리그: {[e['league'] for e in scouting_by_league]}")


if __name__ == "__main__":
    main()
