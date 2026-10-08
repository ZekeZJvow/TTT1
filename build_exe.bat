@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo   A股人气雷达 - 打包脚本
echo ============================================================
echo.

cd /d "%~dp0"

set PY=venv\Scripts\python.exe
if not exist "%PY%" (
    echo [错误] 找不到虚拟环境：%PY%
    echo 请先执行：python -m venv venv
    pause
    exit /b 1
)

echo [1/3] 清理上次构建...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "A股人气雷达.spec" del /q "A股人气雷达.spec"

echo [2/3] 开始打包（首次约 2-5 分钟）...
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name "A股人气雷达" ^
  --icon "icon.ico" ^
  --add-data "index.html;." ^
  --add-data "app.js;." ^
  --add-data "styles.css;." ^
  --add-data "icon.ico;." ^
  --add-data "echarts.min.js;." ^
  --add-data "schema.sql;." ^
  --add-data "deploy/mysql_schema.sql;." ^
  --add-data "tools/backfill_hotlist.py;." ^
  --collect-data certifi ^
  --hidden-import flask ^
  --hidden-import flask_cors ^
  --hidden-import urllib3 ^
  --hidden-import requests ^
  --hidden-import screener ^
  --hidden-import stock_data ^
  --hidden-import market_db ^
  --hidden-import scheduler ^
  --hidden-import notifier ^
  --hidden-import backfill_hotlist ^
  --hidden-import openpyxl ^
  --collect-data openpyxl ^
  app_entry.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上面的日志
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo.
dir /b dist
echo.
echo 输出文件：dist\A股人气雷达.exe
pause
