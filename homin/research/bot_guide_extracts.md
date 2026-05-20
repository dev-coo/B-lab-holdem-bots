# BOT_GUIDE 룰 추출 — 연구의 단일 출처

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Owner**: holdem-agent
- **Version**: 0.1
- **Source**: `guide/BOT_GUIDE.md`
- **Source SHA256**: `5e706f217e193ec68f65fc6b334493c0784e44f74f7ad71325caabd8cace82b9`
- **Related configs**: `configs/blind_schedule.yaml`, `configs/position_class_map.yaml`
- **Related BOT_GUIDE sections**: 전체 (§1–§13)

---

## 1. Objective

> 후속 모든 연구·개발이 참조할 **서버 규칙의 단일 출처(Single Source of Truth)** 를 확립한다. 이 문서에 기록되지 않은 서버 동작은 연구에서 가정하지 않는다.

---

## 2. 문서 사용 규칙

- 이 문서의 모든 항목은 **`guide/BOT_GUIDE.md` 에서 직접 인용**된다. 의역은 최소화.
- 숫자·공식·열거값은 **원문 그대로**. 우리 팀의 해석은 별도 `[Note]` 블록으로 분리.
- 변경 시 반드시 source SHA256 을 재계산하여 갱신.
- 다른 연구 문서에서 인용 시 `[§N.M]` 형식으로 참조 (예: `[§5.3]` → 이 문서의 5.3절).

---

## 3. 봇 식별과 영속성 (§1)

### 3.1 봇 등록 (§1.1)
1. 웹 접속 → 운영자 계정 로그인 → 대시보드 → 봇 이름 입력 → 등록
2. 발급된 **API 토큰** 을 봇 인증에 사용

### 3.2 봇 실행 (§1.3)
```bash
python3 bot.py ws://서버주소:5051/ws "발급받은_API_TOKEN" "봇이름"
```

### [Note 3.1] 우리 설계에의 영향
- **봇 이름 = 영속 키**: 이름은 운영자가 발급하는 고정 식별자. 따라서 P4 원칙(전역 프로필)의 근간.
- **토큰 + 이름** 의 쌍으로 재접속 시 게임 복원됨(§9 참조).
- 이름이 유지되는 한 **다른 시즌·다른 게임에서도 같은 상대 프로필을 누적** 가능.

---

## 4. WebSocket 프로토콜 (§2)

### 4.1 연결 (§2.1)
- URL 형식: `ws://서버주소:포트/ws`
- 모든 메시지는 **JSON**.

### 4.2 인증 — 첫 메시지 (§2.2)
```json
{
  "type": "auth_bot",
  "api_token": "발급받은_토큰",
  "bot_name": "내봇이름"
}
```

**성공**:
```json
{"type": "auth_ok", "user_id": 2, "bot_name": "…",
 "bot_tokens": 50, "concurrent_games": 1}
```

**실패**:
```json
{"type": "auth_fail", "reason": "봇 인증 실패"}
```

> 인증 성공 후 **대시보드에서 봇을 "실행"(deploy)** 해야 방에 배정됩니다.
> WS 접속만으로는 배정되지 않습니다. deploy는 REST API(`POST /bots/{id}/deploy`)로 수행합니다.

### [Note 4.1] Deploy 미확정 항목
- `POST /bots/{id}/deploy` 의 **인증 방식이 문서화되지 않음** (평가 B4).
- 연구/개발 **선결 과제**: 운영자에게 deploy API 인증 확인 (세션 쿠키? Bearer token?).

### 4.3 하트비트 (§2.3)
- 서버가 20초마다 `{"type": "ping"}` 전송.
- 봇은 `{"type": "pong"}` 으로 응답.
- **40초 내 pong 없음 → 연결 강제 종료**.

### 4.4 서버·시즌 종료 (§2.4)
```json
{"type": "server_shutdown", "reason": "서버가 세션을 종료했습니다"}
```
- 시즌 종료 시 송신 + 연결 종료.
- 시즌 종료 후 재접속 시도에도 즉시 `server_shutdown`.

