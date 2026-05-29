# 외부 접근 설정 (Web Station + DSM Reverse Proxy)

LAN 외부 (VPN 끊긴 환경 등) 에서 `https://redcodeme.synology.me/kyobo/` 로 접근하기 위한 설정.

> **중요 — Synology DSM 의 Reverse Proxy 는 URL Path 분기를 지원하지 않습니다.**
> 같은 호스트네임의 같은 포트 (443) 안에서 `/api/*` 만 별도로 라우팅하는 게 불가능.
> 그래서 **백엔드를 다른 포트(9443)** 로 매핑.

## 결과 매핑

| 외부 URL | 내부 매핑 | 역할 |
|---|---|---|
| `https://redcodeme.synology.me/` | `/volume1/web/` (Web Station, 443) | 메인 NAS 페이지 (MyWeb) |
| `https://redcodeme.synology.me/kyobo/` | `/volume1/web/kyobo/` (Web Station, 443) | 정적 KyoboLibrary 메인 |
| `https://redcodeme.synology.me/kyobo/install/...` | 같이 | install 스크립트 다운로드 |
| **`https://redcodeme.synology.me:9443/`** | `localhost:9000` (Reverse Proxy) | **kyobo-bridge 백엔드** |

LAN 직접 접근은 그대로:
- `http://192.168.10.205:8080/` — nginx 컨테이너 (변동 없음)
- `http://192.168.10.205:9000` — kyobo-bridge (변동 없음)

## 1. Web Station 정적 배포 (자동)

`./deploy.sh --static` 또는 `./deploy.sh` 실행 시 자동으로 두 곳 rsync:
- `/volume1/docker/web-apps/kyobo-library/` (LAN nginx 컨테이너 마운트)
- `/volume1/web/kyobo/` (Web Station — HTTPS 80/443 서빙)

→ 별도 설정 없이 deploy.sh 한 번이면 `redcodeme.synology.me/kyobo/` 에 메인 페이지 노출.

## 2. DSM Reverse Proxy 설정 (사용자 직접, 한 번만)

DSM 제어판 → **로그인 포털 → 고급 → Reverse Proxy** → **[생성]**:

### 일반 탭

| 항목 | 값 |
|---|---|
| 역방향 프록시 이름 | `Kyobo Bridge API` |
| 소스 프로토콜 | HTTPS |
| 소스 호스트 이름 | `redcodeme.synology.me` |
| **소스 포트** | **`9443`** ← 443 은 Web Station 이 사용 중이라 다른 포트 필수 |
| HSTS 활성화 | 체크 |
| 액세스 제어 프로파일 | 구성되지 않음 |
| 대상 프로토콜 | HTTP |
| 대상 호스트 이름 | `localhost` |
| 대상 포트 | `9000` |

### 고급 설정 탭
- 기본값 그대로 (시간 제한 60·60·60, HTTP 1.1, 오류 페이지 사용)
- ⚠ Synology DSM 의 Reverse Proxy 에는 **URL Path 필드가 없음** — path 분기 미지원

저장 후 즉시 적용.

## 3. 라우터·방화벽 — 9443 외부 노출

### 3.1 Synology 방화벽
DSM → 제어판 → 보안 → 방화벽 → 9443 TCP 허용 규칙 추가 (모든 원본 IP).

### 3.2 공유기 NAT/포트포워딩
공유기 관리 페이지에서:
- 외부 포트 `9443` → 내부 `192.168.10.205:9443`

(NAS.md 의 기존 외부 포트는 80/443/8080/8282 등. 9443 추가 필요)

## 4. 검증

설정 후 외부 환경 (모바일 LTE / 외부 PC) 에서:

```bash
# 메인 페이지 (Web Station)
curl -I https://redcodeme.synology.me/
# → HTTP/2 200

# KyoboLibrary 정적
curl -I https://redcodeme.synology.me/kyobo/
# → HTTP/2 200

# 백엔드 (Reverse Proxy)
curl https://redcodeme.synology.me:9443/health
# → {"status":"ok","service":"kyobo-bridge",...}

# 백엔드 books API
curl https://redcodeme.synology.me:9443/api/library/books | head -c 200
# → {"books":[{"id":...},...]
```

브라우저로 `https://redcodeme.synology.me/kyobo/` 접속 → 카드 클릭 → [📊 분석 시작]
→ 정상 작동 시 `job #N · 대기 중` 박스 표시.

## 5. CORS

`kyobo-bridge/app/main.py` 의 `allow_origins` 에 외부 도메인 이미 포함:
```python
allow_origins=[
    ...
    "https://redcodeme.synology.me",
]
```

## 6. 한계·주의

- **워커는 여전히 사용자 Mac/PC 에 설치** — 외부 노출이 워커를 외부 머신에 옮기진 않음
- 외부 머신에서 [분석 시작] → 사용자 본인 Mac 의 워커가 잡아야 동작 (즉 본인 Mac 도 켜져 있어야)
- `/api/secrets/ai`, `/api/jobs/next/claim`, `/api/worker/ping` 은 **LAN-only 화이트리스트**
  - 외부 도메인 통해 호출 시 403 (워커가 외부 환경에서 실행되는 경우 작업 polling 불가)
  - 외부 워커 지원 필요하면 `_is_lan()` 화이트리스트 확장 또는 토큰 인증 도입 검토

## 7. 메인 NAS 페이지 카드 링크

`MyWeb/portal/index.html` 의 "도서 라이브러리" 카드는 상대 경로 `kyobo/` 사용 →
LAN/외부 모두 같은 도메인에서 자동 매핑. 별도 수정 불필요.
