---
name: holdem-stop
description: 홀덤 봇을 안전하게 정지. SIGTERM → 10초 대기 → SIGKILL fallback. 잔여 프로세스도 청소.
---

# holdem-stop

## 실행

1. `scripts/bot-stop.sh` 실행.
2. `scripts/bot-status.sh` 로 종료 확인.
3. 사용자에게 "STOPPED" 와 현재 profile DB 상태 (핸드 수) 를 보고.

## 주의

- 게임 중 강제 종료 시 현 핸드는 자동 폴드 처리 (BOT_GUIDE §6.3).
- profile DB 는 `hand_result` 마다 자동 저장되므로 종료 시점의 상태까지 보존됨.
- 재기동 시 `data/profiles.db` 로 warm-start → 상대별 학습 누적 유지.
