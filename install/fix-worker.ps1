# Kyobo Library Worker - status check & auto-fix (ASCII; safe for irm|iex)
#   irm https://redcodeme.synology.me/kyobo/install/fix-worker.ps1 | iex
$ErrorActionPreference = "Stop"
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force } catch {}
$TASK = "KyoboBookcaptureWorker"
Write-Host ""
Write-Host "=== Kyobo Worker - check and fix ===" -ForegroundColor Cyan

$t = Get-ScheduledTask -TaskName $TASK -ErrorAction SilentlyContinue
if (-not $t) {
    Write-Host "[X] Worker is NOT installed. Run the installer first:" -ForegroundColor Red
    Write-Host "    https://redcodeme.synology.me/kyobo/install/install-worker.cmd" -ForegroundColor Yellow
    Write-Host ""; Read-Host "Press Enter to close"; return
}

# 1) Harden settings: no time limit, auto-restart, run on battery
try {
    $t.Settings.ExecutionTimeLimit         = 'PT0S'
    $t.Settings.RestartCount               = 9999
    $t.Settings.RestartInterval            = 'PT1M'
    $t.Settings.DisallowStartIfOnBatteries = $false
    $t.Settings.StopIfGoingOnBatteries     = $false
    $t | Set-ScheduledTask | Out-Null
    Write-Host "[OK] settings hardened (unlimited runtime + auto-restart)" -ForegroundColor Green
} catch { Write-Host "[!] settings update skipped: $_" -ForegroundColor Yellow }

# 2) Enable + start
try { Enable-ScheduledTask -TaskName $TASK | Out-Null } catch {}
if ((Get-ScheduledTask -TaskName $TASK).State -ne 'Running') {
    try { Start-ScheduledTask -TaskName $TASK } catch {}
}
Start-Sleep -Seconds 3
Write-Host ("[OK] task state: " + (Get-ScheduledTask -TaskName $TASK).State) -ForegroundColor Green

# 3) Verify the server (bridge) sees the worker heartbeat
$base = $env:KYOBO_BRIDGE_URL
if (-not $base) {
    $base = "https://redcodeme.synology.me:9443"
    try { if ((Invoke-WebRequest "http://192.168.10.205:9000/health" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) { $base = "http://192.168.10.205:9000" } } catch {}
}
Write-Host "[..] checking server heartbeat (up to ~18s)..." -ForegroundColor DarkGray
$alive = $false
for ($i = 0; $i -lt 6; $i++) {
    Start-Sleep -Seconds 3
    try {
        $s = Invoke-RestMethod "$base/api/worker/status" -TimeoutSec 5
        if ($s.alive) {
            $ago = [math]::Round([double]$s.last_ping_ago_sec, 1)
            Write-Host ("[OK] server sees the worker (last ping " + $ago + "s ago, host " + $s.known.hostname + ")") -ForegroundColor Green
            $alive = $true; break
        }
    } catch {}
}
Write-Host ""
if ($alive) {
    Write-Host "=== ALL GOOD. Now create a capture job in the web UI - the worker will pick it up. ===" -ForegroundColor Cyan
} else {
    Write-Host "[!] No heartbeat yet. See the real error by running the worker in foreground:" -ForegroundColor Yellow
    Write-Host '    cd "$env:LOCALAPPDATA\KyoboLibrary\book-capture"' -ForegroundColor Gray
    Write-Host '    .\.venv\Scripts\python.exe -m bookcapture worker --interval 5' -ForegroundColor Gray
    Write-Host "    or re-run install-worker.cmd to reinstall." -ForegroundColor Gray
}
Write-Host ""
Read-Host "Press Enter to close"