### [Note 4.2] 연구 latency 예산
- 30초 action_request timeout (§6.3) 과 별개로 **봇 내부 예산 3초 목표**.
- 예산 내역 가이드: equity MC ≤ 80ms, EV 계산 ≤ 200ms, LLM ≤ 1500ms, 여유 ≥ 1000ms.

---

## 5. 카드 표기법 (§3)

**랭크**: `2,3,4,5,6,7,8,9,T,J,Q,K,A` (T=10).
**슈트**: `s`♠ `h`♥ `d`♦ `c`♣.
**예**: `Ah`, `Tc`, `2s`, `Kd`.

### [Note 5.1] 라이브러리 호환
- `treys` 라이브러리: 같은 표기 `Ah`, `Tc` 호환. 변환 불필요.
- `eval7`: 같은 표기 호환.
- Kaggle 데이터셋이 다른 표기(`10h`, `10♥`, `A of Hearts`)를 쓰면 **정규화 필요** (EDA 전처리).

---

## 6. 포지션 (§4)

### 6.1 포지션 표 (§4)

| 인원 | 포지션 |
|------|--------|
| 2 | `btn`, `bb` |
| 3 | `btn`, `sb`, `bb` |
| 4 | `btn`, `sb`, `bb`, `utg` |
| 5 | `btn`, `sb`, `bb`, `utg`, `co` |
| 6 | `btn`, `sb`, `bb`, `utg`, `hj`, `co` |
| 7 | `btn`, `sb`, `bb`, `utg`, `mp`, `hj`, `co` |
| 8 | `btn`, `sb`, `bb`, `utg`, `utg1`, `mp`, `hj`, `co` |
| 9 | `btn`, `sb`, `bb`, `utg`, `utg1`, `mp`, `mp1`, `hj`, `co` |

### 6.2 액션 순서
- **프리플롭**: `utg` → ... → `co` → `btn` → `sb` → `bb`
- **포스트플롭**: `sb` → `bb` → `utg` → ... → `co` → `btn`
- **헤즈업**: 프리플롭 `btn → bb`, 포스트플롭 `bb → btn`

### [Note 6.1] position_class_map (연구 단위)
연구 문서에서 사용할 **4단계 축약**:
- `EP` (Early): `utg, utg1` (4인 이상부터 존재)
- `MP` (Middle): `mp, mp1, hj` (7인 이상부터 본격)
- `LP` (Late): `co, btn`
- `BLIND`: `sb, bb`

주의: **6인 이하에서 EP 는 자주 없음**. 6인 테이블은 `{BLIND=sb/bb, EP=utg, MP=hj, LP=co/btn}` 로 축약.
→ `configs/position_class_map.yaml` 에 인원별 매핑을 명시적으로 정의.

---

## 7. 수신 이벤트 (§5)

> **`action_request`만 응답이 필요**하고, 나머지는 정보 수신용.

### 7.1 `game_start` (§5.1)
```json
{"type": "game_start", "room_id": 1,
 "players": [{"name": "…", "type": "bot"}, …],
 "starting_stack": 300,
 "blind_structure": [{"level": 1, "small": 1, "big": 2, "hands": 10}, …]}
```

### 7.2 `hand_start` (§5.2)
```json
{"type": "hand_start", "room_id": 1, "hand_number": 1,
 "your_cards": ["Ah", "Kh"], "your_stack": 298, "your_seat": "btn",
 "blind": [1, 2],
 "players": [{"name":"…","stack":…,"position":…,"status":…,"action":…,"bet":…}, …]}
```

`players[].status`: `active | folded | allin | eliminated`
`players[].bet`: 이번 라운드 베팅액

### 7.3 `action_request` — 응답 필수 (§5.3)

> **이 이벤트를 받으면 30초 이내에 응답해야 합니다.**

```json
{"type": "action_request", "room_id": 1, "hand_number": 1,
 "your_cards": ["Ah","Kh"], "community_cards": ["2s","7d","Kc"],
 "phase": "flop", "pot": 12, "my_stack": 294,
 "to_call": 4, "min_raise": 8, "blind": [1,2], "seat": "btn",
 "players": [...],
 "action_history": [
   {"phase":"preflop","player":"…","action":"call","amount":2},
   …
 ],
 "timeout_ms": 30000}
```

