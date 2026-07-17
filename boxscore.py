"""박스스코어 파싱 및 Best/Worst 자동 생성"""
import re
from scraper import get_page
from bs4 import BeautifulSoup

MY_TEAM = "하랑 타이거즈"
CLUB_IDX = 31310

HIT_TYPE = {
    "홈런": "홈런", "중월3": "3루타", "좌월3": "3루타", "우월3": "3루타",
    "우중3": "3루타", "좌중3": "3루타", "중월2": "2루타", "좌월2": "2루타",
    "우월2": "2루타", "우중2": "2루타", "좌중2": "2루타",
}


def parse_batter_row(cells):
    """타자 한 행 파싱 (cells[4:-7]=플레이, cells[-7:-2]=통계)"""
    if len(cells) < 11:
        return None
    try:
        name = cells[2]
        pos  = cells[1]
        plays = [p.strip() for p in cells[4:-7] if p.strip()]
        stats = cells[-7:-2]
        return {
            "name": name,
            "pos":  pos,
            "plays": plays,
            "타수": int(stats[0]) if stats[0].isdigit() else 0,
            "안타": int(stats[1]) if stats[1].isdigit() else 0,
            "타점": int(stats[2]) if stats[2].isdigit() else 0,
            "득점": int(stats[3]) if stats[3].isdigit() else 0,
            "도루": int(stats[4]) if stats[4].isdigit() else 0,
        }
    except Exception:
        return None


def parse_pitcher_row(cells):
    """투수 한 행 파싱"""
    if len(cells) < 16:
        return None
    try:
        return {
            "name":   cells[0],
            "결과":   cells[2],
            "이닝":   cells[3],
            "볼넷":   int(cells[10]) if cells[10].isdigit() else 0,
            "사구":   int(cells[11]) if cells[11].isdigit() else 0,
            "삼진":   int(cells[12]) if cells[12].isdigit() else 0,
            "실점":   int(cells[15]) if cells[15].isdigit() else 0,
            "자책점": int(cells[16]) if cells[16].isdigit() else 0,
            "투구수": int(cells[17]) if cells[17].isdigit() else 0,
        }
    except Exception:
        return None


def parse_inning_scores(table):
    """이닝별 점수표 파싱 → (우리팀 이닝별득점, 상대팀 이닝별득점)"""
    rows = table.find_all("tr")
    if len(rows) < 3:
        return [], []

    def row_scores(row):
        cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
        scores = []
        for c in cells[1:]:
            try:
                scores.append(int(c))
            except Exception:
                scores.append(None)
        return cells[0] if cells else "", scores

    t1_name, t1_scores = row_scores(rows[1])
    t2_name, t2_scores = row_scores(rows[2])

    if t1_name == MY_TEAM:
        return t1_scores, t2_scores
    else:
        return t2_scores, t1_scores


def fetch_boxscore(game_idx):
    """박스스코어 전체 파싱"""
    url = (f"https://gameone.kr/club/info/schedule/boxscore"
           f"?club_idx={CLUB_IDX}&game_idx={game_idx}")
    html = get_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 5:
        return None

    our_innings, opp_innings = parse_inning_scores(tables[0])

    # 이닝 점수 테이블에서 첫 번째 팀 이름으로 배팅 테이블 순서 결정
    first_row = tables[0].find_all("tr")
    first_team = ""
    if len(first_row) > 1:
        first_team = first_row[1].find(["th","td"]).get_text(strip=True)

    if first_team == MY_TEAM:
        our_bt, opp_bt = tables[1], tables[2]
        our_pt, _      = tables[3], tables[4]
    else:
        opp_bt, our_bt = tables[1], tables[2]
        _,      our_pt = tables[3], tables[4]

    def parse_table(tbl):
        result = []
        for row in tbl.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["th","td"])]
            if not cells or cells[0] in ("합 계", "합계", ""):
                continue
            parsed = parse_batter_row(cells)
            if parsed:
                result.append(parsed)
        return result

    def parse_pitchers(tbl):
        result = []
        for row in tbl.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["th","td"])]
            if not cells:
                continue
            parsed = parse_pitcher_row(cells)
            if parsed:
                result.append(parsed)
        return result

    return {
        "our_batters":  parse_table(our_bt),
        "our_pitchers": parse_pitchers(our_pt),
        "our_innings":  our_innings,
        "opp_innings":  opp_innings,
    }


def find_hit_type(plays):
    """플레이 목록에서 최고 타구 유형 반환"""
    priority = ["홈런", "3루타", "2루타", "안타"]
    found = []
    for play in plays:
        for keyword, label in HIT_TYPE.items():
            if keyword in play:
                found.append(label)
        if any(x in play for x in ["중안", "좌안", "우안", "전안", "투안", "유안"]):
            found.append("안타")
    # 우선순위 높은 것만
    for p in priority:
        if p in found:
            return p
    return ""


