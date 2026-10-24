@echo off
setlocal
cd /d "%~dp0"
docker compose run --rm api python -m onboarding.cli ingest
if errorlevel 1 exit /b %errorlevel%
docker compose run --rm api python -m onboarding.cli demo --reset --yes
if errorlevel 1 exit /b %errorlevel%
echo.
echo Demo data is ready. Open http://localhost:3000 and sign in with dev-hr-token.
