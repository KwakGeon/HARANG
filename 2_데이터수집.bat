@echo off
chcp 65001 > nul
echo [2단계] 게임원에서 경기 데이터 수집 중...
echo (2024, 2025, 2026 시즌 전체 수집)
echo.
python scraper.py --seasons 2024 2025 2026
echo.
echo 완료! 이제 3_대시보드실행.bat 을 실행하세요.
pause
