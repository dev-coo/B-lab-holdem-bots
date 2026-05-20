# 게임 참여 가능성 점검 — 2026-04-20

## Status
- **Stage**: Draft (blocking)
- **Owner**: holdem-agent
- **Related**: `research/deploy_api_notes.md`

## 1. 요약
**현 시점에서 게임 서버(snn.it.kr:5051) 에 네트워크 레벨에서 도달 불가.**
봇 코드·인증·LLM 파이프라인은 모두 준비 완료 상태이나, 서버 자체와 통신 자체가 성립하지
않아 게임 참여가 **현재 불가능**.

## 2. 진단 결과

### 2.1 환경 설정 (OK)
| 항목 | 값 |
|---|---|
| `.env` | 존재, 5개 키 모두 설정 (`HOLDEM_WS_URL`, `HOLDEM_API_TOKEN`, `HOLDEM_BOT_NAME`, `HOLDEM_LLM_API_KEY`, `HOLDEM_LLM_BASE_URL`) |
| WS URL | `ws://snn.it.kr:5051/ws` |
| Bot name | `whoareyou` |
| Token | 설정됨 |
| LLM proxy | `localhost:8317` → HTTP 401 (alive) |

### 2.2 네트워크 (FAIL)
| 검사 | 결과 |
|---|---|
| DNS | `snn.it.kr` → `220.84.128.111` (해결 OK) |
| ICMP ping × 3 | 100% packet loss |
| TCP 80 | closed/filtered |
| TCP 443 | closed/filtered |
| TCP 5050 | closed/filtered |
| TCP **5051** | closed/filtered |
| TCP 8080 | closed/filtered |
| Traceroute | 8홉에 `110.69.17.17` 까지 도달 후 서버측 미응답 |
| 외부망 (`google.com`) | HTTP 301 (정상) |

### 2.3 실제 WS 접속 시도
```
URL: ws://snn.it.kr:5051/ws
Bot: whoareyou
Token: set
RESULT: connection timed out (6s)
```

## 3. 원인 후보
1. **서버 다운** — 모든 포트가 filter 되어 운영 중지 가능성.
2. **지역 제한 / IP 차단** — 현재 네트워크 (Huawei mobile WiFi, 해외 경로) 에서 한국
   서버 접근 차단. 이전 세션에서 같은 경로로 LLM 호출은 되므로 차단 대상은 snn.it.kr 특정.
3. **VPN 요구** — 한국 내 네트워크나 특정 VPN 경유가 운영 정책일 가능성.
4. **특정 시간대만 오픈** — 대회 시간 외에는 포트 차단.

## 4. 선행 조치 필요
운영자 / 관리자에게 확인할 사항:
- [ ] 서버 운영 중인가? (status page 유무)
- [ ] 접근 제한 (IP 허용 목록 / 국가 차단 / VPN) 이 있는가?
- [ ] 접속 가능 시간대 공지가 있는가?
- [ ] deploy API 인증 방식 (이전 blocker 와 동일) 확정은 남아있음.

## 5. 현 상태에서 할 수 있는 것
- 실서버 smoke: **불가** (네트워크 차단).
- 로컬 CLI 동작 확인: 가능 (네트워크 실패 시 재접속 루프 백오프로 수렴).
- R4 Bootstrap self-play, R5 Nash 차트 등의 **네트워크 독립 연구 작업**은 정상 진행 가능.

## 6. 결론
- **봇 코드 준비도**: 100% (287 tests pass, D1-D7 + Phase 2 통합 완료).
- **게임 참여 가능 여부**: **NO** — 네트워크 도달 불가로 auth 단계조차 시도 불가.
- **해제 조건**: 서버 가동 재개 또는 접근 허용 채널 확보.

## Changelog
- 2026-04-20 (v0.1): 네트워크 진단 + WS 접속 시도 결과 기록.
