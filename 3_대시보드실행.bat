@echo off
chcp 65001 > nul
echo [3단계] 대시보드 실행 중...
echo 브라우저에서 http://localhost:8501 을 열어보세요.
echo (종료하려면 이 창을 닫거나 Ctrl+C)
echo.
python -m streamlit run dashboard.py
pause
