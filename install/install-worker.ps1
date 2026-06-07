# Kyobo Library Worker - Windows bootstrap
# Run directly (no download), in PowerShell:
#   irm https://redcodeme.synology.me/kyobo/install/install-worker.ps1 | iex
# (ASCII + no BOM so irm|iex never chokes; Korean UI is in the main installer)

$ErrorActionPreference = "Stop"
# Allow running the .ps1 installer this process only (does not change machine policy)
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force } catch { }

Write-Host ""
Write-Host "=== Kyobo Library Worker - Windows Auto Install ===" -ForegroundColor Cyan
Write-Host ""

# 1) Locate book-capture (synced via OneDrive). $env:OneDrive resolves the real
#    OneDrive path regardless of its (possibly Korean) folder name.
$candidates = @(
    "$env:OneDrive\Claude\NAS\KyoboLibrary\book-capture",
    "$env:OneDriveConsumer\Claude\NAS\KyoboLibrary\book-capture",
    "$env:OneDriveCommercial\Claude\NAS\KyoboLibrary\book-capture",
    "$env:USERPROFILE\OneDrive\Claude\NAS\KyoboLibrary\book-capture"
)
$BC_DIR = $null
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $BC_DIR = $c; break } }
if (-not $BC_DIR) {
    Get-ChildItem "$env:USERPROFILE" -Directory -Filter "OneDrive*" -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Join-Path $_.FullName "Claude\NAS\KyoboLibrary\book-capture"
        if ((Test-Path $p) -and (-not $BC_DIR)) { $BC_DIR = $p }
    }
}
if (-not $BC_DIR) {
    # No OneDrive copy (general users) -> download the worker package from server.
    Write-Host "[..] book-capture not found locally - downloading from server" -ForegroundColor Yellow
    $staticBase = "https://redcodeme.synology.me/kyobo"
    try {
        if ((Invoke-WebRequest "http://192.168.10.205:8080/" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) {
            $staticBase = "http://192.168.10.205:8080"
        }
    } catch { }
    $zipUrl = "$staticBase/install/bookcapture.zip?t=$([DateTime]::Now.Ticks)"  # cache-bust
    $dest   = Join-Path $env:LOCALAPPDATA "KyoboLibrary\book-capture"
    $zip    = Join-Path $env:TEMP "bookcapture.zip"
    try {
        Write-Host "    from $zipUrl" -ForegroundColor DarkGray
        Invoke-WebRequest $zipUrl -OutFile $zip -UseBasicParsing
        # 재설치: 도는 워커가 파일을 잠그지 않도록 먼저 정지
        try { Stop-ScheduledTask -TaskName "KyoboBookcaptureWorker" -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 } catch { }
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        $BC_DIR = $dest
        Write-Host "[OK] worker downloaded: $BC_DIR" -ForegroundColor Green
    } catch {
        Write-Host "[X] worker download failed: $_" -ForegroundColor Red
        return
    }
} else {
    Write-Host "[OK] book-capture: $BC_DIR" -ForegroundColor Green
}

# 2) Auto-detect backend: LAN (9000) if reachable, else external (9443)
if (-not $env:KYOBO_BRIDGE_URL) {
    $lan = "http://192.168.10.205:9000"
    $ext = "https://redcodeme.synology.me:9443"
    $picked = $ext
    try {
        if ((Invoke-WebRequest "$lan/health" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200) { $picked = $lan }
    } catch { }
    $env:KYOBO_BRIDGE_URL = $picked
    Write-Host "[OK] backend auto-detected: $picked" -ForegroundColor Green
} else {
    Write-Host "[OK] backend (preset): $env:KYOBO_BRIDGE_URL" -ForegroundColor Green
}

# 3) Run the main installer (file execution; it carries the Korean UI + UTF-8 BOM)
$INSTALLER = Join-Path $BC_DIR "scripts\install-worker-windows.ps1"
if (-not (Test-Path $INSTALLER)) {
    Write-Host "[X] main installer not found: $INSTALLER" -ForegroundColor Red
    Write-Host "    (OneDrive sync incomplete?)" -ForegroundColor Yellow
    return
}
Write-Host "[..] running main installer" -ForegroundColor Green
Write-Host ""
& $INSTALLER -BridgeUrl $env:KYOBO_BRIDGE_URL

Write-Host ""
Write-Host "=== done. The worker should now be running in the background. ===" -ForegroundColor Cyan
