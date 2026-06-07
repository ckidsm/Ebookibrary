# Kyobo Worker - quick code update + restart (no admin needed)
# Run in PowerShell:
#   irm https://redcodeme.synology.me/kyobo/install/update-worker.ps1 | iex
$ErrorActionPreference = "Stop"
$task = "KyoboBookcaptureWorker"
$dest = Join-Path $env:LOCALAPPDATA "KyoboLibrary\book-capture"
$zip  = Join-Path $env:TEMP "bookcapture-update.zip"

Write-Host ""
Write-Host "=== Kyobo Worker - update worker code ===" -ForegroundColor Cyan

# pick backend static base (LAN if reachable, else external)
$staticBase = "https://redcodeme.synology.me/kyobo"
try { if ((Invoke-WebRequest "http://192.168.10.205:8080/" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) { $staticBase = "http://192.168.10.205:8080" } } catch { }

Write-Host "[..] stopping worker" -ForegroundColor Yellow
try { Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue } catch { }
Start-Sleep -Seconds 2

Write-Host "[..] downloading latest worker code" -ForegroundColor Yellow
Invoke-WebRequest "$staticBase/install/bookcapture.zip?t=$(Get-Random)" -OutFile $zip -UseBasicParsing
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }
Expand-Archive -Path $zip -DestinationPath $dest -Force
Write-Host "[OK] code updated: $dest" -ForegroundColor Green

Write-Host "[..] restarting worker" -ForegroundColor Yellow
try {
    Start-ScheduledTask -TaskName $task
    Write-Host "[OK] worker restarted." -ForegroundColor Green
} catch {
    Write-Host "[!] could not start task (maybe not installed yet) - run the full installer once:" -ForegroundColor Yellow
    Write-Host "    irm https://redcodeme.synology.me/kyobo/install/install-worker.ps1 | iex"
}

Write-Host ""
Write-Host "=== done. Now click [Analyze] on the web again. ===" -ForegroundColor Cyan