- `phase ∈ {preflop, flop, turn, river}`
- `community_cards`: flop 3장, turn 4장, river 5장
- `to_call`: 콜 필요 금액 (0이면 체크 가능)
- `min_raise`: 최소 레이즈 금액 (이번 라운드 **총 베팅 기준**)
- `action_history[].amount`: 이번 라운드 **누적 베팅액**

### [Note 7.1] situation_key 유도
연구의 상황 키 `(phase, position_class, action_ctx, stack_bucket)` 는 action_request 에서 다음과 같이 유도:
- `phase`: 그대로.
- `position_class`: `seat` → §6.2 매핑.
- `action_ctx`: `action_history` 중 이번 phase 의 부분 파싱 → {unopened, limped, open_faced, 3bet_faced, …}.
- `stack_bucket`: `my_stack / (blind[0]+blind[1])` 로 M 계산 → §10 기준 분류.

### 7.4 `action_performed` (§5.4)
```json
{"type":"action_performed","room_id":1,
 "player":"…","action":"raise","amount":6,"pot":9,"players":[...]}
```

타 플레이어 액션. `amount` 는 이번 라운드 **누적 베팅**.

### 7.5 `phase_change` (§5.5)
```json
{"type":"phase_change","room_id":1,
 "phase":"flop","community_cards":["2s","7d","Kc"]}
```

액션 없이 **스트리트 전환 + 커뮤니티 카드 공개만**. 상태 싱크 필수.

### [Note 7.2] 평가 B2 재확인
- `phase_change` 는 우리 액션을 요구하지 않지만, **내부 `GameState.phase` 와 `community_cards` 갱신 지점**.
- 누락 시 다음 action_request 의 situation_key 계산이 한 스트리트 뒤처짐.
- **L2 Perception 라우터의 필수 처리 이벤트**.

### 7.6 `hand_result` (§5.6)
```json
{"type":"hand_result","room_id":1,"hand_number":5,
 "winners":[{"name":"…","amount":52}],
 "showdown":[{"name":"…","cards":["Ah","Kh"]}, …],
 "community_cards":["2s","7d","Kc","4h","9d"],
 "pot":52,
 "eliminated":["…"]}
```

- `winners`: 스플릿팟 시 여러 명.
- `showdown`: 쇼다운 참가자 카드. **폴드한 자 미포함**.
- `eliminated`: 이번 핸드에서 탈락(스택 0).

### [Note 7.3] 블러핑 라벨러의 유일 신호원
- `hand_result.showdown` 이 **블러핑 판정의 ground truth**.
- 폴드한 상대의 카드는 영구 미공개 → `FOLD_TO_*` 지표만 업데이트 가능.
- 재접속 중 누락된 핸드의 `hand_result` 는 복구 불가 (§9 참조).

### 7.7 `player_joined` / `player_left` (§5.7)
```json
{"type":"player_joined","room_id":1,"player":{"name":"…","type":"human","stack":300}}
{"type":"player_left","room_id":1,"player":"…"}
```

### 7.8 `game_end` (§5.8)
```json
{"type":"game_end","room_id":1,
 "rankings":[{"rank":1,"name":"…","chips":1200}, …]}
```

### [Note 7.4] 토너먼트 상금 정보 부재
- `game_end.rankings` 는 **순위만** 제공, 상금(prize pool) 은 제공되지 않음.
- ICM 정식 계산 불가 → 계획 평가 A4 대응: log-utility 단일화 채택.

### 7.9 `error` (§5.9)
```json
{"type":"error","message":"토큰이 부족합니다"}
```

---

## 8. 액션 응답 (§6)

### 8.1 응답 스키마 (§6)
```json
{"type":"action","room_id":1,"action":"raise","amount":12}
```

### 8.2 액션 종류 (§6.1)

