# 외부 접근 설정 (Web Station + DSM Reverse Proxy)

LAN 외부 (VPN 끊긴 환경 등) 에서 `https://redcodeme.synology.me/kyobo/` 로 접근하기 위한 설정.

## 결과 매핑

| 외부 URL | 내부 매핑 | 역할 |
|---|---|---|
| `https://redcodeme.synology.me/kyobo/` | `/volume1/web/kyobo/` (Web Station) | 정적 메인 페이지 |
| `https://redcodeme.synology.me/kyobo/install/...` | 같이 | install 스크립트 다운로드 |
| `https://redcodeme.synology.me/api/...` | `localhost:9000/...` (Reverse Proxy) | kyobo-bridge 백엔드 |

LAN 직접 접근은 그대로:
- `http://192.168.10.205:8080/` — nginx 컨테이너 (변동 없음)
- `http://192.168.10.205:9000` — kyobo-bridge (변동 없음)

## 1. Web Station 정적 배포 (자동)

`./deploy.sh --static` 또는 `./deploy.sh` 실행 시 자동으로 두 곳 rsync:
- `/volume1/docker/web-apps/kyobo-library/` (LAN nginx 컨테이너 마운트)
- `/volume1/web/kyobo/` (Web Station — HTTPS 80/443 서빙)

→ 별도 설정 없이 deploy.sh 한 번이면 `redcodeme.synology.me/kyobo/` 에 메인 페이지 노출.

## 2. DSM Reverse Proxy 설정 (사용자 직접, 한 번만)

DSM 제어판에서 **두 개의 reverse proxy 규칙** 추가:

### 2.1 메인 페이지 매핑 (선택, Web Station 으로 이미 됨)

Web Station 으로 충분하지만 깔끔한 URL 원하면:

| 항목 | 값 |
|---|---|
| 설명 | Kyobo Library (front) |
| 소스 프로토콜 | HTTPS |
| 소스 호스트 | `redcodeme.synology.me` |
| 소스 포트 | `443` |
| 활성 HSTS | (선택) |
| 대상 프로토콜 | HTTP |
| 대상 호스트 | `localhost` |
| 대상 포트 | `8080` |
| 사용자 정의 헤더 → WebSocket | 없음 |

### 2.2 백엔드 API 매핑 (필수)

| 항목 | 값 |
|---|---|
| 설명 | Kyobo Bridge (API) |
| 소스 프로토콜 | HTTPS |
| 소스 호스트 | `redcodeme.synology.me` |
| 소스 포트 | `443` |
| 대상 프로토콜 | HTTP |
| 대상 호스트 | `localhost` |
| 대상 포트 | `9000` |
| 사용자 정의 헤더 | 없음 (CORS 는 백엔드에서 처리) |
| **고급 → 위치(URL Path) 일치** | `/api` |

위 설정으로 `https://redcodeme.synology.me/api/*` → `localhost:9000/*` 매핑.

## 3. DSM 설정 화면 진입 경로

```
DSM 제어판
  → 로그인 포털
    → 고급
      → Reverse Proxy
        → [생성] 버튼 × 2
```

각 규칙 추가 후 저장 → 즉시 적용.

## 4. 검증

설정 후 외부 환경(모바일 LTE / 외부 PC)에서:

```bash
# 메인 페이지
curl -I https://redcodeme.synology.me/kyobo/
# → HTTP/2 200 (또는 308 redirect)

# 백엔드
curl https://redcodeme.synology.me/api/health
# → {"status":"ok","service":"kyobo-bridge",...}
```

브라우저로 접속해서 카드 클릭 → 모달 → 명령 박스가 **`KYOBO_BASE="https://redcodeme.synology.me/kyobo"`** 식으로 자동 박혀 있으면 OK.

## 5. CORS 추가 (필요시)

`kyobo-bridge/app/main.py` 의 `allow_origins` 에 외부 도메인 추가 (이미 포함):
```python
allow_origins=[
    ...
    "https://redcodeme.synology.me",  # 추가
]
```

## 6. 한계·주의

- **워커는 여전히 사용자 Mac/PC 에 설치** — 외부 노출이 워커를 외부 머신에 옮기진 않음
- 외부 머신에서 분석 시작 → 사용자 본인 Mac 의 워커가 잡아야 동작 (즉 본인 Mac 도 켜져 있어야)
- `/api/secrets/ai` 는 **LAN-only** — 외부에서 호출 시 403 (의도). 외부 워커는 따로 `ANTHROPIC_API_KEY` 환경변수 사용 필요
- `/api/jobs/next/claim`, `/api/worker/ping` 도 LAN-only — 워커가 외부 도메인 통하면 403
- 외부 워커 지원이 필요하면 `_is_lan()` 화이트리스트에 외부 IP 추가 또는 토큰 인증 도입 검토