def count_strikeouts(batters):
    total = 0
    for b in batters:
        for play in b["plays"]:
            if "삼진" in play:
                total += 1
    return total


def inning_scores_clean(scores):
    """이닝별 점수에서 None 제거하고 유효 이닝만 반환 (R/H/E/B 제외)"""
    clean = []
    for s in scores:
        if s is None:
            continue
        clean.append(s)
    # 마지막 4개(R H E B) 제거
    if len(clean) > 4:
        clean = clean[:-4]
    return clean


def generate_best_worst(game, bs):
    """Best/Worst bullet 자동 생성"""
    best, worst = [], []

    if not bs or not bs.get("our_batters"):
        best.append("상세 기록 미입력")
        worst.append("상세 기록 미입력")
        return best, worst

    our_batters  = bs["our_batters"]
    our_pitchers = bs["our_pitchers"]
    our_raw      = bs["our_innings"]
    opp_raw      = bs["opp_innings"]

    has_data = any(b["타수"] > 0 or b["안타"] > 0 for b in our_batters)
    if not has_data:
        best.append("상세 기록 미입력")
        worst.append("상세 기록 미입력")
        return best, worst

    our_inn = inning_scores_clean(our_raw)
    opp_inn = inning_scores_clean(opp_raw)

    # ── BEST ──────────────────────────────────────────────
    # 최다 안타 또는 최다 타점 타자
    hitters = [b for b in our_batters if b["안타"] > 0]
    if hitters:
        mvp = max(hitters, key=lambda b: (b["타점"], b["안타"], b["득점"]))
        hit_type = find_hit_type(mvp["plays"])
        desc = f"{mvp['name']} — {mvp['타수']}타수 {mvp['안타']}안타"
        if mvp["타점"] > 0:
            desc += f" {mvp['타점']}타점"
        if mvp["득점"] > 0:
            desc += f" {mvp['득점']}득점"
        if hit_type:
            desc += f" ({hit_type} 포함)"
        best.append(desc)

    # 3루타/홈런 기록한 선수 별도 언급
    big_hits = []
    for b in our_batters:
        ht = find_hit_type(b["plays"])
        if ht in ("3루타", "홈런"):
            big_hits.append(f"{b['name']} {ht}")
    if big_hits:
        best.append("장타 — " + ", ".join(big_hits))

    # 우리팀 최다 득점 이닝
    if our_inn:
        max_run = max(our_inn)
        if max_run >= 3:
            inn_no = our_inn.index(max_run) + 1
            best.append(f"{inn_no}회 {max_run}점 집중타 (최다득점이닝)")

    # 도루 많으면
    total_sb = sum(b["도루"] for b in our_batters)
    if total_sb >= 3:
        best.append(f"팀 도루 {total_sb}개 (기동력 발휘)")

    # 승리 시 우리 투수 칭찬
    if game.get("결과","").startswith("승") and our_pitchers:
        win_p = next((p for p in our_pitchers if p["결과"] == "승"), our_pitchers[0])
        best.append(f"{win_p['name']} 투수 {win_p['이닝']}이닝 {win_p['실점']}실점 {win_p['삼진']}탈삼진")

    # ── WORST ─────────────────────────────────────────────
    # 상대 최다 득점 이닝
    if opp_inn:
        max_opp = max(opp_inn)
        if max_opp >= 4:
            inn_no = opp_inn.index(max_opp) + 1
            worst.append(f"{inn_no}회 {max_opp}실점 집중 허용 (위기관리 필요)")

    # 볼넷 허용
    total_bb = sum(p["볼넷"] + p["사구"] for p in our_pitchers)
    if total_bb >= 5:
        worst.append(f"사사구 {total_bb}개 허용 (제구력 점검 필요)")
    elif total_bb >= 3:
        worst.append(f"사사구 {total_bb}개 허용")

    # 우리팀 삼진
    our_k = count_strikeouts(our_batters)
    if our_k >= 6:
        worst.append(f"삼진 {our_k}개 (타격 집중력 저하)")
    elif our_k >= 4:
        worst.append(f"삼진 {our_k}개")

    # 무안타 타자 (2타수 이상인데 안타 0)
    cold_batters = [b for b in our_batters if b["타수"] >= 2 and b["안타"] == 0]
    if len(cold_batters) >= 4:
        worst.append(f"다수 타자 무안타 ({len(cold_batters)}명 안타 없음)")

    # 무득점
    if game.get("우리팀_점수", 0) == 0:
        worst.append("무득점 — 득점 기회 연결 실패")

    # 콜드 패배
    if "콜드" in game.get("결과","") and "패" in game.get("결과",""):
        diff = game.get("상대팀_점수",0) - game.get("우리팀_점수",0)
        worst.append(f"콜드 패배 ({diff}점 차) — 집중력 회복 필요")

    if not best:
        best.append(f"{game.get('우리팀_점수',0)}점 득점")
    if not worst:
        worst.append(f"상대에게 {game.get('상대팀_점수',0)}점 허용")

    return best, worst