| 액션 | 설명 | amount 필드 |
|------|------|-------------|
| `fold` | 포기 | 불필요 |
| `check` | 패스 (`to_call=0` 일 때만 가능) | 불필요 |
| `call` | 현재 베팅에 콜 | 불필요 (서버 자동) |
| `raise` | 레이즈 | **필수** — 이번 라운드 총 베팅 목표액 |
| `allin` | 올인 | 불필요 (서버 자동) |

### 8.3 raise 의 amount 해석 (§6.2)

> `amount`는 **이번 라운드(페이즈)에서의 총 베팅액**입니다. 추가로 넣는 금액이 아닙니다.

**예시**: `to_call=4, min_raise=8`
- `{"action":"raise","amount":8}` → 8까지 레이즈 (실 추가 투입 = 4)
- `{"action":"raise","amount":20}` → 20까지 레이즈 (실 추가 투입 = 16)

**서버 규칙**:
- `amount < min_raise` → **자동 폴드**
- `amount > my_stack` → **자동 올인**
- `to_call=0` 인데 `call` → **체크로 변환**

### [Note 8.1] EV 수식의 ΔS 정의
부록 C 의 `ΔS = S − (내 기존 베팅)` 에서:
- `S` = `amount` (action_request 의 해석과 일치)
- `내 기존 베팅` = `action_request.players[me].bet` (이번 라운드 기준)
- 블라인드(SB/BB) 자동 투입분도 `players[me].bet` 에 이미 포함됨 → 별도 계산 불필요.

### 8.4 타임아웃 (§6.3)
- 30초 내 응답 없음 → **자동 폴드**
- 잘못된 JSON · 알 수 없는 액션 → **자동 폴드**

---

## 9. 멀티 게임 (§7)

- 하나의 WS 연결로 **여러 게임 동시 처리**.
- 대시보드에서 `concurrent_games` 설정.
- 모든 이벤트에 `room_id` 포함 → **room_id 별로 게임 상태 분리 관리**.

### [Note 9.1] 상태 분리 정책
- `GameState` 는 `room_id` 키로 Dict 보관 (휘발성).
- `PlayerProfile` 은 `(name, type)` 키 (전역·영속). **room_id 와 무관하게 공유**.

---

## 10. 게임 규칙 (§8) — 가장 중요한 섹션

### 10.1 기본 규칙
- **노리밋 텍사스 홀덤**
- **시작 스택: 300**
- 최소 4명, 최대 9명
- 1명 남을 때까지 (탈락제)
- 스택이 블라인드보다 적으면 자동 올인
- 동시 탈락 시 핸드 시작 칩량이 적은 쪽이 낮은 순위

### 10.2 블라인드 구조 (§8)

| Lv | SB | BB | hands | 누적 hand (범위 끝) |
|----|----|----|-------|--------------------|
| 1 | 1 | 2 | 10 | 10 |
| 2 | 2 | 4 | 10 | 20 |
| 3 | 3 | 6 | 10 | 30 |
| 4 | 4 | 8 | 10 | 40 |
| 5 | 5 | 10 | 10 | 50 |
| 6 | 10 | 20 | 8 | 58 |
| 7 | 20 | 40 | 8 | 66 |
| 8 | 30 | 60 | 8 | 74 |
| 9 | 40 | 80 | 8 | 82 |
| 10 | 50 | 100 | 8 | 90 |
| 11 | 100 | 200 | 6 | 96 |
| 12 | 200 | 400 | 6 | 102 |
| 13 | 300 | 600 | 6 | 108 |
| 14 | 400 | 800 | 6 | 114 |
| 15 | 500 | 1000 | 6 | 120 |
| 16 | 750 | 1500 | 6 | 126 |
| 17 | 1000 | 2000 | 6 | 132 |
| 18 | 1500 | 3000 | 4 | 136 |
| 19 | 2000 | 4000 | 4 | 140 |
| 20 | 3000 | 6000 | ∞ | — |

### [Note 10.1] 레벨별 M (시작 스택 300 기준, 무보강)

**가정**: 플레이어가 평균 스택 근처(= 탈락분만큼 증가) 를 유지. N 인 테이블에서 k 명 탈락 시 평균 = `300 · N / (N−k)`.

