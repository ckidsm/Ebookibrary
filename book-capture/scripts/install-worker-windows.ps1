# ─────────────────────────────────────────────────────────────
# Kyobo Library Worker — Windows 자동 설치 (PowerShell)
#
# 한 번 실행하면:
#   1) Python 점검 (없으면 안내)
#   2) venv 생성 + 의존성 설치 (Pillow, pytesseract, pyautogui)
#   3) Tesseract 설치 권유 (winget)
#   4) Task Scheduler 등록 — 로그온 시 자동 시작 + KeepAlive
#   5) 즉시 백그라운드 시작
#
# 정지·제거: uninstall-worker-windows.ps1
# ─────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BC_DIR = Split-Path -Parent $SCRIPT_DIR
$TASK_NAME = "KyoboBookcaptureWorker"
$VENV_DIR = Join-Path $BC_DIR ".venv"
$VENV_PY  = Join-Path $VENV_DIR "Scripts\python.exe"
$LOG_DIR  = Join-Path $env:LOCALAPPDATA "kyobo-library"

function Step($msg)  { Write-Host "▶ $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "! $msg" -ForegroundColor Yellow }
function Die($msg)   { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

# 0) 사전 점검
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    $py = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $py) {
    Die "Python 미설치. https://www.python.org/downloads/ 또는 'winget install Python.Python.3.12' 후 다시 시도."
}

# 1) venv
if (-not (Test-Path $VENV_PY)) {
    Step "venv 생성: $VENV_DIR"
    & $py.Source -m venv $VENV_DIR
    Step "의존성 설치 (Pillow, pytesseract, pyautogui)"
    & $VENV_PY -m pip install --quiet --upgrade pip
    & $VENV_PY -m pip install --quiet -r (Join-Path $BC_DIR "requirements.txt")
    & $VENV_PY -m pip install --quiet pyautogui    # Windows 캡처·키 입력
} else {
    Step "venv 이미 존재: $VENV_DIR"
}

# 2) Tesseract 점검
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tess) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Warn "Tesseract 미설치 — winget 으로 설치 시도 (한국어팩 포함)"
        try {
            winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements
        } catch {
            Warn "winget 설치 실패. 수동: winget install UB-Mannheim.TesseractOCR"
        }
    } else {
        Warn "Tesseract 미설치 — 수동 설치: https://github.com/UB-Mannheim/tesseract/wiki"
    }
}

# 3) 로그 폴더
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }
$LOG_OUT = Join-Path $LOG_DIR "worker.out.log"

# 4) Task Scheduler 등록
Step "Task Scheduler 등록: $TASK_NAME"
$action = New-ScheduledTaskAction `
    -Execute $VENV_PY `
    -Argument "-m bookcapture worker --interval 5" `
    -WorkingDirectory $BC_DIR

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 9999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

# 기존 등록 정리
if (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue) {
    Step "기존 등록 해제"
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Kyobo Library worker — book-capture polling" | Out-Null

# 5) 즉시 시작
Step "즉시 시작"
Start-ScheduledTask -TaskName $TASK_NAME
Start-Sleep -Seconds 2

# 6) 상태
$task = Get-ScheduledTask -TaskName $TASK_NAME
$info = $task | Get-ScheduledTaskInfo
Write-Host ""
Write-Host "State: $($task.State)" -ForegroundColor Cyan
Write-Host "LastRun: $($info.LastRunTime)" -ForegroundColor Cyan
Write-Host "로그: $LOG_OUT"
Write-Host ""
Write-Host "✓ worker 백그라운드 등록 완료" -ForegroundColor Green
Write-Host "  로그온 시 자동 시작, 죽으면 1분 후 재시작."
Write-Host "  정지·제거: $SCRIPT_DIR\uninstall-worker-windows.ps1"
