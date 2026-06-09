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
#
# 원격(외부망) PC 면 백엔드 주소를 9443 으로:
#   .\install-worker-windows.ps1 -BridgeUrl "https://redcodeme.synology.me:9443"
# ─────────────────────────────────────────────────────────────

param(
    [string]$BridgeUrl = $(if ($env:KYOBO_BRIDGE_URL) { $env:KYOBO_BRIDGE_URL } else { "http://192.168.10.205:9000" })
)

$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BC_DIR = Split-Path -Parent $SCRIPT_DIR
$TASK_NAME = "KyoboBookcaptureWorker"
$VENV_DIR = Join-Path $BC_DIR ".venv"
$VENV_PY  = Join-Path $VENV_DIR "Scripts\python.exe"
$LOG_DIR  = Join-Path $env:LOCALAPPDATA "kyobo-library"

function Step($msg)  { Write-Host "▶ $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "! $msg" -ForegroundColor Yellow }
function Die($msg)   { Write-Host "✗ $msg" -ForegroundColor Red; throw $msg }

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path","Machine")
    $u = [Environment]::GetEnvironmentVariable("Path","User")
    $env:Path = (@($m,$u) | Where-Object { $_ }) -join ";"
}
function Find-Python {
    # 실 Python 만. MS Store 의 가짜 python stub(WindowsApps)은 제외.
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notlike "*WindowsApps*")) { return $c }
    $c = Get-Command python3 -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notlike "*WindowsApps*")) { return $c }
    foreach ($g in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                     "$env:ProgramFiles\Python3*\python.exe",
                     "C:\Python3*\python.exe")) {
        $f = Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($f) { return [PSCustomObject]@{ Source = $f.FullName } }
    }
    return $null
}

# -1) 관리자 권한 자동 상승 — 한글 언어팩(Program Files) + 작업 스케줄러 등록에 필요.
#     비관리자면 UAC 로 새 관리자 창에서 재실행하고 현재 창은 종료.
$scriptPath = $MyInvocation.MyCommand.Path
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Warn "관리자 권한으로 다시 실행합니다 — UAC 창이 뜨면 [예] 를 눌러주세요"
    try {
        Start-Process powershell -Verb RunAs -ArgumentList @(
            "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$scriptPath`"","-BridgeUrl","`"$BridgeUrl`""
        ) | Out-Null
        Write-Host ""
        Write-Host ">> 관리자 창에서 설치가 계속됩니다. 이 창은 닫으셔도 됩니다." -ForegroundColor Cyan
        return
    } catch {
        Warn "UAC 취소/실패 — 비관리자 모드로 계속 (한글 OCR·자동시작 일부 제한될 수 있음)"
    }
}

# 0) Python 점검 + 없으면 자동 설치 → 완료 대기 → PATH 갱신 → 재확인
$py = Find-Python
if (-not $py) {
    Warn "Python 미설치 — 자동 설치를 시작합니다 (수 분 소요, 닫지 마세요)"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Step "winget 으로 Python 3.12 설치 중..."
        try {
            & winget install --id Python.Python.3.12 -e --silent --scope user `
                --accept-package-agreements --accept-source-agreements | Out-Null
        } catch { Warn "winget 설치 경고: $_" }
        Refresh-Path; Start-Sleep -Seconds 3
        $py = Find-Python
    }
    if (-not $py) {
        Step "python.org 설치파일 다운로드 + 무인 설치 (완료까지 대기)"
        $pyUrl = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $pyExe = Join-Path $env:TEMP "python-3.12-setup.exe"
        try {
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe -UseBasicParsing
            Start-Process -FilePath $pyExe -Wait -ArgumentList `
                "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_launcher=1"
            Refresh-Path; Start-Sleep -Seconds 3
            $py = Find-Python
        } catch {
            Die "Python 자동 설치 실패: $_  (수동: https://www.python.org/downloads/ 설치 후 다시 실행)"
        }
    }
    if (-not $py) {
        Die "Python 설치는 됐으나 인식 실패 — PC 재부팅 후 다시 실행하거나 새 PowerShell 창에서 재시도."
    }
    Step "Python 준비됨: $($py.Source)"
} else {
    Step "Python 확인: $($py.Source)"
}

# 1) venv + 의존성 (pyautogui 불필요 — win_app 은 ctypes+PIL 만 사용)
if (-not (Test-Path $VENV_PY)) {
    Step "venv 생성: $VENV_DIR"
    & $py.Source -m venv $VENV_DIR
} else {
    Step "venv 이미 존재: $VENV_DIR"
}
Step "의존성 설치/확인 (Pillow, pytesseract) — 진행이 보입니다"
& $VENV_PY -m pip install --disable-pip-version-check --no-input --upgrade pip
& $VENV_PY -m pip install --disable-pip-version-check --no-input -r (Join-Path $BC_DIR "requirements.txt")

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

# 2-1) 한국어/영어 traineddata 보장 — winget 기본설치는 kor 가 빠질 수 있음
Step "Tesseract 한국어/영어 언어팩 확인"
$tessExe = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
if (-not $tessExe) {
    foreach ($p in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                     "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe")) {
        if (Test-Path $p) { $tessExe = $p; break }
    }
}
if ($tessExe) {
    $tessData = Join-Path (Split-Path -Parent $tessExe) "tessdata"
    if (-not (Test-Path $tessData)) { New-Item -ItemType Directory -Path $tessData | Out-Null }
    foreach ($lang in @("kor", "eng")) {
        $dst = Join-Path $tessData "$lang.traineddata"
        if (-not (Test-Path $dst)) {
            $url = "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
            Warn "$lang.traineddata 없음 — 다운로드: $url"
            try {
                Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
                Step "$lang.traineddata 설치 완료"
            } catch {
                Warn "$lang.traineddata 다운로드 실패 — 관리자 권한 또는 수동 배치 필요: $dst"
            }
        } else {
            Step "$lang.traineddata 존재 OK"
        }
    }
} else {
    Warn "tesseract.exe 경로 미확인 — 설치 후 kor/eng traineddata 수동 확인 필요"
}

# 2-2) 백엔드 주소 환경변수 (워커 + 자식 프로세스 capture-auto/upload 가 공유)
Step "백엔드 주소 설정: KYOBO_BRIDGE_URL=$BridgeUrl"
[Environment]::SetEnvironmentVariable("KYOBO_BRIDGE_URL", $BridgeUrl, "User")
$env:KYOBO_BRIDGE_URL = $BridgeUrl
# cp949 콘솔에서 한글/이모지 출력 깨짐·크래시 방지 (UTF-8 강제)
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
$env:PYTHONUTF8 = "1"

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
# 5분마다 반복 트리거 — 워커가 어떤 이유로 죽어도(정상종료 포함) 5분 내 자동 부활.
# (이미 실행 중이면 MultipleInstances=IgnoreNew 로 중복 안 띄움)
try {
    # RepetitionDuration 에 [TimeSpan]::MaxValue 를 주면 P99999999DT.. 로 직렬화돼
    # Register-ScheduledTask 가 "범위를 벗어난 값"(0x80041318)으로 거부함.
    # → 유한한 큰 값(10년)으로. 워커가 죽어도 5분 내 부활은 동일.
    $rep = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $trigger.Repetition = $rep.Repetition
} catch {
    Warn "반복 트리거 설정 실패(무시): $_"
}

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 9999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
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