**6인 테이블**, 탈락 없음 (보수적 worst case):
| Lv | BB | avg stack (300) | M = stack/(SB+BB) |
|----|----|-----------------|--------------------|
| 1 | 2 | 300 | 100 (deep) |
| 3 | 6 | 300 | 33 (deep) |
| 5 | 10 | 300 | 20 (mid) |
| 6 | 20 | 300 | 10 (short, push/fold 진입) |
| 8 | 60 | 300 | 3 (pure jam/fold) |
| 10 | 100 | 300 | 2 |
| 11+ | 200+ | 300 | ≤ 1 (기계적 all-in) |

**6인 테이블**, 2명 탈락 후 (= 평균 450):
| Lv | BB | avg stack (450) | M |
|----|----|-----------------|---|
| 6 | 20 | 450 | 15 |
| 8 | 60 | 450 | 5 |
| 10 | 100 | 450 | 3 |

### [Note 10.2] 전략 모드 전환점 (평가 A1 검증)

시작 스택 300, 블라인드 구조로부터 도출:
- **Deep 모드 (M > 30)**: Lv1–3, 약 30핸드.
- **Mid 모드 (12 < M ≤ 30)**: Lv4–5, 약 20핸드.
- **Short/Push-Fold (M ≤ 12)**: Lv6 부터 사실상. 가장 긴 구간.
- **Pure jam (M ≤ 5)**: Lv8 이후.

**결론**: 평가 A1 검증 완료. **약 Lv5 말~Lv6 초부터 Push/Fold 지배**. 구체적 경계는 잔존 인원·평균 스택에 따라 유동.

### [Note 10.3] 게임 전체 길이 추정
- 블라인드 종료 기준 누적 핸드 = 최대 140핸드 (Lv19 끝).
- Lv20 은 무한이지만 BB=6000 에서 300 스택은 0.05BB → 다음 핸드에 all-in 불가피 → **실제 게임 종료는 140핸드 근처**.
- 평균 게임 길이 추정: **80–130핸드**.

---

## 11. 연결 끊김 / 재접속 (§9)

- WS 끊기면 **즉시 자동 폴드 모드** (매 핸드 폴드).
- 같은 `api_token + bot_name` 으로 재접속 시 **진행 중인 게임 복원**.
- 재접속 시 `joined_room` 이벤트에 `snapshot` 필드 포함 가능.

### 11.1 `joined_room` with snapshot
```json
{"type":"joined_room","room_id":1,"reconnected":true,
 "players":["bot-A","bot-B"],
 "snapshot":{
   "hand_number":5,"phase":"flop",
   "community_cards":["2s","7d","Kc"],
   "pot":120,"blind":[5,10],
   "players":[{"name":"bot-A","stack":280,"position":"btn",…}, …],
   "action_history":[{"phase":"preflop","player":"bot-B","action":"call","amount":10}],
   "your_cards":["Ah","Kh"]
 }}
```

### [Note 11.1] snapshot 의 결손 필드
> **snapshot에는 `my_stack`, `seat` 필드가 없습니다.** 본인의 스택과 포지션은 `players` 배열에서 봇 이름으로 찾아야 합니다:
```python
my_info = next(p for p in snapshot["players"] if p["name"] == BOT_NAME)
my_stack = my_info["stack"]
my_seat = my_info["position"]
```

### [Note 11.2] 핸드 단위 데이터 손실 (평가 B3)
- snapshot 의 `action_history` 는 **현재 핸드만** 담음.
- **끊김 중 완료된 이전 핸드의 `hand_result` 는 영구 손실** → 쇼다운 정보 누락, 프로필 업데이트 구멍.
- 방어: 멱등성 키로 중복 처리 방지 (P7), 누락은 수용.

---

## 12. 봇 회수 (§10)

| 모드 | 동작 |
|------|------|
| 소프트 리콜 | 새 방 배정 중단, 진행 게임은 정상 완료 |
| 하드 리콜 | 진행 게임에서 매 핸드 자동 폴드 + 새 방 배정 중단 |

