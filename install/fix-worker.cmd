@echo off
chcp 65001 >nul
title Kyobo Library Worker - Check ^& Fix
echo.
echo  Kyobo Library Worker - checking and fixing the background worker...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://redcodeme.synology.me/kyobo/install/fix-worker.ps1 | iex"
echo.
echo  Done. You may close this window.
pause
