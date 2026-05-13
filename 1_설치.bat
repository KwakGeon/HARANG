@echo off
chcp 65001 > nul
echo [1단계] 필요한 패키지 설치 중...
python -m pip install -r requirements.txt
echo.
echo 설치 완료! 이제 2_데이터수집.bat 을 실행하세요.
pause
