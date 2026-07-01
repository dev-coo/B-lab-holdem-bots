# 봇 개발 가이드 (Bot Developer Reference)

홀덤 AI 서버에 연결하는 봇을 개발하기 위한 가이드입니다.

---

## 1. 시작하기

### 1.1 봇 등록

1. 웹 브라우저에서 서버에 접속 (예: `http://snn.it.kr:5051`)
2. 운영자가 생성한 계정으로 **로그인**
3. **대시보드** → 봇 관리 → 봇 이름 입력 후 **등록**
4. 발급된 **API 토큰**을 복사 (봇 인증에 사용)

### 1.2 필요 라이브러리

```bash
pip install websockets
```

### 1.3 실행

```bash
python3 bot.py ws://서버주소:5051/ws "발급받은_API_TOKEN" "봇이름"
```

---

## 2. WebSocket 프로토콜

### 2.1 연결

```
ws://서버주소:포트/ws
```

모든 통신은 JSON 메시지로 이루어집니다.

### 2.2 인증

연결 후 **첫 번째 메시지**로 인증을 보내야 합니다.

```json
{
  "type": "auth_bot",
  "api_token": "발급받은_토큰",
  "bot_name": "내봇이름"
}
```

**성공 응답:**
```json
{
  "type": "auth_ok",
  "user_id": 2,
  "bot_name": "내봇이름",
  "bot_tokens": 50,
  "concurrent_games": 1
}
```

**실패 응답:**
```json
{
  "type": "auth_fail",
  "reason": "봇 인증 실패"
}
```

인증 성공 후 **대시보드에서 봇을 "실행"(deploy)** 해야 방에 배정됩니다.
WS 접속만으로는 배정되지 않습니다. deploy는 REST API(`POST /bots/{id}/deploy`)로 수행합니다.

### 2.3 하트비트 (필수)

서버는 20초마다 `{"type": "ping"}`을 보냅니다.
봇은 반드시 `{"type": "pong"}`으로 응답해야 합니다.
**40초 내 pong이 없으면 서버가 연결을 강제 종료합니다.**

```python
if msg["type"] == "ping":
    await ws.send(json.dumps({"type": "pong"}))
```

### 2.4 서버 종료 / 시즌 종료

```json
{"type": "server_shutdown", "reason": "서버가 세션을 종료했습니다"}
```

시즌이 종료되면 봇에게 `server_shutdown` 메시지가 전송되고 연결이 끊어집니다.
봇은 이 메시지를 받으면 정상적으로 프로세스를 종료해야 합니다.
시즌 종료 후 재접속 시도 시에도 `server_shutdown`이 즉시 전송됩니다.

---

## 3. 카드 표기법

카드는 `랭크 + 슈트` 2글자 문자열입니다.

| 랭크 | 의미 |
|------|------|
| `2`~`9` | 숫자 그대로 |
| `T` | 10 |
| `J` | Jack |
| `Q` | Queen |
| `K` | King |
| `A` | Ace |

| 슈트 | 의미 |
|------|------|
| `s` | ♠ 스페이드 |
| `h` | ♥ 하트 |
| `d` | ♦ 다이아몬드 |
| `c` | ♣ 클로버 |

예: `Ah` = A♥, `Tc` = 10♣, `2s` = 2♠, `Kd` = K♦

---

## 4. 포지션

인원수에 따라 배정되는 포지션:

| 인원 | 포지션 (딜러부터 시계방향) |
|------|--------------------------|
| 2명 | `btn`, `bb` |
| 3명 | `btn`, `sb`, `bb` |
| 4명 | `btn`, `sb`, `bb`, `utg` |
| 5명 | `btn`, `sb`, `bb`, `utg`, `co` |
| 6명 | `btn`, `sb`, `bb`, `utg`, `hj`, `co` |
| 7명 | `btn`, `sb`, `bb`, `utg`, `mp`, `hj`, `co` |
| 8명 | `btn`, `sb`, `bb`, `utg`, `utg1`, `mp`, `hj`, `co` |
| 9명 | `btn`, `sb`, `bb`, `utg`, `utg1`, `mp`, `mp1`, `hj`, `co` |

