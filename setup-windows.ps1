# 교보 라이브러리 워커 — 원클릭 설치 / 갱신 부트스트랩
# 윈도우 상태(Python·코드·워커)를 읽어 부족한 것만 자동 설치하고, 서버에서 최신 코드를 받는다.
#
# 사용법: PowerShell 에 한 줄 —
#   irm https://redcodeme.synology.me/kyobo/setup-windows.ps1 | iex
#
$ErrorActionPreference = "Stop"
$BASE = "https://redcodeme.synology.me/kyobo"
function Step($m){ Write-Host "`n▶ $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "  ✓ $m" -ForegroundColor Green }
function Warn($m){ Write-Host "  ! $m" -ForegroundColor Yellow }

Write-Host "===== 교보 라이브러리 워커 설치 =====" -ForegroundColor Magenta

# ── 1) Python 상태 확인 → 없으면 winget 설치 ──
Step "Python 확인"
$py = $null
foreach($c in @("python","python3")){
    $g = Get-Command $c -ErrorAction SilentlyContinue
    if($g -and $g.Source -and (Test-Path $g.Source)){ $py = $g.Source; break }
}
if(-not $py){
    $cand = Get-Item "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if($cand){ $py = $cand.FullName }
}
if(-not $py){
    Warn "Python 없음 → winget 으로 설치 (잠시 걸립니다)"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
    $env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")
    $cand = Get-Item "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if($cand){ $py = $cand.FullName; Ok "Python 설치 완료: $py" }
    else { Warn "Python 설치는 됐으나 경로 인식 실패 — PowerShell 새로 열고 이 명령을 다시 실행하세요"; return }
} else { Ok "Python: $py" }

# ── 2) 서버에서 최신 워커 코드 받기 (.venv 는 보존) ──
Step "최신 워커 코드 다운로드 (서버=최신본)"
$root = Join-Path $env:LOCALAPPDATA "KyoboLibrary"
New-Item -ItemType Directory -Force -Path $root | Out-Null
$zip = Join-Path $env:TEMP "book-capture.zip"
Invoke-WebRequest -Uri "$BASE/book-capture.zip" -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $root -Force
$bc = Join-Path $root "book-capture"
Ok "코드 갱신: $bc"

# ── 3) 워커 설치 스크립트 실행 (venv·tesseract·태스크 등록·자동시작) ──
Step "워커 설치 (venv · tesseract · 자동시작 태스크)"
& powershell -ExecutionPolicy Bypass -File (Join-Path $bc "scripts\install-worker-windows.ps1")

Write-Host "`n===== ✅ 워커 설치/갱신 완료 =====" -ForegroundColor Green
Write-Host "워커는 죽어도 5초 내 자동 부활합니다(세션 켜둔 동안)." -ForegroundColor Gray
Write-Host "`n남은 1가지 — Tampermonkey 유저스크립트:" -ForegroundColor Yellow
Write-Host "  ① chrome://extensions → 개발자모드 ON → Tampermonkey 세부정보 → '사용자 스크립트 허용' ON"
Write-Host "  ② $BASE/userscript/sync-kyobo-library.user.js  설치"
Write-Host "  (자세히) $BASE/troubleshoot.html"
