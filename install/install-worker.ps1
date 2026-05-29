# Kyobo Library Worker · Windows 원클릭 설치 (PowerShell)
#
# 사용 (PowerShell 에서):
#   irm http://192.168.10.205:8080/install/install-worker.ps1 | iex
#
# (iwr/Invoke-RestMethod 로 받아서 즉시 실행)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  📚  Kyobo Library Worker · Windows 자동 설치               ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# 1) OneDrive 안 book-capture 자동 탐색
$candidates = @(
    "$env:USERPROFILE\OneDrive\Claude\NAS\KyoboLibrary\book-capture",
    "$env:USERPROFILE\OneDrive - Personal\Claude\NAS\KyoboLibrary\book-capture",
    "$env:USERPROFILE\OneDrive - 개인\Claude\NAS\KyoboLibrary\book-capture",
    "$env:OneDrive\Claude\NAS\KyoboLibrary\book-capture",
    "$env:OneDriveConsumer\Claude\NAS\KyoboLibrary\book-capture"
)

$BC_DIR = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $BC_DIR = $c; break }
}

if (-not $BC_DIR) {
    Write-Host "✗ book-capture 폴더를 못 찾았습니다. 시도한 경로:" -ForegroundColor Red
    foreach ($c in $candidates) { Write-Host "    - $c" }
    Write-Host ""
    Write-Host "OneDrive 동기화 완료 또는 NAS/KyoboLibrary 다운로드 확인 후 다시 시도." -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ book-capture 발견: $BC_DIR" -ForegroundColor Green

# 2) 메인 설치
$INSTALLER = Join-Path $BC_DIR "scripts\install-worker-windows.ps1"
if (-not (Test-Path $INSTALLER)) {
    Write-Host "✗ 설치 스크립트 없음: $INSTALLER" -ForegroundColor Red
    Write-Host "  OneDrive 동기화 누락 가능성." -ForegroundColor Yellow
    exit 1
}

Write-Host "▶ 메인 설치 스크립트 실행" -ForegroundColor Green
Write-Host ""
& $INSTALLER

Write-Host ""
Write-Host "════════════════════════════════════════════════════════"
Write-Host "✓ 설치 완료. 메인 페이지로 가서 [📊 분석 시작] 누르면 자동 처리됩니다."
Write-Host "  http://192.168.10.205:8080/"
Write-Host "════════════════════════════════════════════════════════"