**프리플롭 액션 순서:** `utg` → ... → `co` → `btn` → `sb` → `bb`
**포스트플롭 액션 순서:** `sb` → `bb` → `utg` → ... → `co` → `btn`
**헤즈업(2명):** 프리플롭 `btn` → `bb`, 포스트플롭 `bb` → `btn`

---

## 5. 수신 이벤트

서버에서 봇으로 보내는 이벤트 목록입니다.
**`action_request`만 응답이 필요**하고, 나머지는 정보 수신용입니다.

### 5.1 game_start — 게임 시작

```json
{
  "type": "game_start",
  "room_id": 1,
  "players": [
    {"name": "bot-A", "type": "bot"},
    {"name": "철수", "type": "human"}
  ],
  "starting_stack": 300,
  "blind_structure": [
    {"level": 1, "small": 1, "big": 2, "hands": 10},
    ...
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `room_id` | int | 방 ID (멀티 게임 구분용) |
| `players` | array | 참가자 목록 `{name, type}` |
| `starting_stack` | int | 시작 스택 (300) |
| `blind_structure` | array | 블라인드 구조 |

### 5.2 hand_start — 핸드 시작

```json
{
  "type": "hand_start",
  "room_id": 1,
  "hand_number": 1,
  "your_cards": ["Ah", "Kh"],
  "your_stack": 298,
  "your_seat": "btn",
  "blind": [1, 2],
  "players": [
    {"name": "bot-A", "stack": 298, "position": "btn", "status": "active", "action": null, "bet": 0},
    {"name": "bot-B", "stack": 297, "position": "sb", "status": "active", "action": null, "bet": 1},
    {"name": "bot-C", "stack": 296, "position": "bb", "status": "active", "action": null, "bet": 2},
    {"name": "bot-D", "stack": 300, "position": "utg", "status": "active", "action": null, "bet": 0}
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `hand_number` | int | 핸드 번호 (1부터 시작) |
| `your_cards` | array | **본인 홀 카드** 2장 (예: `["Ah", "Kh"]`) |
| `your_stack` | int | 본인 현재 스택 |
| `your_seat` | string | 본인 포지션 (예: `"btn"`) |
| `blind` | array | `[스몰블라인드, 빅블라인드]` |
| `players` | array | 전체 참가자 상태 (아래 참조) |

**players 배열 각 항목:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | string | 플레이어 이름 |
| `stack` | int | 현재 스택 |
| `position` | string | 포지션 (`btn`, `sb`, `bb`, `utg` 등) |
| `status` | string | `active`, `folded`, `allin`, `eliminated` |
| `action` | string\|null | 이번 페이즈 마지막 액션 |
| `bet` | int | 이번 라운드 베팅액 |

### 5.3 action_request — 액션 요청 (응답 필수!)

**이 이벤트를 받으면 30초 이내에 응답해야 합니다.**

```json
{
  "type": "action_request",
  "room_id": 1,
  "hand_number": 1,
  "your_cards": ["Ah", "Kh"],
  "community_cards": ["2s", "7d", "Kc"],
  "phase": "flop",
  "pot": 12,
  "my_stack": 294,
  "to_call": 4,
  "min_raise": 8,
  "blind": [1, 2],
  "seat": "btn",
  "players": [ ... ],
  "action_history": [
    {"phase": "preflop", "player": "bot-B", "action": "call", "amount": 2},
    {"phase": "preflop", "player": "bot-C", "action": "check", "amount": 2},
    {"phase": "flop", "player": "bot-B", "action": "raise", "amount": 4}
  ],
  "timeout_ms": 30000
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `your_cards` | array | 본인 홀 카드 |
| `community_cards` | array | 커뮤니티 카드 (플롭 3장, 턴 4장, 리버 5장) |
| `phase` | string | `preflop`, `flop`, `turn`, `river` |
| `pot` | int | 현재 팟 크기 |
| `my_stack` | int | 본인 남은 스택 |
| `to_call` | int | 콜하려면 내야 할 금액 (0이면 체크 가능) |
| `min_raise` | int | 최소 레이즈 금액 (이번 라운드 총 베팅 기준) |
| `blind` | array | `[SB, BB]` |
| `seat` | string | 본인 포지션 |
| `players` | array | 전체 참가자 상태 |
| `action_history` | array | 이번 핸드의 전체 액션 기록 |
| `timeout_ms` | int | 응답 제한 시간 (밀리초) |

**action_history 각 항목:**

| 필드 | 설명 |
|------|------|
| `phase` | 어느 페이즈에서의 액션인지 |
| `player` | 누가 |
| `action` | 무슨 액션 (fold, check, call, raise, allin) |
| `amount` | 이번 라운드 누적 베팅액 |

### 5.4 action_performed — 타 플레이어 액션

```json
{
  "type": "action_performed",
  "room_id": 1,
  "player": "bot-B",
  "action": "raise",
  "amount": 6,
  "pot": 9,
  "players": [ ... ]
}
```

### 5.5 phase_change — 페이즈 전환 (커뮤니티 카드 공개)

```json
{
  "type": "phase_change",
  "room_id": 1,
  "phase": "flop",
  "community_cards": ["2s", "7d", "Kc"]
}
```

| phase | community_cards 개수 |
|-------|---------------------|
| `flop` | 3장 |
| `turn` | 4장 |
| `river` | 5장 |

### 5.6 hand_result — 핸드 결과

```json
{
  "type": "hand_result",
  "room_id": 1,
  "hand_number": 5,
  "winners": [
    {"name": "bot-A", "amount": 52}
  ],
  "showdown": [
    {"name": "bot-A", "cards": ["Ah", "Kh"]},
    {"name": "bot-B", "cards": ["Qd", "Qs"]}
  ],
  "community_cards": ["2s", "7d", "Kc", "4h", "9d"],
  "pot": 52,
  "eliminated": ["bot-C"]
}
```

| 필드 | 설명 |
|------|------|
| `winners` | 승자 목록 `{name, amount}` (스플릿팟 시 여러 명) |
| `showdown` | 쇼다운에 참가한 플레이어의 카드 (폴드한 사람은 미포함) |
| `community_cards` | 최종 커뮤니티 카드 5장 |
| `pot` | 최종 팟 크기 |
| `eliminated` | 이번 핸드에서 탈락한 플레이어 (스택 0) |

### 5.7 player_joined / player_left — 참가/퇴장

```json
{"type": "player_joined", "room_id": 1, "player": {"name": "영희", "type": "human", "stack": 300}}
{"type": "player_left", "room_id": 1, "player": "영희"}
```

### 5.8 game_end — 게임 종료

```json
{
  "type": "game_end",
  "room_id": 1,
  "rankings": [
    {"rank": 1, "name": "bot-A", "chips": 1200},
    {"rank": 2, "name": "bot-B", "chips": 0},
    {"rank": 3, "name": "bot-C", "chips": 0},
    {"rank": 4, "name": "bot-D", "chips": 0}
  ]
}
```

### 5.9 error — 에러

```json
{"type": "error", "message": "토큰이 부족합니다"}
```

---

## 6. 액션 응답

`action_request`를 받으면 아래 형식으로 **30초 이내** 응답:

```json
{
  "type": "action",
  "room_id": 1,
  "action": "raise",
  "amount": 12
}
```

### 6.1 액션 종류

| 액션 | 설명 | amount |
|------|------|--------|
| `fold` | 포기 | 불필요 |
| `check` | 패스 (`to_call`이 0일 때만 가능) | 불필요 |
| `call` | 현재 베팅에 콜 | 불필요 (서버가 자동 계산) |
| `raise` | 레이즈 | **필수** — 이번 라운드 총 베팅 목표액 |
| `allin` | 올인 | 불필요 (서버가 자동 계산) |

### 6.2 raise의 amount 이해

`amount`는 **이번 라운드(페이즈)에서의 총 베팅액**입니다. 추가로 넣는 금액이 아닙니다.

예시:
- 현재 `to_call = 4` (상대가 4 베팅)
- `min_raise = 8`
- `{"action": "raise", "amount": 8}` → 8까지 레이즈 (추가 4 투입)
- `{"action": "raise", "amount": 20}` → 20까지 레이즈 (추가 16 투입)

**규칙:**
- `amount` < `min_raise` → 서버가 **폴드 처리** (유효하지 않은 레이즈)
- `amount` > 본인 스택 → 서버가 **올인 처리**
- `to_call`이 0인데 `call` → 서버가 **체크로 변환**

### 6.3 타임아웃

- 30초 내 응답 없으면 **자동 폴드**
- 잘못된 JSON, 알 수 없는 액션 → **자동 폴드**

---

## 7. 멀티 게임

하나의 WS 연결로 **여러 게임을 동시에** 처리할 수 있습니다.
대시보드에서 `concurrent_games` (동시 게임 수)를 설정하면 서버가 자동으로 여러 방에 배정합니다.

모든 이벤트에 `room_id`가 포함되므로, **room_id별로 게임 상태를 분리 관리**해야 합니다.

```python
# 멀티 게임 상태 관리 예시
games = {}  # room_id → 게임 상태

if msg["type"] == "hand_start":
    games[msg["room_id"]] = {
        "cards": msg["your_cards"],
        "players": msg["players"],
    }

elif msg["type"] == "action_request":
    room_id = msg["room_id"]
    game = games.get(room_id, {})
    # room_id별 상태를 참고하여 액션 결정
```

---

## 8. 게임 규칙 요약

- **노리밋 텍사스 홀덤** (No-Limit Texas Hold'em)
- 시작 스택: **300**
- 최소 4명, 최대 9명
- **블라인드 구조** (핸드 기반 기본):
  - Lv1~5: SB 1~5 / BB 2~10 (각 10핸드)
  - Lv6~10: SB 10~50 / BB 20~100 (각 8핸드)
  - Lv11~15: SB 100~500 / BB 200~1000 (각 6핸드)
  - Lv16~17: SB 750~1000 / BB 1500~2000 (각 6핸드)
  - Lv18~19: SB 1500~2000 / BB 3000~4000 (각 4핸드)
  - Lv20: SB 3000 / BB 6000 (끝날 때까지)
- 1명 남을 때까지 진행 (탈락제)
- 스택이 블라인드보다 적으면 자동 올인
- 동시 탈락 시 핸드 시작 칩량이 적은 쪽이 낮은 순위

---

## 9. 연결 끊김 / 재접속

- WS 연결이 끊어지면 **즉시 자동 폴드 모드** (매 핸드 폴드)
- 같은 `api_token` + `bot_name`으로 재접속하면 **진행 중인 게임 복원**
- 재접속 시 `joined_room` 이벤트에 **`snapshot`** 필드가 포함되어 현재 게임 상태를 즉시 파악 가능

```json
{"type": "joined_room", "room_id": 1, "reconnected": true,
 "players": ["bot-A", "bot-B"],
 "snapshot": {
   "hand_number": 5, "phase": "flop",
   "community_cards": ["2s", "7d", "Kc"],
   "pot": 120, "blind": [5, 10],
   "players": [
     {"name": "bot-A", "stack": 280, "position": "btn", "status": "active", "action": null, "bet": 0},
     {"name": "bot-B", "stack": 320, "position": "bb", "status": "active", "action": "call", "bet": 10}
   ],
   "action_history": [
     {"phase": "preflop", "player": "bot-B", "action": "call", "amount": 10}
   ],
   "your_cards": ["Ah", "Kh"]
 }}
```

**snapshot에는 `my_stack`, `seat` 필드가 없습니다.** 본인의 스택과 포지션은 `players` 배열에서 봇 이름으로 찾아야 합니다:

```python
my_info = next(p for p in snapshot["players"] if p["name"] == BOT_NAME)
my_stack = my_info["stack"]
my_seat = my_info["position"]
```

- `snapshot`이 없으면 핸드 간 전환 시점 — 다음 `hand_start`를 기다리면 됨
- **주의:** 재접속 시 반드시 pong 핸들러가 동작해야 함 (2.3 참조)

---

## 10. 봇 회수

대시보드에서 봇을 회수할 수 있습니다:

| 모드 | 동작 |
|------|------|
| **소프트 리콜** | 새 방 배정 중단, 진행 중인 게임은 정상 완료 |
| **하드 리콜** | 진행 중인 게임에서 매 핸드 자동 폴드 + 새 방 배정 중단 |

회수 후 재투입: 봇 프로그램을 종료하고 다시 실행하면 됩니다.

---

## 11. 전략 팁

### 프리플롭 핸드 강도 (참고용)
- **프리미엄**: AA, KK, QQ, AKs
- **강함**: JJ, TT, AKo, AQs, AJs
- **플레이 가능**: 99~22, KQs, KJs, QJs, JTs, T9s, 98s
- **포지션 의존**: 레이트 포지션(btn, co)에서 더 넓은 범위 플레이 가능

### action_request에서 활용할 수 있는 정보
- `to_call` / `pot` → **팟 오즈** 계산 (콜 가치 판단)
- `players[].status` → 남은 active 플레이어 수
- `players[].stack` → 상대 스택 사이즈 (숏스택 올인 경계)
- `action_history` → 상대 플레이 패턴 분석 (이번 핸드)
- `seat` → 포지션에 따른 전략 조절
- `blind` → 블라인드 대비 스택 비율 (M값) 계산

### M값 (토너먼트 압박 지표)
```
M = my_stack / (SB + BB)
```
- M > 20: 여유, 정상 플레이
- M 10~20: 약간 타이트
- M 5~10: 푸시오어폴드 구간 진입
- M < 5: 올인 or 폴드

---

## 12. 완전한 샘플 봇

```python
"""콜링 스테이션 — 가장 단순한 봇."""
import asyncio
import json
import sys
import websockets

SERVER = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:5051/ws"
API_TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""
BOT_NAME = sys.argv[3] if len(sys.argv) > 3 else "sample-bot"


async def main():
    async with websockets.connect(SERVER) as ws:
        # 1. 인증
        await ws.send(json.dumps({
            "type": "auth_bot",
            "api_token": API_TOKEN,
            "bot_name": BOT_NAME,
        }))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print(f"인증 실패: {auth}")
            return
        print(f"인증 성공: {BOT_NAME}")

        # 2. 이벤트 루프
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif msg_type == "server_shutdown":
                print(f"서버 종료: {msg.get('reason')}")
                break

            elif msg_type == "action_request":
                # 전략: 베팅 있으면 콜, 없으면 체크
                to_call = msg.get("to_call", 0)
                action = "check" if to_call == 0 else "call"

                await ws.send(json.dumps({
                    "type": "action",
                    "room_id": msg["room_id"],
                    "action": action,
                }))

            elif msg_type == "game_end":
                print(f"[Room {msg['room_id']}] 게임 종료")
                for r in msg.get("rankings", []):
                    print(f"  #{r['rank']} {r['name']} ({r['chips']} chips)")

            elif msg_type == "hand_result":
                for w in msg.get("winners", []):
                    print(f"[Room {msg['room_id']}] 핸드 #{msg['hand_number']}: {w['name']} +{w['amount']}")

            elif msg_type == "error":
                print(f"에러: {msg.get('message')}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 13. 이벤트 요약표

| 이벤트 | 설명 | 응답 필요 |
|--------|------|----------|
| `game_start` | 게임 시작, 참가자/블라인드 구조 | X |
| `hand_start` | 핸드 시작, 홀 카드 수신 | X |
| `action_request` | **액션 요청 (30초 제한)** | **O** |
| `action_performed` | 타 플레이어 액션 결과 | X |
| `phase_change` | 커뮤니티 카드 공개 | X |
| `hand_result` | 핸드 종료, 승자/쇼다운/탈락 | X |
| `player_joined` | 중도 참가자 입장 | X |
| `player_left` | 플레이어 퇴장 | X |
| `game_end` | 게임 종료, 최종 순위 | X |
| `joined_room` | 재접속 시 방 복귀 (snapshot 포함 가능) | X |
| `error` | 에러 메시지 | X |
