# Kyobo 워커 자동-재시작 래퍼.
# scheduled task 가 이 스크립트를 (숨김으로) 실행한다. 워커 프로세스가 어떤 이유로
# 종료되면(크래시·정상종료 무관) 5초 뒤 자동으로 다시 띄운다. 모든 출력은 로그에 기록.
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BC_DIR     = Split-Path -Parent $SCRIPT_DIR
$VENV_PY    = Join-Path $BC_DIR ".venv\Scripts\python.exe"
if (-not (Test-Path $VENV_PY)) { $VENV_PY = "python" }   # venv 없으면 시스템 python

$LOG_DIR = Join-Path $env:LOCALAPPDATA "kyobo-library"
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }
$LOG = Join-Path $LOG_DIR "worker.out.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -Append -Encoding utf8 $LOG
}

Log "[run-worker] 래퍼 시작 — python=$VENV_PY"
while ($true) {
    Log "[run-worker] 워커 기동 (bookcapture worker --interval 5)"
    try {
        & $VENV_PY -m bookcapture worker --interval 5 *>> $LOG 2>&1
        Log "[run-worker] 워커 종료 (exit=$LASTEXITCODE) → 5초 후 재시작"
    } catch {
        Log "[run-worker] 워커 예외: $_ → 5초 후 재시작"
    }
    Start-Sleep -Seconds 5
}
