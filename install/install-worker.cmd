@echo off
chcp 65001 >nul
title Kyobo Library Worker Setup
echo.
echo  Kyobo Library Worker - installing...
echo  (If a User Account Control prompt appears for Tesseract, click YES)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://redcodeme.synology.me/kyobo/install/install-worker.ps1 | iex"
echo.
echo  Finished. You may close this window.
pause
