---
name: holdem-status
description: 홀덤 봇의 현재 상태를 요약 보고. 프로세스 생존, PID·uptime, 프로필 DB 통계 (핸드 수·상대별 학습량), 최근 세션 로그 꼬리, 이상 신호 여부를 포함.
---

# holdem-status

현재 봇 인스턴스의 상태를 한 번에 보고한다.

## 실행

`scripts/bot-status.sh` 를 실행하고 출력을 3 개 섹션으로 정리해 사용자에게 보고:

1. **프로세스**: PID, uptime, 기동 명령.
2. **프로필 DB**: 프로필 수, 상대별 누적 핸드 (상위 10), 응답 테이블 크기.
3. **로그 꼬리**: 최신 세션 로그 마지막 10 줄. 여기에 `unparseable` / `Exception` / `ERROR` 가 보이면 별도로 강조.

## 추가 분석 (선택)

사용자가 "자세히" / "detail" 을 요청하면:
- `data/logs/cli/` 의 세션 파일 목록 + 각 파일 마지막 수정 시각.
- `data/profiles.db` 의 `whoareyou` 프로필 VPIP/PFR rate 계산 (있으면).
- 최근 1 시간 내 결정 종류별 카운트 (fold/check/call/raise/allin).

## 이상 진단

다음을 자동으로 체크해 이상이면 경고:
- PID 파일 있으나 프로세스 사망 → `data/bot.pid` 삭제 권장.
- 최근 5 분 내 로그 업데이트 없음 → WS 연결 정체 가능.
- `unparseable` 10 회 이상 → 스키마 수정 필요.
- DB 락 에러 → 동시 접근 조사.
