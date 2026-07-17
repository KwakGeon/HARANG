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

# 선수 이름으로 오인될 수 있는 플레이 코드 모음
_PLAY_CODES = {
    "좌안", "중안", "우안", "투안", "유안", "전안", "1안", "2안", "3안",
    "중전안", "1내안", "2내안", "3내안",
    "좌선", "중선", "우선",
    "좌뜬", "중뜬", "우뜬", "투뜬", "포뜬", "유뜬", "1뜬", "2뜬", "3뜬",
    "좌플", "중플", "우플", "투플", "포플", "유플",
    "좌땅", "중땅", "우땅", "투땅", "포땅", "유땅", "1땅", "2땅", "3땅",
    "홈런", "삼진", "4구", "사구", "도루", "희타", "희비", "병살", "파울", "포일",
    "좌월2", "우월2", "중월2", "우중2", "좌중2",
    "좌월3", "우월3", "중월3", "우중3", "좌중3",
}
_PLAY_SUBSTRINGS = (
    "안타", "삼진", "홈런", "실책", "희타", "희비",
    "도루", "주자", "사구", "몸맞", "병살", "파울", "아웃",
)
# 플레이 코드 끝 글자 패턴 (중전안→안, 좌뜬→뜬 등)
_PLAY_END = frozenset("안뜬땅선플")


def _is_reach_play(play):
    """타자가 비히트 출루한 플레이 판별 (실책·R출루·낫아웃)"""
    if not play or "송구" in play:
        return False
    return play.endswith("실") or play.endswith("R") or "낫아웃" in play


def _is_play(text):
    """텍스트가 플레이 기록인지 판별 (True면 선수 이름이 아님)"""
    if not text:
        return True
    if "," in text:
        return True
    if text in _PLAY_CODES:
        return True
    if any(s in text for s in _PLAY_SUBSTRINGS):
        return True
    # "투땅R" 등 플레이 코드에 접미사가 붙은 변형
    if any(text.startswith(code) for code in _PLAY_CODES):
        return True
    # 2자 이상이고 플레이 종류 끝 글자로 끝나는 경우 (중전안, 1내안 등)
    if len(text) >= 2 and text[-1] in _PLAY_END:
        return True
    return False


def _likely_name(text):
    """선수 이름일 가능성이 높은지 판별"""
    return bool(text) and len(text) >= 2 and not _is_play(text)


# 배팅순서 앞글자로 쓰이는 포지션 한 글자 (한글/한자)
_POS_CHARS = re.compile(r'^[투포유좌중우一二三四五六七八九十中左右]')


def clean_player_name(raw):
    """'4유김철영(23)' 형식에서 '김철영(23)'만 추출"""
    if not raw:
        return raw
    s = re.sub(r'^\d+', '', raw)      # 선두 숫자(배팅 순서) 제거
    s = _POS_CHARS.sub('', s)          # 포지션 한 글자 제거
    return s.strip() if s.strip() else raw


