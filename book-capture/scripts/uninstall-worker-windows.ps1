# Kyobo Library Worker — Windows 등록 해제
$ErrorActionPreference = "SilentlyContinue"
$TASK_NAME = "KyoboBookcaptureWorker"

if (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TASK_NAME
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "✓ Task '$TASK_NAME' 제거 완료" -ForegroundColor Green
} else {
    Write-Host "! Task '$TASK_NAME' 없음 (이미 제거됨)" -ForegroundColor Yellow
}

# 잔여 프로세스 정리
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*bookcapture*worker*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Host "✓ PID $($_.Id) 종료" }