회수 후 재투입: 프로그램 종료 후 재실행.

---

## 13. M 값 (§11)

> **M = my_stack / (SB + BB)**

| M | 해석 | 우리 설계의 모드 |
|---|------|-----------------|
| > 20 | 여유, 정상 플레이 | `deep` |
| 10–20 | 약간 타이트 | `mid` |
| 5–10 | 푸시오어폴드 구간 진입 | `hybrid` |
| < 5 | 올인 or 폴드 | `push_fold` |

### [Note 13.1] 설계 모드 매핑 (H.2.b 확정)
```yaml
mode_thresholds:
  deep:      {min_M: 30}
  mid:       {min_M: 15, max_M: 30}
  hybrid:    {min_M: 8, max_M: 15}
  push_fold: {max_M: 8}
```

H.2.b 초안의 경계(8/15/30) 는 §11 의 5/10/20 과 다르다. 우리가 **약간 더 보수적으로** 설정한 이유:
- §11 의 경계는 일반 포커 컨벤션(cash game/평탄 블라인드 가정).
- 우리 서버는 블라인드가 급상승하므로 **다음 레벨 BB 를 선행 반영** 필요 → 경계 상향.

---

## 14. 이벤트 요약표 (§13)

| 이벤트 | 응답 필요 | 우리 L2 처리 |
|--------|----------|-------------|
| `game_start` | X | GameState(room_id) 초기화 |
| `hand_start` | X | 핸드별 상태 리셋, 프로필 읽어오기 |
| `action_request` | **O** | EV 계산·의사결정·응답 |
| `action_performed` | X | action_history 누적, 프로필 업데이트 |
| `phase_change` | X | phase/community_cards 싱크 (§7.2 Note) |
| `hand_result` | X | 쇼다운 라벨링, 프로필 SQLite flush |
| `player_joined` | X | 플레이어 추가 |
| `player_left` | X | 플레이어 제거 |
| `game_end` | X | 랭킹 기록, GameState 폐기 |
| `joined_room` | X | 재접속 시 snapshot 복원 |
| `error` | X | 로깅·fail-safe |

---

## 15. 연구 단계 체크리스트

이 문서를 참조하여 후속 연구에서 꼭 확인:

- [ ] **R1 theory_notes**: §4.1 Deploy API 인증 방식 결정 포함.
- [ ] **R1 blind_schedule_analysis**: §10.2 표 + Note 10.1/10.2 를 수치적으로 확장.
- [ ] **R2 EDA**: Kaggle 데이터의 카드 표기를 §5 형식으로 정규화. 이벤트 어휘를 §8.2 로 매핑.
- [ ] **R3 population_prior**: situation_key 는 §7.3 Note 7.1 의 유도식으로 생성.
- [ ] **R4 bootstrap**: self-play 시뮬레이터가 §5–§7 이벤트 스키마 완전 재현.
- [ ] **R5 nash_charts**: M bucket 은 §13 Note 13.1 에 맞춤.

---

## Limitations & Caveats

1. **Deploy API 미확정**: §2.2 의 deploy 는 문서화되지 않은 REST 엔드포인트. 운영자 확인 전 자동화 불가.
2. **상금 구조 부재**: §5.8 `game_end` 는 상금 정보 없음. ICM 정식 구현 불가.
3. **재접속 데이터 손실**: §9 의 snapshot 은 현재 핸드만 포함. 핸드 경계 중 단절 시 쇼다운 영구 손실.
4. **sb/bb 포지션 플레이어 수 제약**: 2명일 때만 `btn, bb` (sb 없음). 3명부터 sb 존재. 2인 HU 는 다른 규칙.
5. **블라인드 구조의 가정**: §8 의 "hands" 가 게임 내 총 핸드인지, 레벨 지속 핸드인지 모호. **우리 해석**: 레벨 지속 핸드(현재 이 해석으로 §10.2 표 작성).

---

## Changelog

- 2026-04-19 (v0.1): 초안 작성. BOT_GUIDE §1–§13 전체 추출. source SHA256 고정.
