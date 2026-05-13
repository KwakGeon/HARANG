import requests
import ssl
import urllib3
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


_session = requests.Session()
_session.mount("https://", LegacySSLAdapter())

CLUB_IDX = 31310
MY_TEAM = "하랑 타이거즈"
BASE_URL = "https://gameone.kr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_page(url):
    try:
        resp = _session.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"  [오류] {url} 요청 실패: {e}")
        return None


def parse_game_row(row):
    try:
        tds = row.find_all("td")
        if len(tds) < 4:
            return None

        # TD[3]에 game div가 없으면 스킵 (미완료 경기)
        game_td = tds[3]
        game_div = game_td.find("div", class_="game")
        if not game_div:
            return None

        # 팀명 (span.team_name 2개)
        team_names = [s.get_text(strip=True) for s in game_td.find_all("span", class_="team_name")]
        # 점수 (span.score 2개)
        scores_raw = [s.get_text(strip=True) for s in game_td.find_all("span", class_="score")]

        if len(team_names) < 2 or len(scores_raw) < 2:
            return None

        try:
            score0 = int(scores_raw[0])
            score1 = int(scores_raw[1])
        except ValueError:
            return None

        # 내 팀이 team_names[0]인지 [1]인지 확인
        if team_names[0] == MY_TEAM:
            my_score = score0
            opp_name = team_names[1]
            opp_score = score1
        elif team_names[1] == MY_TEAM:
            opp_name = team_names[0]
            opp_score = score0
            my_score = score1
        else:
            # 내 팀이 없는 행은 스킵
            return None

        # 승/패/무 판정
        if my_score > opp_score:
            wld = "승"
        elif my_score < opp_score:
            wld = "패"
        else:
            wld = "무"

        # 콜드게임 여부
        exp_win = game_td.find("span", class_="exp_win")
        if exp_win and "콜드" in exp_win.get_text(strip=True):
            wld += "(콜드)"

        # 날짜 (TD[0])
        date_str = tds[0].get_text(strip=True)

        # 리그 (TD[1])
        league = tds[1].get_text(strip=True)

        # 구장 (TD[2])
        venue = tds[2].get_text(strip=True)

        # 상대팀 club_idx (링크에서)
        opponent_idx = None
        for a in game_td.find_all("a", href=True):
            href = a["href"]
            if "club_idx=" in href and "club/?" in href:
                m = re.search(r"club_idx=(\d+)", href)
                if m and int(m.group(1)) != CLUB_IDX:
                    opponent_idx = int(m.group(1))

        # game_idx (BOX SCORE 링크에서)
        game_idx = None
        box_link = row.find("a", class_="boxscore")
        if box_link:
            m = re.search(r"game_idx=(\d+)", box_link.get("href", ""))
            if m:
                game_idx = int(m.group(1))

        return {
            "날짜": date_str,
            "상대팀": opp_name,
            "상대팀_idx": opponent_idx,
            "우리팀_점수": my_score,
            "상대팀_점수": opp_score,
            "결과": wld,
            "리그": league,
            "구장": venue,
            "game_idx": game_idx,
        }

    except Exception as e:
        print(f"  [파싱오류] {e}")
        return None


def parse_schedule_page(html):
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for row in soup.find_all("tr"):
        game = parse_game_row(row)
        if game:
            games.append(game)
    return games


def get_last_page(html):
    soup = BeautifulSoup(html, "html.parser")
    max_page = 1
    for a in soup.find_all("a", href=True):
        if "page=" in a["href"]:
            m = re.search(r"page=(\d+)", a["href"])
            if m:
                p = int(m.group(1))
                if p > max_page:
                    max_page = p
    return max_page


def scrape_season(season):
    print(f"\n[{season}시즌] 크롤링 시작...")
    all_games = []

    first_url = (
        f"{BASE_URL}/club/info/schedule/table"
        f"?season={season}&club_idx={CLUB_IDX}&game_type=0&lig_idx=0&group=0&month=0&page=1"
    )
    html = get_page(first_url)
    if not html:
        return []

    last_page = get_last_page(html)
    print(f"  총 {last_page} 페이지")

    games = parse_schedule_page(html)
    all_games.extend(games)
    print(f"  1페이지: {len(games)}경기 수집")

    for page in range(2, last_page + 1):
        url = (
            f"{BASE_URL}/club/info/schedule/table"
            f"?season={season}&club_idx={CLUB_IDX}&game_type=0&lig_idx=0&group=0&month=0&page={page}"
        )
        html = get_page(url)
        if not html:
            break
        games = parse_schedule_page(html)
        all_games.extend(games)
        print(f"  {page}페이지: {len(games)}경기 수집")
        time.sleep(0.8)

    return all_games


def main():
    import argparse

    parser = argparse.ArgumentParser(description="게임원 하랑 타이거즈 경기 기록 크롤러")
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2024, 2025, 2026],
        help="크롤링할 시즌 (예: 2024 2025 2026)",
    )
    args = parser.parse_args()

    all_games = []
    for season in args.seasons:
        games = scrape_season(season)
        for g in games:
            g["시즌"] = season
        all_games.extend(games)

    if not all_games:
        print("\n[경고] 수집된 경기 데이터가 없습니다.")
        return

    df = pd.DataFrame(all_games)
    df = df.drop_duplicates(subset=["game_idx"], keep="first")

    os.makedirs("data", exist_ok=True)
    df.to_csv("data/games.csv", index=False, encoding="utf-8-sig")

    print(f"\n완료! 총 {len(df)}경기 저장 → data/games.csv")
    print("\n[상대전적 미리보기]")

    summary = (
        df.groupby("상대팀")
        .apply(
            lambda g: pd.Series({
                "경기수": len(g),
                "승": int(g["결과"].str.contains("승").sum()),
                "패": int(g["결과"].str.contains("패").sum()),
                "무": int((g["결과"] == "무").sum()),
            })
        )
        .reset_index()
    )
    summary["승률"] = (summary["승"].astype(float) / summary["경기수"] * 100).round(1).astype(str) + "%"
    print(summary.sort_values("경기수", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
