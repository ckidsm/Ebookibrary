#!/usr/bin/env bash
# 교보 라이브러리 워커 — 우분투/리눅스(X11) 원클릭 설치
# 사용:  curl -fsSL https://redcodeme.synology.me/kyobo/setup-linux.sh | bash
set -e
BASE="https://redcodeme.synology.me/kyobo"
echo "===== 교보 라이브러리 워커 설치 (Linux X11) ====="

# 1) 시스템 패키지 — scrot(캡처) xdotool(키) python3 pip Pillow
echo "▶ 패키지 설치 (sudo 비밀번호 필요할 수 있음)"
sudo apt-get update -qq
sudo apt-get install -y -qq scrot xdotool python3 python3-pip python3-pil unzip curl

# 2) 워커 코드 다운로드(서버=최신) + 압축해제
echo "▶ 최신 워커 코드 다운로드"
mkdir -p "$HOME/kyobo"
curl -fsSL -o /tmp/book-capture.zip "$BASE/book-capture.zip"
rm -rf "$HOME/kyobo/book-capture"
unzip -oq /tmp/book-capture.zip -d "$HOME/kyobo"

# 3) Python 의존성(requests) — 사용자 영역
pip3 install --user -q requests || true

# 4) systemd 사용자 서비스 — GUI 로그인 시 자동시작 + 죽으면 5초 내 재시작
echo "▶ 자동시작 서비스 등록 (systemd --user)"
DISP="${DISPLAY:-:1}"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/kyobo-worker.service" <<EOF
[Unit]
Description=Kyobo capture worker (Linux X11)
After=graphical-session.target

[Service]
Environment=DISPLAY=$DISP
Environment=KYOBO_BRIDGE_URL=https://redcodeme.synology.me:9443
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=%h/kyobo/book-capture
ExecStart=/usr/bin/python3 -m bookcapture worker --interval 5
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now kyobo-worker

echo ""
echo "===== ✅ 워커 설치/시작 완료 (DISPLAY=$DISP) ====="
systemctl --user is-active kyobo-worker && echo "  워커 실행 중" || echo "  ! 상태 확인: systemctl --user status kyobo-worker"
echo ""
echo "남은 것:"
echo "  · Tampermonkey 유저스크립트 + '사용자 스크립트 허용'"
echo "  · 노트북 화면에 교보 [바로보기] 단일페이지 + F11 띄우기"
echo "  · 관리: systemctl --user {status|restart} kyobo-worker · journalctl --user -u kyobo-worker -f"