def parse_batter_row(cells):
    """타자 한 행 파싱 — 테이블 구조(A/B/C)를 자동 감지해 이름 추출"""
    if len(cells) < 11:
        return None
    try:
        if _likely_name(cells[2]):
            # 구조 A: [번호, 포지션, 이름, ?, 플레이..., 통계]
            name  = cells[2]
            plays = [p.strip() for p in cells[4:-7] if p.strip()]
        elif _likely_name(cells[1]):
            # 구조 B: [포지션, 이름, 플레이..., 통계]
            name  = cells[1]
            plays = [p.strip() for p in cells[2:-7] if p.strip()]
        else:
            # 구조 C: [배팅순서+포지션+이름, 플레이..., 통계]
            name  = clean_player_name(cells[0])
            plays = [p.strip() for p in cells[1:-7] if p.strip()]
        stats = cells[-7:-2]
        return {
            "name": name,
            "pos":  cells[1],
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
    """Best/Worst bullet 자동 생성 (개인 성적 기준)"""
    best, worst = [], []

    if not bs or not bs.get("our_batters"):
        best.append("상세 기록 미입력")
        worst.append("상세 기록 미입력")
        return best, worst

    our_batters  = bs["our_batters"]
    our_pitchers = bs["our_pitchers"]

    has_data = any(b["타수"] > 0 or b["안타"] > 0 for b in our_batters)
    if not has_data:
        best.append("상세 기록 미입력")
        worst.append("상세 기록 미입력")
        return best, worst

    # ── BEST ──────────────────────────────────────────────
    mentioned = set()

    # 최고 타자 (타점 > 안타 > 득점 순)
    hitters = [b for b in our_batters if b["안타"] > 0]
    if hitters:
        mvp = max(hitters, key=lambda b: (b["타점"], b["안타"], b["득점"]))
        ht = find_hit_type(mvp["plays"])
        desc = f"{mvp['name']} — {mvp['타수']}타수 {mvp['안타']}안타"
        if mvp["타점"] > 0:
            desc += f" {mvp['타점']}타점"
        if mvp["득점"] > 0:
            desc += f" {mvp['득점']}득점"
        if ht:
            desc += f" ({ht} 포함)"
        best.append(desc)
        mentioned.add(mvp["name"])

        # 2안타 이상 or 2타점 이상인 다른 선수 (최대 2명)
        others = sorted(
            [b for b in hitters if b["name"] not in mentioned and (b["안타"] >= 2 or b["타점"] >= 2)],
            key=lambda b: (b["타점"], b["안타"]), reverse=True
        )
        for b in others[:2]:
            ht2 = find_hit_type(b["plays"])
            d = f"{b['name']} — {b['타수']}타수 {b['안타']}안타"
            if b["타점"] > 0:
                d += f" {b['타점']}타점"
            if ht2:
                d += f" ({ht2} 포함)"
            best.append(d)
            mentioned.add(b["name"])

    # 홈런/3루타 (이미 언급된 선수 제외)
    big_hits = []
    for b in our_batters:
        ht = find_hit_type(b["plays"])
        if ht in ("3루타", "홈런") and b["name"] not in mentioned:
            big_hits.append(f"{b['name']} {ht}")
    if big_hits:
        best.append("장타 — " + ", ".join(big_hits))

    # 도루 2개 이상 개인
    for b in our_batters:
        if b["도루"] >= 2:
            best.append(f"{b['name']} 도루 {b['도루']}개 (기동력)")

    # 투수: 승리 투수 or 호투 (투구수 20+ & 실점 2 이하)
    if our_pitchers:
        win_p = next((p for p in our_pitchers if p["결과"] == "승"), None)
        if win_p:
            best.append(f"{win_p['name']} — {win_p['이닝']}이닝 {win_p['실점']}실점 {win_p['삼진']}탈삼진 (승)")
        else:
            good = [p for p in our_pitchers if p["실점"] <= 2 and p["투구수"] >= 20]
            if good:
                ace = min(good, key=lambda p: p["실점"])
                best.append(f"{ace['name']} — {ace['이닝']}이닝 {ace['실점']}실점 {ace['삼진']}탈삼진 (호투)")

    # ── WORST ─────────────────────────────────────────────
    # 무안타 타자 (2타수 이상)
    cold = [b for b in our_batters if b["타수"] >= 2 and b["안타"] == 0]
    if cold:
        names = ", ".join(b["name"] for b in cold[:4])
        suffix = f" 등 {len(cold)}명" if len(cold) > 4 else f" ({len(cold)}명)"
        worst.append(f"무안타 — {names}{suffix}")

    # 삼진 2개 이상 타자
    k_list = []
    for b in our_batters:
        k = sum(1 for p in b["plays"] if "삼진" in p)
        if k >= 2:
            k_list.append((b["name"], k))
    if k_list:
        k_list.sort(key=lambda x: -x[1])
        worst.append("삼진 — " + ", ".join(f"{n}({k}K)" for n, k in k_list[:3]))

    # 실점 많은 투수 (4실점 이상 or 사사구 4개 이상)
    if our_pitchers:
        worst_p = max(our_pitchers, key=lambda p: p["실점"])
        bb = worst_p["볼넷"] + worst_p["사구"]
        if worst_p["실점"] >= 4:
            worst.append(f"{worst_p['name']} — {worst_p['이닝']}이닝 {worst_p['실점']}실점 {bb}사사구")
        elif bb >= 4:
            worst.append(f"{worst_p['name']} — {bb}사사구 허용 (제구력 점검)")

        # 패전 투수 (위에서 언급 안 된 경우)
        lose_p = next((p for p in our_pitchers if p["결과"] == "패"), None)
        if lose_p and not any(lose_p["name"] in w for w in worst):
            worst.append(f"{lose_p['name']} 패전 — {lose_p['이닝']}이닝 {lose_p['실점']}실점")

    # 콜드 패배
    if "콜드" in game.get("결과","") and "패" in game.get("결과",""):
        diff = game.get("상대팀_점수",0) - game.get("우리팀_점수",0)
        worst.append(f"콜드 패배 ({diff}점 차)")

    if not best:
        best.append(f"{game.get('우리팀_점수',0)}점 득점")
    if not worst:
        worst.append(f"상대에게 {game.get('상대팀_점수',0)}점 허용")

    return best, worst


# ── MVP 지표 추출 ─────────────────────────────────────────────

def _parse_hit_details(plays):
    """플레이 목록에서 홈런·3루타·2루타 개수 반환"""
    hr = tri = dbl = 0
    for p in plays:
        if "홈런" in p:
            hr += 1
        elif any(x in p for x in ["월3", "중3", "우중3", "좌중3"]):
            tri += 1
        elif any(x in p for x in ["월2", "중2", "우중2", "좌중2"]):
            dbl += 1
    return hr, tri, dbl


def extract_player_stats(bs):
    """박스스코어에서 선수별 세부 지표를 추출 (MVP 집계용)"""
    if not bs or not bs.get("our_batters"):
        return {"batters": [], "pitchers": [], "game_innings": 0}

    game_innings = len(inning_scores_clean(bs.get("our_innings", [])))
    if game_innings == 0:
        game_innings = len(inning_scores_clean(bs.get("opp_innings", [])))

    batters = []
    for b in bs["our_batters"]:
        name = b.get("name", "")
        if not name or len(name) < 2:
            continue
        if b["타수"] == 0 and b["안타"] == 0:
            continue
        plays = b.get("plays", [])
        볼넷 = sum(1 for p in plays if "4구" in p)
        사구 = sum(1 for p in plays if "몸맞" in p)
        삼진 = sum(1 for p in plays if "삼진" in p)
        # 비히트 출루: 실책(실), R 출루(유땅R 등), 낫아웃 포함 / 송구실 제외
        실책_플레이 = [p for p in plays if _is_reach_play(p)]
        실책출루 = len(실책_플레이)
        hr, tri, dbl = _parse_hit_details(plays)
        batters.append({
            "name": name,
            "타수": b["타수"],
            "안타": b["안타"],
            "타점": b["타점"],
            "득점": b["득점"],
            "도루": b["도루"],
            "볼넷": 볼넷,
            "사구": 사구,
            "삼진": 삼진,
            "실책출루": 실책출루,
            "실책_플레이": 실책_플레이,
            "홈런": hr,
            "삼루타": tri,
            "이루타": dbl,
        })

    pitchers = []
    for p in bs.get("our_pitchers", []):
        name = p.get("name", "")
        if not name or len(name) < 2:
            continue
        pitchers.append({
            "name": name,
            "삼진": p.get("삼진", 0),
            "자책점": p.get("자책점", 0),
            "실점": p.get("실점", 0),
        })

    return {
        "batters": batters,
        "pitchers": pitchers,
        "game_innings": game_innings,
    }
