@echo off
setlocal
cd /d "%~dp0"
docker compose up -d postgres
if errorlevel 1 exit /b %errorlevel%
docker compose exec -T postgres psql -U onboarding -d onboarding -v ON_ERROR_STOP=1 < scripts\demo-data-del.sql
if errorlevel 1 exit /b %errorlevel%
echo.
echo Demo data removed. The cabinet is empty again.
