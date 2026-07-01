# Strategy Changelog

전략의 의사결정 로직이 어떻게 바뀌어 왔는지 버전별로 누적 기록한다. 새 변경은 **맨 위에 새 섹션** 으로 추가 (최신이 위). 각 항목은 다음 형식:

> **참고 (2026-04-22 인프라 변경, 전략 로직 무변화)**: 저장소가 uv workspace 구조로 전환됨. 이전 `app/strategy/*` 경로는 현재 `packages/main_bot/src/holdem_main_bot/*` 로 이동. 공용 유틸 (`hand_eval`, `equity`) 은 `packages/core/src/holdem_core/` 로 이동. 분석·대시보드는 `tools/src/holdem_tools/` 로 이동. 본 CHANGELOG 의 v0~v3 섹션에 나오는 `app/*` 경로는 **당시 경로 기록용** 이며, 현재 코드 찾을 때는 새 경로를 참고할 것.

```
## vX (YYYY-MM-DD) — 한 줄 요약

### 동기 (왜 바꿨나)
### 변경 (뭘 바꿨나)
### 파라미터 (StrategyConfig 차이)
### 측정 (before/after 수치)
### 리스크 / 후속
### 관련 파일 / 커밋
```

관련 문서: [`LOGIC.md`](../LOGIC.md) · [`GLOSSARY.md`](../GLOSSARY.md) · [`../../BOT_REFERENCE.md`](../../BOT_REFERENCE.md)

---

## v5.5 (2026-05-01) — 너구리쿤 분석 기반 LAG 대응 5종 fix

### 동기

`.debug/main/holdem.db` 라이브 17K~38K 핸드 데이터로 주요 상대 너구리쿤 (VPIP 79.6%, PFR 31.5%, 3bet 19.3%, SD 승률 61.6%, 모든 394 룸 등장 — 사실상 상수 LAG 상대) 행동 분석. 5가지 미스매치 발견:

1. **`primary_threat == 너구리쿤` 등록 0건 / 17K 핸드** — `estimate_tier()` 가 이번 핸드의 preflop 액션만 base 로 쓰고 누적 profile 은 widen/tighten 보정에만 사용. 너구리쿤이 이번 핸드 raise 안 하면 → 'any' tier → primary_threat 후보 제외. 17K 핸드 동안 가장 위험한 상대가 단 한 번도 인식되지 않음.
2. **너구리쿤이 우리 탈락 30.5% 책임 (1088 중 332건)** — 대표 8건 dominated 탈락 모두 equity **0.36-0.40 commit** (4d/Kc on 9-high straight board, Ks/Qs on 8-paired, 등). 현 `committed_shove` 룰이 `m<10 + equity>=0.35` 면 무조건 allin → strong opp 상대로 너무 관대.
3. **river/medium/bet posterior 23% (n=1608, conf 0.99)** — 너구리쿤 river bet 의 77% 가 value 인데 v5.1 의 `bluff_low_threshold=0.25` margin 보정만으로는 약함. river 에서 추가 boost 필요.
4. **flop/turn small raise posterior 45% (n=6050)** — 너구리쿤 flop small raise 는 반은 bluff 인데 `bluff_high_threshold=0.50` 미달이라 cfg 보정 미발동. mid 영역도 활용 필요.
5. **`fold_vs_3bet` 1886회 (너구리쿤 winner 핸드 중)** — 너구리쿤 3bet 의 71% 가 fold-win 으로 끝남 = 우리가 over-fold. 기본 call_vs_3bet 은 QQ/JJ/AKo 만. 누적으로 wide-3bettor 식별되면 추가 hand 도 call.

상세: `/tmp/raccoon_analysis/00_synthesis.md` (분석팀 리포트).

### 변경

**A. `estimate_tier()` 누적 profile floor (P0 — opp_range.py)**
- `_profile_floor_tier(profile)` 신설 — hands_seen ≥ 100 + (SD 승률 ≥ 0.55 OR 3bet rate ≥ 0.10 OR VPIP ≥ 0.50) → top20 floor; ≥ 500 + SD ≥ 0.60 → top10 floor
- `estimate_tier` 가 이번 핸드 base 와 floor 의 max 를 base 로 사용
- `primary_threat` tie-break: 동률 tier 면 누적 hands_seen 큰 쪽 우선 (신뢰성)

**B. tier-conditional commit equity floor (P0/P2 — strategy.py)**
- `committed_shove_equity_floor_top10=0.45`, `top20=0.40`, default `0.35` (현행 유지)
- `ev_raise_equity_floor_top10=0.45`, `top20=0.40`, default `0.35` (현행 유지)
- `_postflop` 의 `committed_shove` 룰과 EV argmax raise floor 모두 `flags_tier` 기반 conditional. 기본 spot 동작은 변화 없음.

**C. phase-specific bluff posterior (P1 — strategy.py)**
- `bluff_river_value_boost=1.5` — river phase + bluff_low 분기 시 margin 보정 ×1.5 (값-우세 시그널 강화)
- `bluff_mid_threshold=0.40`, `bluff_mid_scale=0.5` — flop/turn 에서 0.40-0.50 mid posterior 도 절반 효과로 잡음 (너구리쿤 flop small raise 같은 spot)

**D. vs wide-3bettor call defense (P1 — strategy.py)**
- `vs_wide_3bettor_threebet_rate=0.10`, `vs_wide_3bettor_min_hands=100`
- `vs_wide_3bet_extra_calls = {TT, 99, AQs, AQo, AKs, KQs, AJs}` — wide-3bettor 면 premium 외 추가 call
- `_last_preflop_raiser_name()` + `_is_wide_3bettor()` helper 추가
- 기존 `call_vs_3bet_premium` (QQ/JJ/AKo) 은 변경 없음

### 파라미터 (v5.4 → v5.5 diff)

| field | v5.4 | v5.5 | 비고 |
|---|---:|---:|---|
| `committed_shove_equity_floor` | (hardcoded 0.35) | 0.35 | conditional 분리 (default) |
| `committed_shove_equity_floor_top10` | — | **0.45** | 신규 |
| `committed_shove_equity_floor_top20` | — | **0.40** | 신규 |
| `ev_raise_equity_floor` | 0.35 | 0.35 | (현행 유지) |
| `ev_raise_equity_floor_top10` | — | **0.45** | 신규 |
| `ev_raise_equity_floor_top20` | — | **0.40** | 신규 |
| `bluff_river_value_boost` | — | **1.5** | 신규 |
| `bluff_mid_threshold` | — | **0.40** | 신규 |
| `bluff_mid_scale` | — | **0.5** | 신규 |
| `vs_wide_3bettor_threebet_rate` | — | **0.10** | 신규 |
| `vs_wide_3bettor_min_hands` | — | **100** | 신규 |
| `vs_wide_3bet_extra_calls` | — | **{TT, 99, AQs/o, AKs, KQs, AJs}** | 신규 |

`opp_range.py` 모듈 상수 (cfg 외):
- `_PROFILE_FLOOR_HANDS_TOP20=100`, `TOP10=500`
- `_PROFILE_FLOOR_SD_WIN_TOP20=0.55`, `TOP10=0.60`
- `_PROFILE_FLOOR_THREEBET_RATE=0.10`
- `_PROFILE_FLOOR_VPIP_WIDE=0.50`

### 측정

**리플레이 (`.debug/main/holdem.db` 500 케이스, `--db-glob`)**:
- matches_original = **498/500 (99.6%)** — 새 룰 발동 spot 만 분기, 기본 동작은 호환
- 발동 케이스 2건 모두 합리적 spot (commit_floor 또는 wide_3bet_call)

**프로필 floor 검증 (live `.debug/main/holdem.db` 12 profiles)**:
- 너구리쿤: empty history + raccoon profile → `top20` (was `'any'`) ✓
- 도화 (99K 핸드), 부산대 정해인 (39K), 쪼랩익명이4 (95K), whoareyou (107K) — 모두 `top10` floor ✓
- admin (12 핸드) — `'any'` 유지 (적은 데이터 무시) ✓
- `is_wide_3bettor(너구리쿤)` = True (3bet rate 17%) ✓

**린트**: opp_range.py / strategy.py 의 lint 카운트 변동 없음 (3 → 3, 모두 사전 존재).

### 리스크 / 후속

- floor 룰이 admin/봇 자체 등 봇이 아닌 플레이어에도 적용될 수 있음. 단 hands_seen ≥ 100 가드로 잡음 차단.
- `bluff_mid_scale=0.5` 가 mid 영역에서 false-positive 일 가능성 — 새 데이터 쌓인 후 hit-rate 측정 필요.
- `vs_wide_3bet_extra_calls` 의 KQs/AJs 가 너구리쿤 4bet jam 받았을 때 dominated 가능 (너구리쿤 4bet 의 sd_win 84%). v5.5.x 후속에서 4bet faced 분기 추가 검토.
- `committed_shove_equity_floor_top10=0.45` 가 short stack 에서 돌아갈 수 없는 spot 만들 가능 — desperate (M<3) 에서는 floor 무시 검토 (현재는 m<10 가드만).

### 관련 파일

- `packages/main_bot/src/holdem_main_bot/opp_range.py` (estimate_tier floor, primary_threat tie-break, _profile_floor_tier, _max_tier, _tier_strength)
- `packages/main_bot/src/holdem_main_bot/strategy.py` (StrategyConfig 12 fields 추가, _postflop commit/EV floor conditional, bluff phase-specific 후처리, _preflop_decision wide_3bet defense + helpers)
- 분석 보고서: `/tmp/raccoon_analysis/{00_synthesis,01_volume_aggression,02_bluff_showdown,03_headup_loss}.md`

### v5.5.2 추가 patch (headup-loss 보고 반영)

**preflop blind-bleed 차단 (F1+F5)**:
headup-loss 분석 — 너구리쿤 winner 핸드의 우리 결정 42K 중 fold **60.2%**, preflop fold **77.7%**. 너구리쿤 raise→우리 반응에서 small/medium 사이즈 fold% **70-76%**, fold 후 너구리쿤 winner 비율 58-74%. 즉 너구리쿤이 cheap mini-raise (≤2.5bb) 만으로 우리 blind 회수 중. 새 옵션 `vs_wide_opener_bb_defend=True` + `vs_wide_opener_min_size_bb=2.5` + `vs_wide_opener_bb_extra_calls` (21 hands: connectors T9s/98s/87s/76s/65s/54s + one-gappers J9s/T8s 등 + suited Ax + 22-55). wide-opener 가 mini-raise 한 BB defend spot 에서 call_set 확장.

**[F6] 우려 — teammate 가 file-based stale view 만 본 결과**:
headup-loss 가 "너구리쿤이 `opponent_profiles.json` 에 없음" 진단했으나 이는 **HOLDEM_DEBUG_JSONL=0 이후 JSON 파일이 더 이상 갱신되지 않기 때문**. 실제 source-of-truth 는 SQLite (`.debug/main/holdem.db`). v5.4 patch 의 `_load_opponent_profiles(path, debug_dir=...)` 가 DB 우선이라 우리 봇은 너구리쿤 hands_seen=62K, sd_win 0.61 등 정확히 조회. v5.5 floor 와 결합 → 너구리쿤 매 핸드 `top20` 인식. file 기반 분석 코드만 stale.

리플레이 (`.debug/main/holdem.db` 500): matches_original = **498/500** (호환 유지).

### v5.5.1 추가 patch (분석팀 후속 보고 반영)

**(A) wide-4bettor 가 open 한 spot 에서 우리 3bet bluff 비활성**:
volume-aggression 분석 — 너구리쿤 open 후 3bet 받으면 fold 1.1% / 4bet 75% / call 19%. 즉 wide-3bettor 는 wide-4bettor 이기도 하므로 우리 3bet bluff 거의 무의미. 새 옵션 `vs_wide_4bettor_disable_3bet_bluff=True` 와 strict value subset `vs_wide_4bettor_threebet_value = {AA,KK,QQ,JJ,AKs,AKo,AQs}`. wide-3bettor 가 opener 면 three_bet_set 을 strict value 와 intersect, 나머지 hand 는 call/fold.

**(B) turn/river commit floor 추가 보정 +0.05**:
bluff-showdown 분석 — 너구리쿤 turn allin (n=135) fold-equity 11.1%, sd_win 70%; river allin (n=165) fold-equity 11.5%, sd_win 75%. 이미 v5.5 의 commit_floor 가 top10/top20 에서 0.45/0.40 인데, turn/river phase 일 때 추가 +0.05 (top10=0.50, top20=0.45). 새 옵션 `commit_floor_turn_river_bonus=0.05`.

리플레이 (`.debug/main/holdem.db` 500): matches_original = **498/500** (호환 유지, 새 룰만 분기 발동).

---

## v5.4 (2026-05-01) — Deploy 자동화 + spectator broadcast 진단 + opponent_profiles/bluff_prior 칼리브레이션 + WARN1 픽스

### 동기

대회 결과 집계 불가 사고. `.debug/main/_global.jsonl` 5007 라인 / 6 runs 분석:
- **봇 "지방에도사람살아요"가 4723개 hand_start 중 0건의 player list 에 있음** (0.0%).
- outbound action 0건 — 봇이 단 한 번도 결정 송신을 안 함.
- 서버는 ping/auth_ok 외에는 hand_start broadcast 만 보내고 action_request 0건.

근본 원인 2 단계:
1. **봇이 deploy 안 됨** — `BOT_REFERENCE.md` §2.2: "WS 인증만으로는 방 배정 안 됨. `POST /bots/{id}/deploy` 필요." 봇 코드 어디에도 deploy 호출 없음 (`grep deploy packages/ scripts/` 0건).
2. **silent ValidationError** — `events.py::HandStart` 가 `your_cards/your_stack/your_seat` 필수였는데 spectator broadcast 에는 그 필드 없음 → `client.py::_parse` 의 ValidationError catch 가 WARN 만 찍고 None 반환 → dump 에 `event=null` 4723건. 사고 잠재.

부수적으로 데이터 마이닝 결과 (4명 분석 팀):
- `opponent_profiles.json` (16명, 9명 ≥1k 핸드) — 풍부한 자산이지만 `profile_min_hands=15` 잡음 통과, `wssd_pct` 같은 nit 시그널 미활용.
- `bluff_prior.json` (784 버킷, 26명) — `bluff_min_confidence=0.05` 너무 헐거움 (n=2 잡음 firing). 84% soft label 이 50/50 split 으로 누적되어 long-run mean 이 인공적으로 0.5 로 끌려 bluff over-detection.
- WARN1 (BB 3bet pot 에서 RA=0.5 fallback) — `range_advantage.py::_hero_class_keys` 가 BB 의 첫 raise 를 OPEN 으로 해석해서 `OPEN_BB`(empty) 폴백.

### 변경

1. **P0 — Deploy 자동화 (`app.py` + `config.py` + `__main__.py` 흐름)**:
   - `Settings` 에 `DASHBOARD_URL`, `BOT_ID`, `AUTO_DEPLOY` 필드 추가. 둘 다 채우면 `run()` 시작 시 `POST {DASHBOARD_URL}/bots/{BOT_ID}/deploy` 호출.
   - 미설정이면 `auto_deploy_skipped_missing_config` ERROR 로그로 사용자에게 수동 deploy 안내. 네트워크 실패는 WARN — 이미 deploy 된 상태일 수 있으므로 WS 연결은 시도.
2. **P0 — Spectator-tolerant `HandStart` (`events.py`)**: `your_cards: list[CardStr] = []`, `your_stack: int = 0`, `your_seat: str | None = None` 으로 default 부여. 더 이상 spectator broadcast 가 silent ValidationError 로 사라지지 않음.
3. **P0 — Loud 진단 (`ws/client.py`)**: `_parse` 의 ValidationError → `logger.error` (이전 `warning`) + `raw_keys` 동봉. `_dispatch::HandStart` 분기에서 `your_seat is None` 이면 `spectator_hand_start_received_bot_not_seated` ERROR + skip — 봇이 deploy 안 됐다는 명시적 신호.
4. **P1 — `profile_min_hands` 15 → 200**: 90~250 핸드 신규 상대는 base tier (action 만) 폴백. ≤200 핸드 VPIP 표준편차 ~7%p → tier 보정 잡음 차단.
5. **P1 — `wssd_pct` (W$SD) 누적 + 활용**: `summary.py::_merge_profiles` 에서 `wssd_pct = showdown_won_n / showdown_n` 미리 컴퓨팅하여 `opponent_profiles.json` 에 저장. `strategy.py::_postflop` 에서 `opp_threat` 의 `wssd_pct >= 0.62` 이고 `showdown_n >= 50` 이면 `raise_thr += 0.02`, `margin += 0.02` (nit 의 SD-bound aggression 에 보수적). meta 에 `wssd_aggro_threat` 기록.
6. **P2 — `bluff_min_confidence` 0.05 → 0.12**: 실측 784 버킷 중 n=0.2 짜리 잡음이 confidence 0.01 로 통과해 결정 흔들던 사고 차단. 0.12 면 n≈2.7 (soft 14회 / hard 3회) 이상 — strong signal 만.
7. **P2 — Soft label 1:3 bias**: `bluff_prior.py::update_soft_fold_win` 의 alpha:beta `0.1:0.1` → `0.05:0.15`. fold-win 의 대부분은 value bet 이 fold 받아낸 것이라는 prior 반영. long-run mean 이 0.5 (50/50) → 0.25 (1/4) 수렴.
8. **P2 — Global prior `(1.0, 3.0)` → `(1.0, 4.0)`**: mean 0.25 → 0.20. 통상 bluff 빈도 10~15% 에 더 가까운 출발점. 신규 버킷에만 적용, 기존 786 버킷의 누적값은 그대로 유지.
9. **P3 — Shover VPIP-aware call gate (`tournament.py::push_fold_decision`)**: profile 에서 shover VPIP 조회 (`hands_seen >= 200`). VPIP≥0.30 (loose, 예 고니 53%) → `call_min -= 0.05`. VPIP≤0.18 (tight, 예 편경장 14%) → `call_min += 0.05`. dominant 함수 spot 에서만 더 좁게.
10. **P3 — WARN1 fix (`range_advantage.py::_hero_class_keys`)**: BB 에서 `n_raises >= 1` 도 3bet 으로 분기 (이전: `n_raises >= 2` 만). 결과 `THREE_BET_OOP` 사용 → hero_combos 7개 이상 정상 생성. RA 0.5 fallback 해소.

### 파라미터 (v5.3.1 → v5.4)

| 항목 | v5.3.1 | v5.4 | 근거 |
|---|---|---|---|
| `Settings.DASHBOARD_URL` | (없음) | "" (사용자 설정) | deploy REST endpoint |
| `Settings.BOT_ID` | (없음) | 0 (사용자 설정) | deploy 대상 식별 |
| `Settings.AUTO_DEPLOY` | (없음) | True | 부팅 시 자동 호출 |
| `HandStart.your_seat` | required str | `str \| None` | spectator broadcast 수용 |
| `HandStart.your_cards` | required list | default [] | spectator broadcast 수용 |
| `HandStart.your_stack` | required int | default 0 | spectator broadcast 수용 |
| `profile_min_hands` | 15 | **200** | 잡음 차단 |
| `wssd_pct_high` | (없음) | 0.62 | nit 식별 임계 |
| `wssd_aggro_margin_bonus` | (없음) | 0.02 | nit aggression 시 raise_thr/margin 상향 |
| `wssd_min_showdowns` | (없음) | 50 | 보정 적용 최소 SD |
| `bluff_min_confidence` | 0.05 | **0.12** | n=2 잡음 firing 차단 |
| Soft label α:β | 0.1:0.1 | **0.05:0.15** | fold-win bluff bias 완화 |
| Global prior (α, β) | (1.0, 3.0) | **(1.0, 4.0)** | mean 0.25 → 0.20 |
| `BB n_raises==1` (RA) | OPEN_BB fallback | THREE_BET_OOP | WARN1 픽스 |

### 측정

- 사고 발생 데이터: `_global.jsonl` 5007 라인 분석
  - hand_start broadcast 4723 건 / 9.1 분당 1건 / 6 runs 7일 누적
  - 봇 player list 출현 0건 (0.0%)
  - outbound action 0건
  - per-room jsonl 0개 (deploy 안 된 결과)
- 스모크 검증 (라이브 데이터 아직 없음, 향후 deploy 후 라이브 측정 필요):
  - 모든 import 정상 (`uv run python -c "from holdem_core.* import ...; from holdem_main_bot.* import ..."`)
  - spectator broadcast (`your_seat=None`) parse 성공 + `client._dispatch` 가 ERROR 로그 + skip 정상
  - seated hand_start parse 정상 (`your_seat='btn'` etc)
  - WARN1: BB first raise → hero_range_combos 7키 (이전 0)

### 리스크 / 후속

- **`DASHBOARD_URL` / `BOT_ID` 미설정 상태로 봇 기동 시**: ERROR 로그가 나오지만 WS 는 여전히 연결됨. 사용자가 대시보드에서 수동 deploy 했다면 정상 작동. 둘 다 빈 채로 두면 매 부팅마다 ERROR 1회 — 시끄럽지만 안전.
- **`profile_min_hands=200` 신규 토너먼트에서 첫 100핸드 정도는 profile 보정 없이 base tier 만 사용** — 이전(15) 보다 보수적. 데이터 누적 후 점진적으로 보정 활성.
- **bluff_min_confidence 0.12 격상 시 short-term firing 빈도 감소**. 기존 786 버킷 중 conf>=0.12 통과 버킷 분포 추정 (n>=2.7) 약 200~250 개. 실측 1주일 후 firing rate 재측정.
- **Global prior (1.0, 4.0) 변경은 NEW 버킷에만 적용**. 기존 784 버킷의 alpha/beta 는 원래 (1.0, 3.0) prior + observation 으로 계산되어 있어 그대로 누적 사용.
- **WARN2 잔존**: 라이브 fold-rate 재측정. deploy 정상화 후 1~2주 데이터 누적 후 v4 대비 fold rate 비교.
- **다음 후보**:
  - `wssd_pct` 의 반대편 (low W$SD = LAG, e.g. 도화) 활용 — value bet 폭 확장.
  - Soft label sizing-aware weight (`small=0.5, large=0.2, overbet=0.15`) — 큰 사이즈일수록 value 일 가능성 높으므로 bluff alpha 더 적게.
  - Tournament ICM / bubble detection — `prize_structure` 받아 chip-EV → $-EV 변환.

### 관련 파일

- `packages/core/src/holdem_core/core/config.py` — DASHBOARD_URL/BOT_ID/AUTO_DEPLOY
- `packages/core/src/holdem_core/app.py` — `_deploy_bot()` + run hook
- `packages/core/src/holdem_core/models/events.py` — HandStart Optional 필드
- `packages/core/src/holdem_core/ws/client.py` — ERROR 진단 + spectator skip
- `packages/main_bot/.env` — DASHBOARD_URL/BOT_ID 자리 추가
- `packages/main_bot/src/holdem_main_bot/strategy.py` — profile_min_hands, wssd 상수, _postflop wssd 분기
- `packages/main_bot/src/holdem_main_bot/tournament.py` — push_fold_decision shover VPIP 분기
- `packages/main_bot/src/holdem_main_bot/range_advantage.py` — BB 3bet 감지 (WARN1)
- `packages/main_bot/src/holdem_main_bot/bluff_prior.py` — global prior + soft label split
- `packages/core/src/holdem_core/debug/summary.py` — wssd_pct 누적 컴퓨팅

---

## v5.3.1 (2026-04-23) — HU push_fold 경로 전용 shove range + M-threshold 하향

### 동기

v5.3 배포 후 실측 90게임 (HU 결정 861건) 집계 결과 2등 45% → **56%** 로 악화. 이유는 v5.3 이 **healthy/tight 경로에서만** HU 레인지를 쓰도록 구현됐는데, **HU 결정의 83.5% 가 push_fold/desperate 경로** 로 빠졌기 때문. `hu_open_raise` 발동은 고작 5.2%.

| HU regime | 결정 수 | % |
|---|---|---|
| desperate | 579 | **67.2%** |
| push_fold | 140 | 16.3% |
| tight | 104 | 12.1% |
| healthy | 38 | 4.4% |

HU 첫 진입 M 분포: median 8.2, p25 5.7 → 대부분 이미 push_fold 이하 구간. `_PUSH_PF` (24%) / `_PUSH_DESPERATE` (27%) 는 HU 표준(BTN shove 40~80%) 대비 여전히 타이트 → fold 73.6%.

### 변경

1. **`tournament.py` — HU 전용 shove range 2종 추가**:
   - `_HU_PUSH_PF` (89 hands / **45.7%** combos): pair 전부, Ax 전부, Kx 전부, Qx broadway+suited, suited connector 전부
   - `_HU_PUSH_DESPERATE` (129 hands / **68.6%** combos): `_HU_PUSH_PF` + Qx/Jx/Tx/9x/8x suited + offsuit 확장 (K2o+, Q5o+, J6o+, T7o+, 96o 등)
2. **`push_fold_decision` 에 HU 분기**:
   - `push_set = _HU_PUSH_PF if is_hu else _PUSH_PF`
   - `desperate_push_set = _HU_PUSH_DESPERATE if is_hu else _PUSH_DESPERATE`
   - HU 면 `_PUSH_BLIND_WIDER` union 건너뜀 (HU 에선 무의미)
3. **`push_fold_decision` first-in shove equity gate 도 HU 전용**:
   - HU 면 상대 call range 를 `_HU_CALL_VS_SHOVE` 기준으로 체크 (기본 `_BB_CALL_VS_SHOVE` 사용 시 K5o 같은 HU wider shove 가 equity gate 에 걸려 fold)
   - HU 에선 `shove_min − 0.05` 로 완화
4. **`StrategyConfig` 에 HU M-threshold bonus 3개 추가**:
   - `hu_m_healthy_bonus = 8.0` (m_healthy 20 → 12)
   - `hu_m_tight_bonus` 3.0 → **5.0** (m_tight 12 → 7)
   - `hu_m_push_fold_bonus = 2.0` (m_push_fold 6 → 4)
   - `hu_m_desperate_bonus = 1.0` (m_desperate 3 → 2)
5. **`_preflop_decision` 이 HU 면 위 4개 threshold 가 전부 적용된 `hu_cfg` 로 regime 재판정** + `push_fold_decision(cfg_for_push=hu_cfg)` 로 내려보냄

### 파라미터 (v5.3 → v5.3.1 diff)

| 필드 | v5.3 | v5.3.1 |
|---|---|---|
| `hu_m_tight_bonus` | 3.0 | **5.0** |
| `hu_m_push_fold_bonus` | — | 2.0 |
| `hu_m_desperate_bonus` | — | 1.0 |
| `hu_m_healthy_bonus` | — | 8.0 |

**HU effective thresholds**: healthy 12 / tight 7 / push_fold 4 / desperate 2 (기본 20/12/6/3).

### 측정

**레인지 크기 비교**:

| Set | hands | combos | % of 1326 |
|---|---|---|---|
| _PUSH_PF | 49 | 318 | 24.0% |
| _PUSH_DESPERATE | 52 | 354 | 26.7% |
| **_HU_PUSH_PF** | 89 | 606 | **45.7%** |
| **_HU_PUSH_DESPERATE** | 129 | 910 | **68.6%** |

**단위 시나리오 (HU=True vs False)**:

| 시나리오 | v5.3 | v5.3.1 |
|---|---|---|
| BTN K5o M=4 | fold (v5.3 에서도 fold — gate 걸림) | **allin** (HU_PUSH_PF) |
| BTN Q8o M=6 | fold (push_fold 에서도 fold) | **allin** |
| BTN 96o M=2 | fold (desperate) | **allin** (HU_PUSH_DESPERATE) |
| BTN 74o M=8 | push_fold/fold | **raise 2bb** (M=8 이 tight 로 이동) |
| BTN J6s M=10 | push_fold/fold | **raise 2bb** |
| BTN 32o M=15 | unopened_fold | unopened_fold (의도 유지) |

**리플레이 3000 케이스**:

| | v5.3 (변경 전) | v5.3.1 | Δ |
|---|---|---|---|
| fold | 1855 | 1850 | −5 |
| raise | 478 | **504** | **+26** |
| call | 231 | **242** | **+11** |
| allin | **336** | **305** | **−31** |
| check | 100 | 99 | −1 |

→ HU 구간에서 **push_fold 경로 allin 이 HU_OPEN raise 로 전환 +26**, faced_shove 완화로 call +11, 전체 allin −31. 리플레이 HU 샘플 한계로 작은 Δ 지만 방향 확실.

### 리스크 / 후속

- **HU shove 확대 → dominated 리스크 증가 가능**: K5o/Q8o 로 shove 하는데 상대가 AK/TT 를 가지면 bust. 완화: equity gate 가 여전히 발동. 다만 HU 에선 `shove_min − 0.05` 로 완화 + 상대 call range 도 `_HU_CALL_VS_SHOVE` (넓음) 기준이라 컷이 덜 엄격.
- **라이브 실측 필요**: 리플레이는 기존 방의 action 상황 재현 — HU shove 확대 효과는 새 게임에서만 정확히 측정 가능.
- **후속**:
  - v5.3.2: `_HU_PUSH_PF` 내에서도 M 별 sub-bucket 적용 검토 (M=5 vs M=8 에 같은 range 는 과할 수 있음)
  - v5.3.2: HU BB call_vs_open range (`HU_CALL_BB`) 추가 확장 검토 — 현재 T6o/K6o 등 fold

### 예상 효과

| 지표 | v5.3 (현재) | v5.3.1 목표 |
|---|---|---|
| HU push_fold+desperate 비율 | 83.5% | 50% 미만 |
| HU fold 비율 | 73.6% | 40% 미만 |
| 2등 게임 (90 중) | 41 (45.6%) | 25 (27%) |
| 1등 게임 | 11 (12.2%) | 25 (27%) |

### 관련 파일

- `packages/main_bot/src/holdem_main_bot/tournament.py` — `_HU_PUSH_PF`, `_HU_PUSH_DESPERATE`, push_fold_decision HU 분기 확장, HU equity gate range 교체
- `packages/main_bot/src/holdem_main_bot/strategy.py` — `StrategyConfig` 4 필드 추가/수정, `_preflop_decision` 의 hu_cfg 에 m_healthy/m_push_fold/m_desperate 반영

---

## v5.3 (2026-04-23) — Heads-up(2-handed) 전용 레인지 · blind-bleed 탈출

### 동기

v5.2 까지 56게임 실측에서 **2등 탈락 25건 (45%)** — 1등 5건(9%) 대비 5배. 2등 게임 25건 전부 preflop 탈락이고, 원인은 `forced_showdown_dominated` 15 + `allin_call_dominated` 10. HU(2-handed) 진입 이후 평균 스택 **342 → 160 (−53%)**, 24게임 중 **21게임(87.5%) 에서 HU 동안 스택 감소**.

HU 520 핸드 액션 분포:

| 액션 | 건수 | % |
|---|---|---|
| **fold** | **340** | **65.4%** |
| allin | 77 | 14.8% |
| raise | 13 | 2.5% |
| call | 1 | 0.2% |

### 원인 (코드 레벨)

`packages/main_bot/src/holdem_main_bot/position.py:16` 의 `_MAP[2] = {"btn": "LP", "bb": "BB"}` — HU 를 그냥 LP/BB 로 분류해서 일반 6-max 레인지(`OPEN_LP` 40%, `CALL_VS_OPEN_OOP` 25 hands) 를 사용. HU 표준 (BTN 75~85%, BB defend 65~80%) 대비 심하게 좁음 → 매 핸드 blind 헌납 → `forced_showdown_dominated` 로 탈락.

### 변경

1. **`preflop_ranges.py` — HU 전용 레인지 3종 추가**:
   - `HU_OPEN_BTN` (**87.6%** combos) — HU BTN 은 거의 모든 playable. OPEN_LP ∪ 추가 offsuit/low-suited-gap
   - `HU_CALL_BB` (**38.3%** combos) — BB 에서 BTN open 에 defend. TT+ / AKs+ 제외 (3bet 쪽으로)
   - `HU_3BET_BB` (**8.3%** combos) — value (TT+/AKs+/AKo/KQs/KJs) + light bluff (A3s~A5s, K4s, K5s, 65s, 76s)
   - 헬퍼: `hu_open_range()`, `hu_call_range()`, `hu_three_bet_range()`
2. **`tournament.py` — HU 전용 call-vs-shove 레인지 + gate 완화**:
   - `_HU_CALL_VS_SHOVE` (~40% combos, 41 hands) — 22+, AKs~A7s, AKo~A9o, KQs~K9s, KQo~KTo, QJs~Q9s, QJo/QTo, JTs/J9s/JTo, T9s
   - `push_fold_decision()` 내 `_call_set_for_shover()` 에 HU 분기 — 기본 baseline 을 `_HU_CALL_VS_SHOVE` 로 교체 (loose VPIP 상대면 `_BB_CALL_VS_LOOSE_SHOVE` union 유지)
   - `call_min` 도 HU 에서는 `hu_call_shove_equity_min` (0.40) 사용 — 상대 shove range 가 넓어 gate 완화
3. **`strategy.py::_preflop_decision` 에 HU 경로 통합**:
   - `is_hu = cfg.enable_hu_mode and active_count(players) == 2`
   - HU 면 `m_tight` 를 `m_tight - hu_m_tight_bonus` (12→9) 로 낮춘 복제본으로 regime 재판정 (tight regime 영역 축소)
   - BTN 오픈 set 을 `hu_open_range()`, BB defend set 은 `hu_call_range()` + `hu_three_bet_range()`
   - HU BTN open 사이즈: `hu_open_size_bb` (2.0bb) — 기존 LP 2.5bb 에서 축소 (folding equity 낭비 방지)
   - meta 에 `is_hu` 플래그 + `reason` 에 `hu_open_raise` / `hu_call` / `hu_three_bet` 구분
4. **`StrategyConfig` 신규 필드 4개**:
   - `enable_hu_mode: bool = True`
   - `hu_open_size_bb: float = 2.0`
   - `hu_m_tight_bonus: float = 3.0`
   - `hu_call_shove_equity_min: float = 0.40`

### 파라미터 (v5.2 → v5.3 diff)

| 필드 | v5.2 | v5.3 |
|---|---|---|
| `enable_hu_mode` | — | **True** |
| `hu_open_size_bb` | — | 2.0 |
| `hu_m_tight_bonus` | — | 3.0 |
| `hu_call_shove_equity_min` | — | 0.40 |

기존 필드 변화 없음 — 6-max 경로는 v5.2 그대로.

### 측정

**HU 레인지 크기**:

| Set | hands | combos | % of 1326 |
|---|---|---|---|
| HU_OPEN_BTN | 150 | 1162 | **87.6%** |
| HU_CALL_BB | 75 | 508 | 38.3% |
| HU_3BET_BB | 19 | 110 | 8.3% |
| HU BB total defend | — | 618 | **46.6%** |
| _HU_CALL_VS_SHOVE | 41 | 529 | 39.9% |

**리플레이 분포** (2000 케이스, `.debug/main/room_*.jsonl`):

| | HU mode OFF (v5.2) | HU mode ON (v5.3) | Δ |
|---|---|---|---|
| fold | 1325 | **1309** | **−16** |
| raise | 325 | **335** | **+10** |
| call | 177 | **183** | +6 |
| allin | 106 | 106 | 0 |
| check | 67 | 67 | 0 |

→ HU 샘플 구간에서 **fold 16건이 raise(10)/call(6) 로 전환**. 리플레이의 HU 구간이 제한적이라 차이 작지만 방향은 정확. 라이브 측정 필요.

**단위 시나리오 스모크** (HU=True vs False):

| 시나리오 | HU OFF | HU ON |
|---|---|---|
| BTN K4o first-in | fold (unopened_fold) | **raise 2bb** (hu_open_raise) |
| BB 88 vs BTN raise | call (cold_call) | call (hu_call) |
| BB A9o faced-shove desperate | allin (PUSH_DESPERATE) | allin (HU_CALL_VS_SHOVE) |

**런타임**:
- HU 전용 decide() avg: 1ms (오픈 결정, equity gate 미발동)
- equity gate 발동 시 ~30ms 유지

### 리스크 / 후속

- **HU defend 확장 → dominated 증가 가능**: K7o 같은 marginal 로 call 했다가 강한 BTN open 에 bust 가능. 완화: v5.2 `enable_preflop_equity_gate` 가 HU 에서도 작동. `hu_call_shove_equity_min=0.40` 완화값이라 완전 차단은 안 되지만, `shove_min=0.36` 은 유지돼서 push 측에서 걸러짐.
- **open size 2bb → 상대 defend 자주**: 이게 의도한 HU 기본값. pot 작아 손실 작고, 내가 IP 라 postflop 운영 우위.
- **라이브 필요**: ab_compare 리플레이는 "과거 HU 상황" 샘플이 제한적 — 실측은 새 30~50 게임 후 재측정.
- **후속**:
  - v5.3.x: HU BB defend 에 Tx/9x offsuit 일부 추가 (현재 T6o 등 fold — 너무 엄격)
  - v5.3.x: HU 에서 `iso_limp_range` 재검토 (현재 LP iso-limp 은 HU 에서도 작동)
  - v5.4: 3-handed(3명 남은 상황) 전용 레인지 — HU 와 6-max 중간

### 예상 효과 (목표)

| 지표 | v5.2 | v5.3 목표 |
|---|---|---|
| HU 구간 fold 비율 | 65.4% | 35~40% |
| 2등 게임 (56 중) | 25 (45%) | 15~18 (27~32%) |
| 1등 게임 | 5 (9%) | 12~15 (21~27%) |
| `forced_showdown_dominated` | 15 | 5~8 |
| HU 진입→탈락 스택 감소 | 21/24 (87%) | 10/24 (42%) |

### 관련 파일

- `packages/main_bot/src/holdem_main_bot/preflop_ranges.py` — HU_OPEN_BTN/HU_CALL_BB/HU_3BET_BB 상수 + 헬퍼 3개
- `packages/main_bot/src/holdem_main_bot/tournament.py` — `_HU_CALL_VS_SHOVE` 상수 + `push_fold_decision` 의 HU 분기
- `packages/main_bot/src/holdem_main_bot/strategy.py` — `StrategyConfig` 4 필드 + `_preflop_decision` HU 통합
- `packages/main_bot/src/holdem_main_bot/position.py` — 변경 없음 (Position Literal 유지)

---

## v5.2 (2026-04-23) — 프리플롭 풀 오픈 확장 + equity gate + 탈락 분류기 고도화

### 동기

55게임 실전 (.debug/main/summary_*.json) 집계 결과 **치명적 병목 3개**:

1. **VPIP 17.7% / PFR 15.2%** — TAG 표준(VPIP 22-28%) 대비 과도하게 타이트. LP(BTN/CO)에서 open 24% 만 (표준 40~48%). 블라인드에 갉아먹혀 M-ratio 저하 → desperate 진입 24%.
2. **탈락의 52.2% 가 `allin_call_dominated`** — hand_key match 만으로 shove/call 하면 dominated spot 흘림. 89% 가 preflop 에서 탈락.
3. **탈락 원인 `unknown` 47.8%** — `_classify_elimination_cause` 가 `my_last_action=None` 케이스 (BB 블라인드 묶여 자동 쇼다운) 처리 못함.

### 변경

1. **Preflop 오픈 레인지 확장** (`preflop_ranges.py`):
   - EP: 17 → 18 hands (8.3% combos) — 88, AJo 추가
   - MP: 27 → 28 hands (12.7%) — KJo, A8s 추가, A9s 유지
   - LP: 51 → **81 hands (39.7%)** — Suited Ax/Kx 전부, offsuit A2o+/K9o+/Q9o+/J9o/T9o, suited connectors/gap 전체 (43s, 64s, 75s, 86s, 97s 등)
   - SB: 44 → **59 hands (28.2%)** — LP 에서 약한 offsuit/gap 제외한 버전
2. **m_push_fold 7.0 → 6.0** — M[6-7] 구간이 push_fold(shove-or-fold) 에서 tight(정상 결정) 으로 이동. desperate 진입 속도 완화.
3. **Preflop equity gate** (`tournament.py::_preflop_equity_vs_range`): push_fold_decision 이 shove/call 결정 전에 상대 추정 range 대비 equity_mc 로 2차 검증.
   - shove 전 (raise_cnt≥1 또는 first-in): equity < `preflop_shove_equity_min` (0.36) 이면 취소 → check/fold
   - faced_shove call 전: equity < `preflop_call_shove_equity_min` (0.45) 이면 fold
   - 상대 range 는 raise_cnt 로 동적 선택: 3bet+ → TIER_TOP10, raise 1번 → TIER_TOP20, first-in shove → `_PUSH_PF`
4. **`_PUSH_DESPERATE` 축소**: dominated 빈발하는 J9o/T9o/A5o 제외. A6o/K9o/Q9o 만 유지 (blocker 효과).
5. **`_BB_CALL_VS_SHOVE` 축소**: 77 제거 (88+ 로 한정, 상대 shove 중앙값 대비 58%+ equity).
6. **`_BB_CALL_VS_LOOSE_SHOVE` 신설**: 상대 VPIP≥0.30 (loose pusher) 일 때 77/66/ATs/A9s/KQs/KJs/AJo/KQo 를 call 범위에 union.
7. **`push_fold_decision(profiles=...)` 추가**: opp profiles 주입 → shover VPIP 로 call 범위 동적 조정 (`_last_aggressor_name` + `hands_seen≥15` 게이트).
8. **Bluff Beta prior 임계값 완화** (`StrategyConfig`): `bluff_min_confidence` 0.10→0.05, `bluff_high_threshold` 0.55→0.50. 포스트플롭 샘플이 전체의 10.5% 뿐이라 conf 쌓기 느린 문제 대응.
9. **탈락 분류기 재설계** (`summary.py::_classify_elimination_cause`): 새 카테고리 5개 추가.
   - `forced_showdown_dominated` / `forced_showdown_beat` — `my_last_action=None` + 쇼다운 진입
   - `blind_out` — 액션 없이 쇼다운 없이 탈락
   - `allin_no_showdown` — allin/call 후 쇼다운 정보 없음
   - `allin_bad_beat` — 카드상 이겼는데 탈락 (side-pot)
   - `checked_down_loss` — passive bust

### 파라미터 (v5.1 → v5.2 diff)

| 필드 | v5.1 | v5.2 | 이유 |
|---|---|---|---|
| `m_push_fold` | 7.0 | **6.0** | tight 영역 확장 |
| `enable_preflop_equity_gate` | — | **True** | dominated 방지 |
| `preflop_equity_gate_samples` | — | 400 | 샘플 수 |
| `preflop_shove_equity_min` | — | 0.36 | shove gate |
| `preflop_call_shove_equity_min` | — | 0.45 | call gate |
| `bluff_min_confidence` | 0.10 | **0.05** | 포스트플롭 샘플 부족 |
| `bluff_high_threshold` | 0.55 | **0.50** | 시그널 감지 확대 |

### 측정

**레인지 크기 변화** (combos 기준):

| 포지션 | v5.1 | v5.2 | Δ |
|---|---|---|---|
| EP | ~7.5% | 8.3% | +0.8pp |
| MP | ~11.2% | 12.7% | +1.5pp |
| LP | **~24%** | **39.7%** | **+15.7pp** |
| SB | ~18% | 28.2% | +10.2pp |

**리플레이 분포** (1000 케이스, `.debug/main/room_*.jsonl`):

| | v5.1 (gate OFF, m_push_fold=7.0) | v5.2 (gate ON, m_push_fold=6.0) | Δ |
|---|---|---|---|
| fold | 697 | 721 | +24 |
| **allin** | **89** | **64** | **-25 (-28%)** |
| raise | 126 | 125 | -1 |
| call | 64 | 64 | 0 |
| check | 24 | 26 | +2 |

**→ equity gate 가 작동하여 allin 빈도 28% 감소.** fold 가 증가한 만큼 dominated shove 예방 효과.

**런타임 성능**:
- preflop 일반 결정 (gate 미발동): 0.1ms
- preflop gate 발동 시 (shove/call 결정): ~30ms (samples=400, combos ~100~400)
- 전체 decide() avg: ≈ 11ms (postflop 기존과 동일), 15초 예산의 0.07%

### 리스크 / 후속

- **라이브 측정 필요**: 리플레이는 "기존 액션 상황 재현" 이라 확장된 LP 레인지로 새 open 하는 spot 샘플링 안 됨. 실제 VPIP/PFR 변화는 새 게임 돌려봐야 측정 가능.
- **탈락률 목표**: allin_call_dominated 52.2% → 30% 대. unknown 47.8% → 10% 미만 (새 카테고리로 세분화).
- **ITM 목표**: 49.1% → 55%+, 1등 16.4% → 22~25%.
- **후속**:
  - v5.3: push_fold 구간에서도 equity gate 를 first-in shove 에 적용 (현재 raise_cnt≥1 시에만). 단 _PUSH_PF 는 이미 Nash 기반이라 gate 가 over-tighten 가능.
  - v5.3: `preflop_shove_equity_min` / `preflop_call_shove_equity_min` 튜닝 — 현재 직관값.
  - v5.3: `iso_limp_range` 도 확장된 OPEN_LP 반영해서 재정의 (현재는 구 OPEN_LP 기반).

### 관련 파일

- `packages/main_bot/src/holdem_main_bot/preflop_ranges.py` — OPEN_* 확장
- `packages/main_bot/src/holdem_main_bot/tournament.py` — equity gate, profiles 주입, loose_shove call range
- `packages/main_bot/src/holdem_main_bot/opp_range.py` — `combos_from_keys` 공용 유틸
- `packages/main_bot/src/holdem_main_bot/strategy.py` — StrategyConfig 7 필드 추가, `_preflop_decision(profiles=...)`
- `packages/core/src/holdem_core/debug/summary.py` — `_classify_elimination_cause` 재설계

---

## v5.1 (2026-04-23) — 뻥카 Beta prior (player × street × sizing × action_type)

### 동기

1000게임 × 고정 4명 (익명이1/2/3 + 내 봇) 이라는 setup 에서 **상대별 장기 베팅 성향** 이 매 턴 반복 갱신되어야 "이 베팅이 뻥카인지 진짜인지" 를 추정할 수 있다. v5 의 `estimate_fold_equity` 는 보드 wetness + 상대 tier 만으로 FE 를 뽑아서, 같은 상대가 반복 등장해도 학습이 누적되지 않는다. 쇼다운 공개는 전체 핸드의 **~16% (실측 100/630)** 만이라 fold로 이긴 핸드는 기존 profile 로도 잡히지 않았다.

### 변경

1. **`bluff_prior.py` — Beta(α, β) 저장소**. 키 = `player × street × sizing_bucket × action_type`. `sizing_bucket` 은 pot 대비 증분 비율 → small/medium/large/overbet 4-bucket. `action_type` 은 프리플롭 `raise/3bet/4bet/allin`, 포스트플롭 `bet/raise/allin`. atomic JSON (`.debug/bluff_prior.json`).
2. **라벨링 규칙** (쇼다운 hard label + fold-win soft label):
   - 쇼다운 공개: 그 시점 보드 snapshot 에서 equity_mc 로 equity 재계산. `equity < 0.40` → α+=1 (bluff), `0.40–0.65` → α+0.3 / β+0.3 (semi), `equity ≥ 0.65` → β+=1 (value).
   - fold 로 이긴 aggressive action 이 있고 쇼다운 없음: 마지막 aggressive 에 α+0.1 / β+0.1 (weak soft — bluff 상한만 시사).
3. **`bluff_model.py`** — 런타임에 `req.action_history` 에서 "상대의 가장 최근 aggressive action" 을 찾아 `(prob_bluff, confidence)` posterior 조회. `confidence = n/(n+20)`.
4. **`_postflop` 통합**: EV 엔진 직전에 `estimate_opp_bluff_prob` 호출 → confidence ≥ 0.10 일 때만:
   - `p ≥ 0.55` (뻥카 성향): `margin -= Δ·conf`, `fe -= Δ·conf` (콜 관대, raise 해도 잘 안 fold)
   - `p ≤ 0.25` (value 성향): `margin += Δ·conf`, `fe += Δ·conf` (콜 엄격, raise 하면 fold 잘 함)
5. **`on_hand_result` 훅** — `ws/client.py` 가 `HandResult` 수신 시 `strategy.on_hand_result(evt, pre_history, my_seat)` 를 optional 호출 (getattr). `BalancedStrategy` 가 posterior 업데이트 + 20핸드마다 atomic save.
6. **`scripts/build_bluff_dataset.py`** — 과거 `.debug/room_*.jsonl` 를 순회해서 초기 prior 빌드. 봇 이름은 `--bot-name` 또는 `_run_started` 레코드 자동 감지.

### 파라미터 (StrategyConfig v5 → v5.1 diff)

| 필드 | 기본값 | 설명 |
|---|---|---|
| `enable_bluff_model` | `True` | 전체 토글. False 면 v5 경로 완전 복귀. |
| `bluff_prior_path` | `.debug/bluff_prior.json` | store 경로. `__main__.py` 가 `DEBUG_DIR` 과 join. |
| `bluff_min_confidence` | `0.10` | 이 값 미만 conf 는 조정 무시 (글로벌 prior 상태). |
| `bluff_high_threshold` | `0.55` | p_bluff 이 값 이상 → 뻥카 성향 시그널. |
| `bluff_low_threshold` | `0.25` | p_bluff 이 값 이하 → value 성향 시그널. |
| `bluff_margin_delta` | `0.04` | call margin 최대 조정폭 (conf 로 스케일). |
| `bluff_fe_delta` | `0.10` | fold_equity 최대 조정폭. |
| `bluff_observe_equity_samples` | `200` | 쇼다운 equity 재계산 MC 샘플. |
| `bluff_save_interval` | `20` | N 핸드마다 JSON flush. |

### 측정

**라벨 가용성** (실측 backup room_85*.jsonl 10개 = 579 핸드):
- hands_with_showdown = 91 (15.7%) — hard label
- hands_fold_win = 488 (84.3%) — soft label 후보
- 생성된 버킷 수 = 24, 총 evidence weight = 61.0, 상대 3명

**샘플 posterior** (익명이1):
- `preflop|overbet|raise` — p=0.54, conf=0.48 (n=18.4 evidence) — "풀 레이즈 오픈이 반반 뻥카"
- `flop|large|bet` — p=0.38, conf=0.18 — "세미값 우세"
- `flop|overbet|bet` — p=0.50, conf=0.21 — "절반은 뻥카"

**분포 영향** (500 케이스 v5 vs v5+bluff prior):
- bluff OFF (baseline): raise 60 / call 41 / fold 298 / check 47 / allin 54 / matches_original 436
- bluff ON: raise 61 / call 41 / fold 298 / check 46 / allin 54 / matches_original 437
- Δ = 1건 (check→raise). 차이 작은 이유: 현재 prior 볼륨이 작고 (61 weight / 24 bucket) 대부분 버킷이 min_confidence(0.10) 또는 high/low threshold 밖. **1000게임 쌓이면 confidence 누적으로 영향 확대 예상**.

**결정 시간**:
- v5 baseline: avg ~180ms typical (2000 MC samples, 3-way), worst ~1000ms (9-way 2000+ samples)
- v5+bluff ON (동일 시나리오, 500 MC): **avg 11ms** — bluff 오버헤드는 Beta lookup (dict access, O(1), <1µs) + meta 기록뿐. 15초 예산 대비 0.07%.

### 리스크 / 후속

- **쇼다운 편향** (설계 한계): hard label 은 "쇼다운 간 aggressive action" 에만 붙음 → fold 받아낸 성공한 뻥카는 soft label 만. posterior 는 "called bluff 빈도" 를 overestimate 하고, "successful bluff 빈도" 를 underestimate 가능.
- **sizing_bucket 의 pot_ref 근사**: `_iter_aggressive_in_hand` 에서 running_pot 은 call/raise amount 누적의 근사치. 정확하지는 않지만 ratio 비교에는 OK.
- **콜드스타트**: min_confidence=0.10 이라 ~n≥2.2 evidence 필요. 첫 100핸드 동안은 글로벌 prior (p=0.25, conf=0) 로만 작동 — 영향 없음.
- **자기 자신 섞임 방지**: `BalancedStrategy(bot_name=settings.BOT_NAME)` 로 주입. `build_bluff_dataset.py` 는 `--bot-name` 명시 or `_run_started` 레코드 자동 감지.
- **후속**:
  - v5.2: 실제 1000게임 실전 데이터로 `bluff_high_threshold / bluff_low_threshold` 튜닝 (현재 0.55/0.25 는 직관값).
  - v5.2: hand_result 관찰 시 `equity_samples=200` 을 비동기로 (`asyncio.to_thread`) 이동해서 다음 hand_start 와 겹치지 않게 (현재 동기라 20핸드마다 최대 ~4초 블록 가능 — 서버 pause 구간에 들어가 실질 문제 없지만 안전장치로).
  - v6: `fold_to_cbet_rate` 와 bluff posterior 를 `estimate_fold_equity` 내부에서 blend (현재는 별도 축으로 조정).

### 관련 파일

- `packages/main_bot/src/holdem_main_bot/bluff_prior.py` (신규)
- `packages/main_bot/src/holdem_main_bot/bluff_model.py` (신규)
- `packages/main_bot/src/holdem_main_bot/strategy.py` (import, StrategyConfig, `__init__`, `on_hand_result`, `_postflop` 내부)
- `packages/main_bot/src/holdem_main_bot/__main__.py` (`bluff_prior_path` + `bot_name` 주입)
- `packages/core/src/holdem_core/ws/client.py` (`HandResult` 핸들러에 `on_hand_result` optional 호출)
- `scripts/build_bluff_dataset.py` (신규)

---

## v5 (2026-04-22) — 구조적 재설계 · EV argmax · SPR tree · range_advantage · iso-limp

### 동기

v4 리플레이 (99.4% matches_v3) 는 기대대로였지만, `docs/strategy/` 외부의 **log forensics + code audit** 결과 v0~v4 누적 구조가 한계에 도달:

- **`counterfactual_wrong_fold` 4.1% → v4 실전 축소 효과 측정 불가** — v4 변경은 기본값 조정 위주여서 결정 프레임워크가 그대로. 임계값을 더 만져봐야 같은 cascade 구조 내 국소 이동.
- **결정 근거가 단일 equity-vs-threshold 계단 비교**. fold equity 가 별도 변수로 들어오지 않아 bluff/semi-bluff EV+ spot 을 체계적으로 흘림.
- **SPR (stack/pot ratio) 인식 없음**. 스택 얕은 pot 에선 커밋해야 할 top pair 를 pot-control 로 끌고 가고, deep stack 에서 중간 made hand 로 큰 pot 을 만듦.
- **range-vs-range 시각 부재**. 내 프리플롭 레인지 우위 (예: BTN open 이 A-high 보드에서 combo 우위) 를 무시하고 hand-vs-range 만 봄.
- **프리플롭 limp 대응 공백**. `facing_limp` 분기 없음 — LP 에서 suited 커넥터 한두 장이면 iso-raise 해서 heads-up 에 가야 EV+ 인데 call 또는 check.

위 네 축 (§A EV engine / §B SPR tree / §C range_advantage / §J iso-limp) 을 **추가 레이어** 로 넣되, 각 축을 `enable_xxx` 플래그로 토글 가능하게 설계해 v4 cascade 는 fallback 으로 보존. 근거 원문: `/tmp/holdem-v5/log-forensics.md`, `/tmp/holdem-v5/code-audit.md`, `/tmp/holdem-v5/architecture-proposal.md`.

### 변경

#### A. Fold-equity + EV argmax 엔진 (신규 `ev_engine.py`)

기존 cascade (raise_thr → value_thr → call margin → fold) 를 **네 액션의 EV 계산 후 argmax** 로 대체 (toggle 가능).

- `estimate_fold_equity(opp_tier, board_wetness, profile_stats, phase, multiway) -> float [0.05, 0.70]` — tier × wetness 기본 테이블 + `fold_to_cbet_rate` 프로필 블렌드 (있을 때).
- `action_ev(equity, pot, to_call, my_stack, raise_size, fold_equity) -> EVResult` — `ev_raise`, `ev_call`, `ev_check`, `ev_fold` 계산 후 `choice` (argmax) 반환.
- **Safety floors** (argmax 뒤 적용):
  - `equity < ev_raise_equity_floor` 인데 argmax=raise → raise 제외하고 re-argmax (thin air bluff 방지).
  - `pot_odds ≥ ev_extreme_pot_odds_fold AND equity < pot_odds` → 강제 fold.
- `enable_ev_engine=False` 면 v4 cascade 경로 그대로.

#### B. SPR-indexed decision tree (신규 `spr_tree.py`)

`SPR = my_stack / pot` 버킷 (low/mid/high) 에 따라 **raise_thr / call_margin / draw_pot_ratio / bet_frac** 를 local delta 로 조정.

- low bucket (SPR ≤ 3): raise_thr ↓ 0.05, call_margin ↓ 0.02, draw price 완화 +0.05, bet × 1.2 (commit).
- mid bucket: delta 없음.
- high bucket (SPR > 10): raise_thr ↑ 0.05, call_margin ↑ 0.02, draw 타이트 −0.05, bet × 0.8 (pot control).
- `adjust_for_bucket()` 가 `SPRAdjust` 반환 → `_postflop` 이 threshold 계산 후 이 delta 를 합산.

#### C. range_advantage (신규 `range_advantage.py`, heads-up only)

프리플롭 action sequence 에서 **내 레인지를 재구성** 해 상대 레인지와 보드에서 MC 대결.

- `hero_range_combos(pos, my_preflop_actions, dead_cards, vs_pos)` — 기존 `OPEN_*` / `THREE_BET_*` / `CALL_VS_OPEN_*` 테이블을 재활용해 내 combo 후보 리스트 생성.
- `range_advantage(hero_combos, opp_combos, board, samples)` — hero × opp combo 페어에서 `rank7` MC. 반환 `[0.0, 1.0]`, tie=0.5.
- RA > 0.60 → raise_thr −0.04 (레인지 우위 → value 확장). RA < 0.40 → raise_thr +0.04 (레인지 열세 → bluff 억제).
- 비용: 기본 400 샘플, 실측 +15~30ms. `timeout_ms=3000` 대비 여유.

#### J. Limp-isolation 프리플롭 분기 (신규 `ISO_LIMP_RANGE` + `_preflop_decision` 수정)

unopened 경로에 새 분기: `call_cnt ≥ 1 AND pos=="LP" AND to_call>0 AND hand ∈ ISO_LIMP_RANGE` → iso-raise.

- `ISO_LIMP_RANGE = OPEN_LP ∪ {A8o, A7o, A6o, K9o, Q8s, 97s}` — 59 combos (v5 기본값, 숫자는 §파라미터).
- 사이즈: `iso_limp_size_bb + (limpers - 1) * 1bb` — limper 수에 비례 가산.
- limper 수는 `_count_preflop_calls(action_history)` 로 집계.

#### K. meta 확장

`_build_meta` 에 SPR / RA / EV / iso 필드 추가 (§5 참고). 대시보드 overlay 자동 표시.

### 파라미터 (v4 → v5 diff)

**v4 기본값은 전부 유지** — v5 는 신규 필드 추가만 (24개).

| 구분 | 필드 | 기본값 | 역할 |
|---|---|---:|---|
| §A toggle | `enable_ev_engine` | True | False → v4 cascade. |
| §A FE cap | `ev_fe_top10_cap` | 0.45 | top10 상대 FE 상한. |
| §A FE cap | `ev_fe_default_cap` | 0.65 | 그 외 tier FE 상한. |
| §A safety | `ev_raise_equity_floor` | 0.35 | argmax=raise AND equity<이값 → re-argmax. |
| §A safety | `ev_extreme_pot_odds_fold` | 0.6 | pot_odds≥0.6 AND equity<pot_odds → 강제 fold. |
| §B toggle | `enable_spr_tree` | True | |
| §B bucket | `spr_low_max` / `spr_high_min` | 3.0 / 10.0 | low / high 경계. |
| §B delta | `spr_raise_thr_low` / `_high` | 0.05 / 0.05 | low: −, high: +. |
| §B delta | `spr_call_margin_low` / `_high` | 0.02 / 0.02 | |
| §B delta | `spr_draw_pot_low` / `_high` | 0.05 / 0.05 | |
| §B mult | `spr_bet_frac_low` / `_high` | 1.2 / 0.8 | |
| §C toggle | `enable_range_advantage` | True | heads-up 만. |
| §C MC | `range_advantage_samples` | 400 | MC 샘플 수. |
| §C threshold | `ra_high_threshold` / `_low` | 0.60 / 0.40 | 우위/열세 컷. |
| §C delta | `ra_raise_thr_delta` | 0.04 | raise_thr 조정 크기. |
| §J toggle | `enable_iso_limp` | True | |
| §J size | `iso_limp_size_bb` | 3.5 | base BB 배수 (+1bb/extra limper). |

신규 레인지 테이블: `ISO_LIMP_RANGE` (59 combos).

### 측정

**리플레이** (verifier 독립 재실행, 동일 seed).

Primary dataset `/tmp/holdem-v5/verify-report.md §2.1` — `.debug/backup/room_*.jsonl` **2,461 cases**:

| metric | v4-compat (토글 전부 off) | v5 default | delta |
|---|---:|---:|---:|
| total | 2461 | 2461 | 0 |
| matches_original | **2301 (93.50%)** | **2063 (83.83%)** | **-9.67pp** |
| fold | 1505 (61.2%) | 1499 (60.9%) | -0.3pp |
| check | 458 (18.6%) | 226 (9.2%) | **-9.4pp** |
| call | 52 (2.1%) | 223 (9.1%) | **+7.0pp** |
| raise | 196 (8.0%) | 263 (10.7%) | +2.7pp |
| allin | 250 (10.2%) | 250 (10.2%) | 0 |
| avg_equity | 0.3250 | 0.3256 | ~0 |

Secondary dataset (recent rooms) `.debug/main/room_10*.jsonl` **1,780 cases**: matches_original **94.27%**, check → call 동일 패턴 (-5.5pp / +3.8pp), allin 불변 (7.6% / 7.6%).

MC noise: 2회 재실행 matches_original 2063–2064 범위 (±0.04pp). 에러 0건.

**해석**:
- Structural 목표였던 `counterfactual_wrong_fold` 감소는 실전에선 **check→call 전환** 으로 나타남 (기록 로그의 fold spot 은 이미 대부분 opp bet 없이 check 된 상태라 "fold→call" swap 아닌 "check→call" swap 로 관측됨). historical replay 한계.
- **Allin 0 변동** → SPR low-bucket 이 과커밋하지 않음 확인. aggression 폭발 없음.
- avg_equity 불변 → equity MC 는 structural change 와 독립 (sanity).

**Sanity primitives** (verifier `/tmp/holdem-v5/verify-report.md §5`):
- EV: FE 단조 증가, top10 cap 0.45 준수, multiway deflation OK.
- SPR: 버킷 경계 3/10 정확, low 는 commit (×1.2 bet), high 는 pot control (×0.8).
- RA: BTN open vs mid opp on AKx → 0.681 (broadway 우위, 방향 정상). BB call vs mid opp on 762 → 0.471.
- ISO_LIMP_RANGE 크기 59, OPEN_LP 대비 +6 extra hands.

**v4 rollback smoke**: `StrategyConfig(enable_ev_engine=False, enable_spr_tree=False, enable_range_advantage=False, enable_iso_limp=False)` → 같은 flop spot 에서 reason=`bet_strong` 반환 (v4 경로 정확히 복구).

### 리스크 / 후속

**리스크**:
- **WARN 1 (BB 3bet RA 공백)** — `hero_range_combos(pos='BB', actions=['raise'])` 가 0 combos 반환 (BB 는 `OPEN_BB=frozenset()` 이라 `n_raises=1` 시 빈 집합). `range_advantage()` 는 0.5 (neutral) 로 안전 반환 → no crash, "RA 조정 없음" 만. BB 3bet pot 에서 RA 시그널 미사용. v5.x 에서 "blind 의 첫 raise = 3bet" 판정 추가 예정.
- **WARN 2 (fold rate −0.3pp, 타겟 −5pp 미달)** — 구조적 목표 `counterfactual_wrong_fold` 감소가 replay 기록 상 fold→call 아닌 check→call 로 나타남 (§측정). 라이브 플레이 후 새 로그로 재측정 필요.
- **RA MC 비용** — 400 샘플 × heads-up 매 결정. 측정치 +15~30ms, timeout_ms=3000 대비 여유. 실전 로그에서 느려지면 v5.x 에서 `(pos, preflop_line, board_tuple)` 캐싱.
- **FE heuristic 테이블 기반** — `fold_to_cbet_rate` 가 `.debug/opponent_profiles.json` 에 아직 없어 실질적으로 pure 테이블 FE 사용. `holdem_core/debug/summary.py` 에 누적 예정 (v5.x).
- **`matches_original` 83.8% 는 v4→v5 의 의도된 drop** — 84% 근처가 architect 예측 범위 (82–91%) 내. 90%+ 유지가 목표였다면 문제지만, 구조적 재설계에선 오히려 정상.

**롤백 지점** (우선순위 순):
1. 액션 분포 / allin 폭주 조짐 → `enable_ev_engine=False` 먼저. check→call 복귀.
2. SPR low 버킷 커밋이 과도하면 → `enable_spr_tree=False`.
3. RA 데이터가 노이즈 같으면 → `enable_range_advantage=False`.
4. LP iso-raise 과다 관찰 → `enable_iso_limp=False`.
5. 전부 off → `matches_original` 93.5% 로 v4 경로 복귀 확인 완료.

**후속 (v5.x / v6 이월)**:
- BB 3bet 에서 RA 활성화 — `_hero_class_keys` 에 "blind first raise = 3bet" 분기 추가.
- `fold_to_cbet_rate` 를 `SummaryWriter.write` 에 누적 → FE heuristic profile blend 활성화.
- Polarized sizing (§G) — range_advantage 우위 상황에서 over-bet 옵션.
- Multi-street plan (§F) — flop 결정 시 turn/river 전략 commitment.
- Aggression balance mixing (§I) — v3 듀얼 모드 balanced 경로 실제 분기.
- HandResult adaptation (§D) — `.debug/opponent_profiles.json` 업데이트 → 살아있는 tier 조정 루프.
- N-handed position split (§E) — 2/3/4/5/6-max 별 포지션 세분화 (log 데이터 확보 후).
- `tools/analysis/replay` 의 `BalancedStrategy` 하드 의존 → strategy factory 추상화 (다른 봇도 리플레이).

### 관련 파일

**신규**:
- `packages/main_bot/src/holdem_main_bot/ev_engine.py` — `estimate_fold_equity`, `action_ev`, `EVResult` (§A)
- `packages/main_bot/src/holdem_main_bot/spr_tree.py` — `spr_value`, `spr_bucket`, `adjust_for_bucket`, `SPRAdjust` (§B)
- `packages/main_bot/src/holdem_main_bot/range_advantage.py` — `hero_range_combos`, `range_advantage`, `my_preflop_actions` (§C)

**변경**:
- `packages/main_bot/src/holdem_main_bot/strategy.py` — `StrategyConfig` +24 필드 (§A/B/C/J toggle + knob), `_preflop_decision` 에 iso-limp 분기, `_postflop` 에 SPR adjust → RA adjust → (enable_ev_engine 면) EV argmax / else v4 cascade, `_build_meta` 에 신규 flags, `_count_preflop_calls`/`_my_player_name` 헬퍼 추가
- `packages/main_bot/src/holdem_main_bot/preflop_ranges.py` — `ISO_LIMP_RANGE` (59 combos) + `iso_limp_range()` accessor

Implementer 상세: `/tmp/holdem-v5/impl/changes.md`, `/tmp/holdem-v5/impl/config-diff.md`. Verifier: `/tmp/holdem-v5/verify-report.md` (PASS).

---

## v4 (2026-04-22) — Equity 캘리브레이션 · BB defense 확장 · top10·river 보정

### 동기

v3 구간 실전 로그 **404 룸 / 317 세션 (~16,700 핸드)** 을 분석한 결과:

- `counterfactual_wrong_fold` **494건 (4.1%)** — 폴드했는데 쇼다운 가면 이기던 케이스. 내가 너무 타이트.
  - loss-patterns §C: BTN 31% · SB 20% steal 위치에서 BB 가 과다 폴드.
- `aggressive_bet_into_better` **141건 (1.2%)** — 내가 raise 후 상대가 더 강함. 대부분 3-way pot.
  - loss-patterns §B: paired/wet 보드에서 aggressive action 이 made hand 에 처벌.
- **Equity 캘리브레이션 좌편향**:
  - 0.0-0.2 구간 206회 → 실제 승률 **37.9%** (예상 10%, +27.9pp)
  - 0.2-0.4 구간 190회 → **49.5%** (예상 30%, +19.5pp)
  - 0.4-0.6 구간 181회 → **74.0%** (예상 50%, +24.0pp)
  - → 전 구간 우상향 (상대가 약함/fold equity 과포함). 저 equity 에서 더 call 해도 EV+.
- **상대가 tight 쏠림**: opponent-profiles §5 — 추적 4명 VPIP 모두 < 30% (편경장 9.3%, 익명이2 12.2%, Hugo 18.3%, Wooz 25.0%). v3 의 `profile_vpip_wide=0.40` 은 실전 분포에 비해 경계 무용.
- **vs top10 tier 승률 51.9%** (loss-patterns §G) — 가장 강한 상대 앞에서만 겨우 break-even. bluff-catch 빈도 과다 가능성.
- **river counterfactual_wrong_fold** 빈도 상대적 높음 (pattern-hunter 권고). implied odds 충분한 river 에서 추가 완화로 회수 가능.

*주의: `game_end` 수신 **0/317** 이라 `final_rank` 는 아직 측정 불가 — 전략 판단은 equity 캘리브레이션과 loss_cause_distribution 에 의존. game_end 수신 이슈는 WS 레이어 문제로 전략 범위 밖.*

### 변경

#### A. Equity 임계값 재조정 (`StrategyConfig`, `_postflop`)

저 equity 구간 우상향 + counterfactual_wrong_fold 를 타겟으로 6개 기본값 조정:

- **`equity_call_margin` 0.05 → 0.03** — heads-up postflop 에서 조금 더 call. marginal EV+ spot 회수.
- **`equity_value_bet_threshold` 0.65 → 0.62** — top pair/set 범위에서 value bet 기회 확대.
- **`multiway_raise_penalty` 0.08 → 0.10** — 3-way raise_thr = 0.87, 4-way = 0.97(clamp). multiway 보수화.
- **`equity_call_margin_multiway` 0.08 → 0.07** — multiway 도 약간 call 확대 (저 equity 우상향 반영).
- **`equity_raise_threshold_multiway_base` 0.85 → 0.87** — 3-way raise base 상향 (aggressive_bet_into_better 타겟).
- **`profile_vpip_wide` 0.40 → 0.30** — 실전 상대 max VPIP 25% → 경계 30% 로 좁혀 widen 로직이 실제로 작동.

`equity_raise_threshold=0.80` 은 유지 (0.8-1.0 구간 캘리브레이션 양호, 95.5% vs 예상 90%).

#### B. BB defense 확장 (`preflop_ranges.py::CALL_VS_OPEN_OOP`)

counterfactual_wrong_fold 중 BTN·SB steal 폴드가 큰 비중. OOP call 레인지에 6 핸드 추가:

- **신규**: `KTs, QTs, A9s, AJo, KJo, A9o`
- v3: 18종 → v4: **24종**

#### C. top10 상대 보수 편향 (신규 `StrategyConfig` 필드 + `_postflop` 분기)

vs top10 tier 상대 승률 51.9% 대응. heads-up 한정:

- **`top10_raise_thr_bonus: float = 0.03`** — `opp_tier == "top10"` 이면 `raise_thr = min(0.95, raise_thr + 0.03)`
- **`top10_call_margin_bonus: float = 0.01`** — 동일 조건에서 `margin += 0.01` (bluff-catch 줄임)
- `flags["top10_threat"]` meta 기록.

#### D. River call margin 완화 (신규 `StrategyConfig` 필드 + `_postflop` 분기)

river + implied odds 충분할 때 margin 추가 완화:

- **`river_call_pot_odds_min: float = 0.25`** — 완화 적용 pot_odds 하한
- **`river_call_margin_discount: float = 0.01`** — `phase=="river" AND pot_odds>=0.25` 에서 `margin = max(0.0, margin - 0.01)`
- `flags["river_margin_discount"]` meta 기록.

#### E. 불변 규칙 준수 (변경 없음)

- `Action.meta` 네트워크 유출 가드 — 건드리지 않음
- `_clamp_raise_amount` 패턴 — 건드리지 않음
- `_PUSH_DESPERATE` — 건드리지 않음 (v1 dominated 탈락 경험 존중)
- `register_decision_logger(__name__)` — 유지

### 파라미터 (v3 → v4 diff)

| 필드 | v3 | v4 | 변화 |
|---|---:|---:|---|
| `equity_call_margin` | 0.05 | **0.03** | -0.02 |
| `equity_value_bet_threshold` | 0.65 | **0.62** | -0.03 |
| `equity_raise_threshold` | 0.80 | 0.80 | (유지) |
| `multiway_raise_penalty` | 0.08 | **0.10** | +0.02 |
| `equity_call_margin_multiway` | 0.08 | **0.07** | -0.01 |
| `equity_raise_threshold_multiway_base` | 0.85 | **0.87** | +0.02 |
| `profile_vpip_wide` | 0.40 | **0.30** | -0.10 |
| `top10_raise_thr_bonus` | — | **0.03** | 신규 |
| `top10_call_margin_bonus` | — | **0.01** | 신규 |
| `river_call_margin_discount` | — | **0.01** | 신규 |
| `river_call_pot_odds_min` | — | **0.25** | 신규 |
| `CALL_VS_OPEN_OOP` 크기 | 18 | **24** | +6 (`KTs, QTs, A9s, AJo, KJo, A9o`) |

Meta 플래그 추가: `top10_threat` (bool), `river_margin_discount` (bool, 해당 spot 에서만).

### 측정 (v3 vs v4 리플레이)

replay-tester 산출 (`/tmp/holdem-v4/v3-vs-v4-diff.json`). v3 baseline (commit `fd520ca`) vs v4 working tree, 404 룸에서 복원한 **16,111 `action_request`** 전체를 두 `BalancedStrategy` 인스턴스에 동일 `seed=0` 으로 돌려 직접 비교.

수용 기준 전부 통과:

| 기준 | 임계값 | 측정 | 판정 |
|---|---|---|---|
| matches_original (v3↔v4 일치율) | ≥ 0.80 | **0.99398** (99.4%) | ✅ |
| \|Δfold\| | ≤ 5pp | **-0.459pp** | ✅ |
| \|Δcall\| | ≤ 8pp | **+0.472pp** | ✅ |
| \|Δraise\| | ≤ 8pp | **+0.087pp** | ✅ |
| \|Δcheck\| | ≤ 8pp | **-0.106pp** | ✅ |
| \|Δallin\| | ≤ 8pp | **+0.006pp** | ✅ |
| Exception | 0 | v3=0, v4=0 | ✅ |

Action histogram (16,111 cases):

| action | v3 count | v4 count | v3 % | v4 % | Δ pp |
|---|---:|---:|---:|---:|---:|
| fold | 11,600 | 11,526 | 72.000 | 71.541 | **-0.459** |
| call | 410 | 486 | 2.545 | 3.017 | **+0.472** |
| check | 935 | 918 | 5.803 | 5.698 | -0.106 |
| raise | 1,441 | 1,455 | 8.944 | 9.031 | +0.087 |
| allin | 1,725 | 1,726 | 10.707 | 10.713 | +0.006 |

결정 전이 (불일치 97건 = 0.60%):

| transition | 건수 | 주 원인 |
|---|---:|---|
| fold → call | 74 | `equity_call_margin` 0.05→0.03 + BB defense 6 핸드 확장 |
| check → raise | 17 | `equity_value_bet_threshold` 0.65→0.62 |
| raise → call | 3 | `multiway_raise_penalty` 0.08→0.10 + multiway base 0.87 |
| call → allin / allin → call | 3 | 경계 spot, equity MC noise |
| 같은 action, 다른 amount | 6 | value_thr 하향이 sizing 에 영향 |

Phase 분포:

| phase | cases | 변경 건수 | 비율 |
|---|---:|---:|---:|
| preflop | 14,608 | 66 | 0.45% |
| flop | 718 | 16 | 2.23% |
| turn | 471 | 9 | 1.91% |
| river | 314 | 6 | 1.91% |

변경이 의도대로 landed 된 대표 spot:
- **BB defense 확장**: room 7026 hand27 (AJo, pot 45/to_call 20) · room 7105 hand28 (QTs, 40/15) · room 7128 hand14 (A9o, 22/7) — 모두 fold→call.
- **Value bet 확장**: room 7096 hand11 turn KQ on Qd2s9d3d · room 7109 hand14 flop QQ on 6d9d2c · room 7121 hand2 flop KK on 4sAh7d — check→raise.
- **Multiway 보수화**: room 7130 hand19 flop AA on 5s7hKh (flush-draw) — raise→call (pot control 전환).

기대 효과 (v4 실전 로그 수집 후 재측정 예정):

| 지표 | v3 실측 | v4 기대 |
|---|---|---|
| `counterfactual_wrong_fold` | 4.1% (494건) | 2–3% (BB defense + margin 축소 + river 완화) |
| `aggressive_bet_into_better` | 1.2% (141건) | 0.8–1.0% (multiway raise_thr 상향) |
| vs top10 tier 승률 | 51.9% | 54–58% (보수 편향) |

**Round 2 재측정** (pattern-hunter 권고 반영 후, CALL_VS_OPEN_OOP A9s/AJo/KJo/A9o 추가 + river discount 추가):

| 지표 | Round 1 | Round 2 | Δ |
|---|---|---|---|
| matches_original | 99.398% | **99.429%** | +0.031pp |
| diff 건수 | 97 | 92 | −5 |

**중요 관찰** (replay-tester Round 2 verdict):
- BB defense 추가 4 핸드 (A9s/AJo/KJo/A9o): 첫 30 diff 중 17건 landed — 효과 확인.
- **River discount 는 실전 로그에서 발동 0건** — 조건 (`phase=river AND pot_odds≥0.25 AND to_call>0`) 이 까다로워 쇼다운 도달 표본에서 거의 안 나타남. 사실상 non-op. v4.1 에서 `pot_odds_min` 0.25 → 0.20 완화 검토.
- loss-patterns 대비 실제 공격 비율: counterfactual_wrong_fold 494건 → 71건 (14.4%), aggressive_bet_into_better 141건 → 1건 (0.7%) 커버. 변화 폭 보수적 (사용자 지시 `matches_original ≥ 0.80` 통과 우선).

### 리스크 / 후속

**리스크**:
- **BB defense 확장 (6 핸드)** — `KJo`, `A9o` 는 dominated range 만나면 손해. pot_odds 의존 spot 에서만 안전.
- **River margin 완화** — hero call 빈도 ↑. bluff-catch 증가가 강한 상대엔 역효과 가능. top10 bonus 로 부분 상쇄 설계.
- **경계 spot 3건 (call↔allin)** — equity MC noise 영향. `_PUSH_DESPERATE` 는 건드리지 않아 dominated 탈락 우려 없음.
- **v3 게임 종료 0/317** — 네트워크 이슈 지속. v4 에서도 `final_rank` 측정 불가 가능성. WS 레이어 개선은 전략 범위 밖.

**롤백 지점** (우선순위 순):
1. matches_original < 0.85 이면 `KJo`, `A9o` 먼저 롤백 → BB defense 4 핸드만 유지.
2. < 0.80 이면 river discount 도 롤백.
3. 기본 StrategyConfig 6건은 수치 기반 명확히 합의됨 — 롤백 최후 순위.

**후속 (v5 예정 / 범위 밖)**:
- Top10 상대 steal 축소 — LP `open_range` 에서 K9o/Q9o 등 제외. `_preflop_decision` 에 `opp_class` 전달하는 구조 리팩터 필요.
- Wet board `bet_frac_wet_strong` 조건부 완화 — aggressive_bet_into_better 141건 중 wet board 비율 파악 후.
- Regime-aware 로그 (session 단위 healthy/tight/push_fold/desperate 기록).
- v3 듀얼 모드의 balanced 경로 실제 구현 (v3.x → v4 범위 밖, 이월).
- `narrow_by_postflop` 의 turn/river 확장.
- ICM 반영 (chip-EV → $-EV).

### 관련 파일

**변경**:
- `packages/main_bot/src/holdem_main_bot/strategy.py`
  - `StrategyConfig` 기본값 6건 조정, 신규 필드 4건 (`top10_raise_thr_bonus`, `top10_call_margin_bonus`, `river_call_margin_discount`, `river_call_pot_odds_min`)
  - `_postflop`: `top10_threat` 분기 (raise_thr + margin bonus), river margin discount 분기
  - meta flags: `top10_threat`, `river_margin_discount`
- `packages/main_bot/src/holdem_main_bot/preflop_ranges.py`
  - `CALL_VS_OPEN_OOP` 18종 → 24종 (`KTs, QTs, A9s, AJo, KJo, A9o` 추가)

**신규**: 없음 (기존 파일 확장).

---

## v3 (2026-04-22) — Flush Draw 규칙 · 상대 분류기 · 듀얼 모드 뼈대

### 동기

v2 를 20룸(`room_858~877`) 실전에 돌린 결과:

| 지표 | v1 (15룸) | v2 (20룸) |
|---|---|---|
| 평균 생존 핸드 | 61 | **58** (유사) |
| `counterfactual_wrong_fold` | 7.6% | **4.4%** (↓, call margin 완화 효과) |
| `aggressive_bet_into_better` | 0.7% | 1.1% (↑, desperate 과도 축소?) |
| equity 0.2-0.4 승률 | 45.5% | **54.3%** (↑) |
| equity 0.4-0.6 승률 | 66.7% | 50% (↓, multiway threshold 과다) |
| `game_end` 수신 | 0/15 | 0/20 (네트워크 이슈 지속) |

관찰 두 가지:
1. **플러시 드로우 같은 implied-odds 손** 이 v2 에서 손해 — `draw_live` 상태에서 equity=0.3~0.4 이면 fold, 또는 약한 value_bet 으로 오버베팅해서 상대 call 못 얻음.
2. **중요한 메타 인식** (사용자 힌트): 현재 상대는 스크립트 봇. 다음 상대는 봇 개발자가 만든 봇 — 우리 결정론적 패턴이 그대로 역설계됨. 같은 전략으로는 둘 다 최적일 수 없다.

### 변경

#### V. 플러시 드로우 규칙 (`draw_detect.py`, `rule_based._postflop`)

사용자 규칙: "홀카드 같은 모양 + 플롭에 내 슈트 2장 이상 = 플래시 노려봄. 단, 베팅 크게 안 올림."

**V.1 `app/strategy/draw_detect.py` 신설**
- `detect_draws(hole, board) -> DrawInfo`
- `DrawInfo`: `has_flush_draw, has_flush_made, my_suit_count, has_oesd, has_gutshot, outs, is_live_draw`
- 플러시 드로우: 홀 suited + hole+board 에서 내 슈트 4장 (= 4-flush, 9 outs)
- 스트레이트 드로우: OESD(4 연속) 8 outs, gutshot 4 outs
- `outs` 는 단순 합 (중복 보정 없음 — MC equity 가 실제 수치 제공)

**V.2 `_postflop` 에 드로우 우선 분기**
- `draw.is_live_draw AND equity < raise_thr AND made_hand <= one_pair` → "drawing hand"
- 조건: `cfg.draw_no_aggression=True` (기본) 이면 raise/큰 bet 금지
  - `to_call == 0` → `check` (reason=`draw_check_free`)
  - 가격 싸면 (`to_call/(pot+to_call) <= 0.35` 그리고 `to_call/my_stack <= 0.15`) → `call` (reason=`draw_call_cheap`)
  - 비싸면 일반 equity 분기로 fallthrough (fold 가능)
- 효과: 이전에 value_bet 으로 드로우 손이 라이트 베팅 나가던 것 차단. 드로우는 싸게 보고 싶을 때만 진행.

**V.3 StrategyConfig 신규**
- `draw_call_pot_ratio_max: float = 0.35`
- `draw_call_stack_ratio_max: float = 0.15`
- `draw_no_aggression: bool = True`

**V.4 Meta 필드**
- `draw_flush, draw_flush_made, draw_oesd, draw_gutshot, draw_outs, draw_live` 기록

#### M. 듀얼 모드 뼈대 (`opponent_class.py`, `rule_based.py`)

완전한 balanced 전략은 v3.x 이후. 이번엔 **분류 + 모드 기록** 까지.

**M.1 `app/strategy/opponent_class.py` 신설**
- `OpponentClass = Literal["unknown", "script", "adaptive"]`
- `classify_opponent(profile) -> OpponentClass`
  - `unknown`: hands_seen < 20
  - `script`: VPIP-PFR 차이 ≤ 0.10 AND 3bet ≤ 3% (단조로운 패턴)
  - `adaptive`: 3bet ≥ 5% OR VPIP-PFR 차이 ≥ 0.20 (변동성)
- `classify_all(profiles) -> dict[name, class]`
- `resolve_table_mode(active_names, classes, strategy_mode="auto") -> str`
  - "auto" 면: adaptive 1명+ → "balanced", 전원 script → "exploit", 외 → "balanced"(보수적)

**M.2 `BalancedStrategy` 에 분류기 연결**
- `__init__` 시 `classify_all(self._profiles)` → `self._opp_classes`
- `reload_profiles()` 시 재분류
- `decide()` 에서 `_resolve_mode_for_request(req)` 호출, meta 에 `table_mode` / `cfg_mode` 기록
- **현재는 mode 값만 기록**. 실제 exploit/balanced 분기는 v3.x 에서 추가 예정.

**M.3 StrategyConfig.mode**
- `"auto" | "exploit" | "balanced"`. 기본 `"auto"`.
- `"exploit"` 강제 시 현재 v2 로직 고정 (script 봇 상대 최대 활용)
- `"balanced"` 는 현재 exploit 과 동일 경로 — v3.x 에 mixed strategy 추가 후 분기

### 파라미터 (v2 → v3 diff)

| 필드 | v2 | v3 | 용도 |
|---|---|---|---|
| `draw_call_pot_ratio_max` | — | 0.35 | 드로우 call 허용 pot 비율 |
| `draw_call_stack_ratio_max` | — | 0.15 | 드로우 call 허용 스택 비율 |
| `draw_no_aggression` | — | True | 드로우만으로 raise/bet 금지 |
| `mode` | — | `"auto"` | 듀얼 모드 선택 |

### 측정 (20룸 리플레이 v2 → v3)

`room_858~877` 1154 결정 기준:

| 항목 | 값 |
|---|---|
| 드로우 감지 | 55회 (4.8%) |
| 드로우 → `check_free` | 46회 |
| 드로우 → `call_cheap` | 3회 |
| 드로우 fallthrough (일반 equity 분기) | 6회 |
| 액션 분포 fold/check/call/raise/allin | 761 / 183 / 11 / 79 / 120 |

v2 동일 로그 대비:
- 드로우 손으로 value_bet 나갔던 케이스 → check 전환 (expected ~40회 절약)
- raise 비율 유사, 드로우 손이 이제 오버베팅 하지 않음

### 듀얼 모드 관찰

현재 `.debug/opponent_profiles.json` 에 수십 명 중 adaptive 1~2명 (익명이3 같은 high-VPIP), 나머지 unknown/script. table_mode 가 `balanced` 로 분류되는 경우 많음 = 첫 iteration 에선 conservative default 동작. 이건 의도된 안전 기본값.

### 리스크 / 후속

- **드로우 규칙 과적용**: `made_hand_rank <= 2` (high_card or one_pair) 에만 적용. top pair 이상 made hand 는 기존 value_bet 경로 유지.
- **드로우 fold 회피**: 가격 비싸면 그대로 fold. 블라인드 소진 가능성 낮음 (드로우 만 이유로 감).
- **`is_live_draw` 중복 카운트**: flush + OESD 동시일 때 outs 합산(중복 제거 안 함) — `equity_mc` 가 실제 수치 주니 문제 없음.
- **듀얼 모드 분류 조기 판정**: hands_seen=20 로 낮춤. 25~30 으로 상향 고려 (단기 변동에 덜 민감하게).
- **"balanced" 가 현재 exploit 과 동일**: 당분간 meta 기록만. v3.x 에서 mixed strategy 구현 시 실제 분기 추가:
  - 3bet bluff 빈도 (IP: JJ/AQs → bluff 포함)
  - Bet sizing randomization (dry 강 → 0.33/0.5/0.75 분산)
  - Borderline hand 에 fold/call/raise 혼합 (hash(hand+seed)%100)
- **자체 적대 봇 미구현**: "간단 TAG/LAG/Nit 봇 vs 우리" 검증 아직. v3.x 이후 `scripts/adversarial_sim.py` 로 추가 예정.

### 관련 파일

**신규**:
- `app/strategy/draw_detect.py` — `DrawInfo`, `detect_draws()`
- `app/strategy/opponent_class.py` — `OpponentClass`, `classify_opponent()`, `classify_all()`, `resolve_table_mode()`

**변경**:
- `app/strategy/rule_based.py` — `StrategyConfig` 확장 (draw_*, mode), `_postflop` 에 드로우 분기, `BalancedStrategy._resolve_mode_for_request()`, `decide()` 에서 table_mode 기록
- `docs/strategy/CHANGELOG.md` — v3 섹션 맨 위에 추가 (v2 유지)

---

## v2 (2026-04-22) — 멀티웨이 페널티 · Position 오픈사이즈 · Desperate 축소 · Opponent Profile 소비

### 동기

v1 을 실전 15룸(`room_843~857`) 에 돌린 결과 **생존 핸드 38→61 (+60%)** 로 개선되었지만 구조적 leak 이 분명. 15룸 리플레이 분석에서 도출된 핵심 실책:

| 관찰 | 수치 |
|---|---|
| 4-way 오픈 승률 | **8.8%** (6/68) — 상대 수 증가에 공격성 과다 |
| EP 에서 raise 승률 | **0%** (0/10) — 모든 포지션 open_size 2.5bb 동일 |
| M=6~10 tight regime 승률 | **36.9%** — desperate(33.3%) 보다 높은 역설 (경계 설정 오류) |
| 탈락 4건 원인 | 모두 desperate allin 에서 dominated (KT vs 24, Q8 vs JJ, JA vs 76, J8 vs T9) |
| BB 승률 | **23.1%** (최악) — 3bet 거의 0, fold 63회 |
| 포스트플롭 call 비율 | **1.5%** (14/955) — equity_call_margin=0.03 극단적으로 타이트 |
| equity 0.0~0.2 구간 | **28패/37회 (24.3% 승률)** — 약한 에쿼티로 과도한 call |
| 상대 프로필 소비 | **0** — `.debug/opponent_profiles.json` 쌓였지만 미활용 |

### 변경

#### G. 즉효 파라미터 튜닝

**G.1 position-별 open_size 차등** (`rule_based.py:_preflop_decision`, `preflop_ranges.py`)
- `StrategyConfig.open_size_bb_by_pos: dict[Position, float]` 신설 — `{EP:3.5, MP:3.0, LP:2.5, SB:2.5, BB:2.0}`
- `open_size_bb=2.5` 는 deprecated fallback 으로 유지. EP 에서 상대 제거 효과, LP 에서 steal 타이트.
- tight regime 추가 압박: 포지션 사이즈 +0.5bb

**G.2 멀티웨이 페널티 & threshold 재구성** (`rule_based.py:_postflop`)
- `multiway_raise_penalty` **0.05 → 0.08**
- 신규 `equity_raise_threshold_multiway_base=0.85` — 멀티웨이 raise 최소 기준
- 3-way(n_opps=2): `raise_thr = 0.85`
- 4-way(n_opps=3): `raise_thr = 0.85 + 0.08 = 0.93`
- 5-way(n_opps=4): `raise_thr = 0.85 + 0.16 = 0.95`(clamp)
- 이전 로직 `raise_thr + penalty*(n-1)` 의 중복 가산 제거

**G.3 멀티웨이 call margin 분리** (`rule_based.py:_postflop`)
- 신규 `equity_call_margin_multiway=0.08` (heads-up `equity_call_margin=0.03→0.05`)
- 4-way: 추가 `+0.02 * (n_opps-2)`

**G.4 M-ratio 경계 상향** (`StrategyConfig`)
- `m_tight` **10.0 → 12.0** (healthy→tight 경계. tight regime 더 자주 발동)
- `m_push_fold` **6.0 → 7.0** (desperate 구간 축소)
- 근거: v1 에서 tight regime(M=6-10) 승률이 healthy(M>20) 보다 높았다 = healthy 에서 약한 raise 과다

**G.5 BB defense 확장** (`StrategyConfig`)
- `preflop_call_cap_bb` **8.0 → 10.0** (BB blind 이미 투입, call 상한 완화)

**G.6 멀티웨이 bet 사이즈 축소** (`board.py:size_bet`, `StrategyConfig`)
- 신규 `bet_frac_dry_strong_multiway=0.33`, `bet_frac_wet_strong_multiway=0.5`
- 신규 `bet_frac_dry_value_multiway=0.25`, `bet_frac_wet_value_multiway=0.33`
- `size_bet(..., n_opps=1)` 파라미터 추가. n_opps≥2면 multiway 변형 사용
- 근거: 멀티웨이에서는 fold equity 낮음. 큰 베팅은 call 유도, 강한 value만 수집

#### H. 탈락 패턴 교정 (`tournament.py`)

**H.1 `_PUSH_DESPERATE` 축소**
- 제거: `A2o, A3o, A4o, K7o, K8o, Q8o, J8o, J8s, T8o, T8s, 97s, 76s`
- 유지: `_PUSH_PF + {A5o, A6o, K9o, Q9o, J9o, T9o}` (high-card broadway 만)
- 근거: v1 4건 탈락 모두 이 range 로 push 후 dominated (KT-24, Q8-JJ, JA-76, J8-T9)

**H.2 desperate faced_shove 분기 추가** (`push_fold_decision`)
- 이전: desperate 에서 상대가 이미 allin 해도 KT 같은 marginal 로 shove → dominated
- 변경: `faced_shove` 면 `_BB_CALL_VS_SHOVE` (QQ+, AKs, AKo, JJ, AJs 등) 만 call, 나머지 fold

#### I. Opponent Profile 소비 (`opp_range.py`, `rule_based.py`, `client.py`)

**I.1 profile 로딩**
- `StrategyConfig.profile_path=".debug/opponent_profiles.json"` 신설
- `BalancedStrategy.__init__` 에서 1회 로드 → `self._profiles: dict[str, OppProfile]`
- 게임 종료(`GameEnd`) 시 `client._dispatch` 가 `strategy.reload_profiles()` 호출

**I.2 `estimate_tier` 확장**
- 시그니처: `estimate_tier(name, history, profile=None, profile_min_hands=15, profile_vpip_tight=0.18, profile_vpip_wide=0.40)`
- base tier(이번 핸드 history) 계산 후:
  - `profile.hands_seen >= profile_min_hands` 이고 VPIP < 0.18 → 한 단계 **좁힘** (top20 → top10)
  - VPIP > 0.40 → 한 단계 **넓힘** (top20 → top40)
- tight opponent(VPIP 12.6%) 의 raise 는 실제로 더 강하니 내 call 더 보수적
- loose/limper(VPIP 39%) 는 약한 range 포함 — 내 value bet 사이즈 더 크게

**I.3 배선**
- `primary_threat(req, profiles=...)`, `all_opp_combos(req, ..., profiles=...)`, `infer_opp_combos(req, ..., profiles=...)` 시그니처 확장
- `rule_based._postflop` 이 `self._profiles` 를 opp_range 계층에 전달
- flags 에 `profiles_loaded: int` 기록 (대시보드 메타)

### 파라미터 (v1 → v2 diff)

| 필드 | v1 | v2 | 변화 |
|---|---|---|---|
| `open_size_bb` | 2.5 | 2.5 (fallback) | deprecated |
| `open_size_bb_by_pos` | — | `{EP:3.5, MP:3.0, LP:2.5, SB:2.5, BB:2.0}` | 신규 |
| `multiway_raise_penalty` | 0.05 | **0.08** | +60% |
| `equity_call_margin` | 0.03 | **0.05** | +67% |
| `equity_call_margin_multiway` | — | 0.08 | 신규 |
| `equity_raise_threshold_multiway_base` | — | 0.85 | 신규 |
| `m_tight` | 10.0 | **12.0** | +2 |
| `m_push_fold` | 6.0 | **7.0** | +1 |
| `preflop_call_cap_bb` | 8.0 | **10.0** | +2 |
| `bet_frac_dry_strong_multiway` | — | 0.33 | 신규 |
| `bet_frac_wet_strong_multiway` | — | 0.5 | 신규 |
| `bet_frac_dry_value_multiway` | — | 0.25 | 신규 |
| `bet_frac_wet_value_multiway` | — | 0.33 | 신규 |
| `profile_path` | — | `.debug/opponent_profiles.json` | 신규 |
| `_PUSH_DESPERATE` 크기 | 68 | 56 | -12 (핸드 키) |

### 측정 (15룸 리플레이 v1 → v2)

v2 config 로 v1 수집 로그(`room_843~857`, **955 결정**) 를 리플레이 한 결과:

| 지표 | v1 실제 | v2 리플레이 |
|---|---|---|
| 총 결정 | 955 | 955 |
| v1 과 동일 결정 | 955 (100%) | 929 (97.2%) — 26건이 v2 에서 다르게 결정 |
| 액션 분포 fold | 58% | 59% |
| 액션 분포 check | 26% | 20% |
| 액션 분포 call | 16% | 1.4% |
| 액션 분포 raise | 9.1% | 8.8% |
| 액션 분포 allin | 9.7% | 10.5% |
| avg equity (postflop 결정 기준) | — | 0.31 |

**해석**: v2 는 v1 과 대부분 같은 결정을 내리지만, 주로 (a) desperate push range 축소로 marginal shove → fold 전환, (b) 멀티웨이 raise_thr 상승으로 몇몇 raise → check/fold 전환, (c) call margin 상향으로 조금 더 많은 call 유지. 큰 차이는 실전 재돌림 후 게임 종료율·탈락 회피로 판가름 예정.

**실전 목표 (v2 로 15~30 룸 추가 돌린 후 검증)**:

| 지표 | v1 (15룸) | v2 목표 |
|---|---|---|
| 평균 생존 핸드 | 61 (41~75) | 75+ |
| 게임 종료(`game_end` 수신) | **0/15** | 7/15 이상 |
| 명시적 탈락(`hand_result.eliminated`) | 4/15 (27%) | 2/15 이하 (15%) |
| BB 승률 | 23.1% | 30%+ |
| 4-way 오픈 승률 | 8.8% | 15%+ |

**⚠ 주의**: v1 세션 15개 모두 `ended=False` — 게임 완전 종료(`game_end` 이벤트) 를 관측한 케이스 0건. 봇이 중도에 회수됐거나, 네트워크 중단/서버 이슈로 로그가 잘린 것으로 추정. 따라서 "최종 순위" 기반 지표는 v1 데이터로 판단 불가 → v2 실전에서는 `game_end` 수신 여부를 함께 모니터.

### 리스크 / 후속

- **파라미터 튜닝 과적합**: 15룸만으로 coord-descent 시 5명 상대(익명이1~3)에 과적합 가능. `scripts/ab_compare.py --coord-descent` 는 주요 축 3~4개로 제한하여 사용.
- **프로필 과의존**: `hands_seen >= 15` 에서 VPIP 판정. 표본 작은 상대엔 오판 가능. `profile_min_hands` 를 25로 상향 고려.
- **멀티웨이 threshold 과잉**: 5-way+ 에서 raise_thr=0.95 clamp. 사실상 거의 raise 안 함 → value bet 놓칠 수 있음. 실전 데이터로 적절성 재평가.
- **`_PUSH_DESPERATE` 너무 좁힘 → 블라인드 소진**: M<3 에서 fold 만 하면 blind 에 죽음. 다음 데이터로 재평가.
- **`Action.meta` 스키마 확장**: v2 에서 `profiles_loaded`, `open_size_bb` 등 추가 → 대시보드 overlay 자동 반영 (flow.py `decision_overlay_html` 이 모르는 키는 무시).
- **후속 v3 아이디어**:
  - Position 인식 실패 시 보수적 fallback 검증 (`utg1`, `mp1` 등 실서버 표기 조사)
  - 포스트플롭 turn/river 상대 레인지 추가 좁히기 (현재 flop raise 까지만 반영)
  - 프로필 기반 bet sizing 조정 (loose opponent 엔 큰 value, tight 엔 작은 value)
  - ICM 반영 (현재 chip-EV 기반)
  - 스택 깊이별 3bet/4bet mult 차등

### 관련 파일

**변경**:
- `app/strategy/rule_based.py` — `StrategyConfig` 확장, `_preflop_decision` position-aware open_size, `_postflop` multiway threshold 재구성, `BalancedStrategy` profile 로딩·reload
- `app/strategy/tournament.py` — `_PUSH_DESPERATE` 축소, `push_fold_decision` 에서 desperate+faced_shove 분기
- `app/strategy/opp_range.py` — `_tighten_tier`/`_widen_tier` 헬퍼, `estimate_tier`/`primary_threat`/`all_opp_combos`/`infer_opp_combos` 에 `profile` 파라미터 체인
- `app/strategy/board.py` — `size_bet(..., n_opps=1)` 파라미터 추가, multiway bet_frac 분기
- `app/bot/client.py` — `GameEnd` 시 `strategy.reload_profiles()` 훅

**신규**: 없음 (모두 기존 파일 확장)

---

## v1 (2026-04-21) — Position · M-ratio · Preflop Raise · Multiway · Board Texture

### 동기

v0 로 실전 5개 방(`room_836/837/838/839/842`) 전부 **31~48핸드 안에 탈락(전패)**. 로그 분석 결과 구조적 약점이 분명했다.

- 프리플롭 raise **0%** → 항상 reactive, 이니셔티브 못 잡아 블라인드 유지 불가
- `seat` 는 받으면서도 전략에 **position 미반영** — UTG 에서도 BTN 에서도 같은 레인지
- `my_stack / (SB+BB) = M` **미반영** — 블라인드가 올라가도(Lv1 BB=2 → Lv6 BB=20) 같은 콜 상한(`max(pot*2, 16)`) 적용되어 짧은 스택이 타이트하게 말라죽음
- 멀티웨이(활성 상대 2+) 상황을 **1:1 equity 로 근사** → 3-way 에서 top pair 같은 손을 과대평가해서 콜/벳, 결국 SD 에서 패배
- `CALL_FLOOR = 16` 하드코딩 → 블라인드 10/20 구간에서도 16 이 상한이라 사실상 의미 없는 상한

### 변경

#### 프리플롭 — 엔진 전면 재작성 (`rule_based._preflop_decision`)

v0 의 `is_pair OR is_suited OR is_top300` → `check/call/fold` 3지선다를 제거하고 4단계 파이프라인으로 교체.

1. **M-ratio 체크** → `push_fold_decision` 위임
   - `regime = m_regime(effective_m(req), cfg)` 로 `healthy | tight | push_fold | desperate` 판정 (`tournament.py`)
   - M < `m_push_fold` (기본 6) 구간에서는 Nash push chart 근사 (`push_fold_decision`)
     - `desperate` (M<3): any pair / any ace / any broadway pair / K9+ suited → shove
     - `push_fold` (3≤M<6): 22+, A2s+, A7o+, KTs+, KJo+, QTs+, QJo, JTs → shove. SB/BB 에서는 소폭 확장. BB 가 상대 shove 를 받는 경우 call range 는 더 타이트 (77+, AJs+, AQo+)
2. **포지션 분류** (`position.classify_position`) — 2~9명 인원별 테이블, `EP/MP/LP/SB/BB` 버킷 반환. BOT_REFERENCE §4 인코딩.
3. **Raise count 기반 분기**
   - `raise_cnt == 0` (unopened):
     - `BB` 이고 `to_call == 0` → `check`
     - `key ∈ open_range(pos)` → `raise(max(bb * open_size_bb, min_raise))`. `tight` 레짐에선 `3bb` 이상으로 압박.
     - else → `check`(BB) 또는 `fold`
   - `raise_cnt == 1` (single raise 당함):
     - `key ∈ three_bet_range(pos, vs_pos)` → `raise(last_raise_amt * three_bet_mult)`. IP(LP) 는 3×, OOP 는 3.5×.
     - `key ∈ call_range(pos, vs_pos)` 이고 `to_call ≤ preflop_call_cap_bb * BB` → `call`
     - else → `fold`
   - `raise_cnt ≥ 2` (3bet+ 에 직면):
     - `key ∈ four_bet_range()` = `{AA, KK, AKs}` → `raise(last_raise * four_bet_mult)` 또는 allin
     - else → `fold`
4. **amount 규칙 엄수** — 모든 raise 는 `_clamp_raise_amount(target, req) = min(max(target, min_raise), my_stack)` 으로 BOT_REFERENCE §6.2 준수.

레인지 테이블: `preflop_ranges.py`
- `OPEN_EP` (~12%): JJ+, AKs, AQs, AJs, KQs, AKo, AQo, JTs 등 (utg/utg1)
- `OPEN_MP` (~18%): EP ∪ {88, 77, ATs, KJs, QJs, AJo, KQo, 수트 에이스 선별} (mp/mp1/hj)
- `OPEN_LP` (~27%): MP ∪ {66-22, A5s-A2s, 98s~54s, ATo, KJo, QJo, JTo} (co/btn)
- `OPEN_SB`: LP 와 유사
- `THREE_BET_VALUE`: QQ+, AKs, AKo
- `THREE_BET_IP` (추가 블러프): JJ, AQs, KQs
- `FOUR_BET_VALUE`: AA, KK, AKs
- `CALL_VS_OPEN_IP/OOP`: 3bet 안 하지만 call 해볼 만한 중소페어 + suited connector

#### 포스트플롭 — 멀티웨이 + 보드 텍스처 + 레인지 좁히기 (`rule_based._postflop`)

1. **멀티웨이 감지**: `n_opps = active_count(players) - 1`
   - `n_opps ≥ 2` 이면 `equity_mc_multi` 로 교체 (기존 `equity_mc` 는 1:1 전용 유지)
   - raise/bet 임계값에 `multiway_raise_penalty * (n_opps - 1)` 가산 (기본 0.05/상대)
   - MC 샘플 수 동적 증가: `max(cfg.mc_samples, 500 * (n_opps + 1))`
2. **상대 레인지 업데이트** (`opp_range.narrow_by_postflop`)
   - `infer_opp_combos` 로 프리플롭 tier 레인지 → 포스트플롭 액션 기반 추가 필터링
   - flop raise/allin → top pair+ 이상만
   - turn raise/allin → two pair+ 이상
   - strength 판정은 `hand_eval.classify_hand` 재사용
3. **보드 텍스처** (`board.board_texture`) → `BoardTexture{flush_draw, flush_made, straight_draw, straight_made, paired, monotone, wetness 0-3}`
4. **동적 베팅 사이즈** (`board.size_bet`)
   - dry + 강패 (equity ≥ raise_thr): `bet_frac_dry_strong` (기본 0.5)
   - wet + 강패: `bet_frac_wet_strong` (기본 0.75) — drawing hand 거부용 크게
   - dry + value: `bet_frac_dry_value` (기본 0.33)
   - wet + value: `bet_frac_wet_value` (기본 0.6)
   - river 는 fold equity 없으므로 value 배수 `river_value_mult` (기본 1.2)
5. **커밋 판정**: `to_call + pot ≥ my_stack * 0.5` 이고 `M < m_tight` 이면서 `equity ≥ 0.35` 이면 `allin`

### 파라미터 (StrategyConfig 차이)

| 필드 | v0 기본 | v1 기본 | 비고 |
|---|---|---|---|
| `mc_samples` | 2000 | 2000 | (변동 없음) |
| `equity_call_margin` | 0.03 | 0.03 | (변동 없음) |
| `equity_value_bet_threshold` | 0.65 | 0.65 | (변동 없음) |
| `equity_raise_threshold` | 0.80 | 0.80 | (변동 없음) |
| `max_bet_fraction_of_pot` | 0.5 | 0.5 | (변동 없음, 내부 size_bet 이 우선) |
| `postflop_call_cap_fraction` | 1.0 | 1.0 | (변동 없음) |
| `open_size_bb` | — | **2.5** | 신규 — 오픈 사이즈 BB 배수 |
| `three_bet_mult_ip` | — | **3.0** | 신규 — IP 3bet 배수 |
| `three_bet_mult_oop` | — | **3.5** | 신규 — OOP 3bet 배수 |
| `four_bet_mult` | — | **2.3** | 신규 — 4bet 배수 |
| `preflop_call_cap_bb` | — | **8.0** | 신규 — 콜 상한 (BB 배수). `CALL_FLOOR=16` 상수 제거 |
| `m_healthy` | — | **20.0** | 신규 |
| `m_tight` | — | **10.0** | 신규 |
| `m_push_fold` | — | **6.0** | 신규 |
| `m_desperate` | — | **3.0** | 신규 |
| `multiway_raise_penalty` | — | **0.05** | 신규 — 상대 +1명당 임계값 가산 |
| `multiway_min_samples_per_opp` | — | **500** | 신규 |
| `bet_frac_dry_strong` | — | **0.5** | 신규 |
| `bet_frac_wet_strong` | — | **0.75** | 신규 |
| `bet_frac_dry_value` | — | **0.33** | 신규 |
| `bet_frac_wet_value` | — | **0.6** | 신규 |
| `river_value_mult` | — | **1.2** | 신규 |
| `profile_min_hands` | — | **15** | 신규 (Phase F 에서 사용 예정) |
| `profile_vpip_wide` | — | **0.40** | 신규 (Phase F) |
| `profile_vpip_tight` | — | **0.18** | 신규 (Phase F) |

### 측정 (before/after)

v0 로 기록된 `.debug/room_*.jsonl` (5개 룸, 352 decisions) 을 v1 전략으로 **리플레이** 한 결과:

| 지표 | v0 (실제 결과) | v1 (리플레이) |
|---|---|---|
| 프리플롭 `raise`+`allin` 비율 | **0%** | **20.3%** |
| 전체 액션 분포 | fold 58% / check 26% / call 16% / raise 0% / allin 0% | fold 51% / check 24% / call 6% / raise 9% / allin 10% |
| `open_raise` (unopened 케이스) | 0회 (해당 개념 없음) | 26회 / 114회 = **22.8%** |
| 멀티웨이 threshold 가산 건수 | 없음 | 로그에 기록 중 (`multiway_penalty`) |
| 프리미엄 (AA~JJ, AKs/AKo) BTN | call 상한까지만 | `raise`/`3bet` 발생 |
| M<5 숏스택 | 같은 레인지로 call 후 리버 fold | `allin`/`fold` 이분 전환 |

**리플레이 방법**: `.venv/bin/python scripts/ab_compare.py --debug-glob '.debug/room_*.jsonl'` (= `app.analysis.replay.load_debug_cases` + `score_config`).

### 리스크 / 후속

- **분산 증가**: raise 비율 0% → 20% 전환은 큰 승/큰 패 섞여 토너먼트 분산 ↑. 3bet 블러프는 IP only, JJ/AQs/KQs 한정으로 보수적으로 시작.
- **포지션 테이블 불일치 가능성**: BOT_REFERENCE 의 2~9명 포지션 맵이 실서버와 다를 리스크 — 신규 로그에서 `seat` 값 (`mp1`, `utg1` 등) 분포 모니터 필요. `classify_position` 은 테이블 매칭 실패 시 보수적으로 `MP` fallback.
- **push/fold chart 근사**: 정확한 Nash chart 는 스택/ante/ICM 의존 — 현재는 chip-EV 단순화. M<5 에서 너무 aggressive 하면 실전에서 여러 번 수정 필요.
- **멀티웨이 equity 편향**: `equity_mc_multi` 는 상대 combo 가 tier 샘플일 때 서로 상관관계 있는 경우(같은 카드 공유) 약간 과대. 현재 구현은 `dead_cards` 로 내 카드+보드만 제외.
- **amount 규칙 회귀**: 모든 raise 에서 `_clamp_raise_amount` 를 일관되게 적용하지만, `min_raise` 가 `pot`/`to_call` 대비 너무 크면 의도한 사이즈보다 클 수 있음 — 신규 로그 `open_size` / `threebet_size` 로 추적.
- **`Action.meta` 유출**: `Field(exclude=True)` + `client._dispatch` 의 런타임 가드(`"meta" not in action_payload`)로 차단. 회귀 가드 상시 활성.
- **다음 후보 개선** (v2 이후):
  - `opp_profile` 누적 (`.debug/opponent_profiles.json` 은 이미 analysis 가 생성 중) → `opp_range.estimate_tier(profile=...)` 로 개인화
  - turn/river 액션으로 레인지 더 좁히기 (현재는 flop raise 까지만 반영)
  - 베팅 사이즈 폴드 이퀴티 정량화 (상대별 fold-to-cbet 빈도 학습 후)
  - 100 테스트케이스 (`tests/fixtures/decisions/*.json`) 기반 coordinate-descent 튜닝

### 관련 파일

**신규**
- `app/strategy/position.py` — `classify_position`, `active_count`, `is_in_position`
- `app/strategy/tournament.py` — `effective_m`, `m_regime`, `push_fold_decision`
- `app/strategy/preflop_ranges.py` — 레인지 테이블 + `open_range`/`three_bet_range`/`four_bet_range`/`call_range`/`hand_key`
- `app/strategy/board.py` — `BoardTexture`, `board_texture`, `size_bet`

**변경**
- `app/strategy/rule_based.py` — `_preflop_decision` 전면 재작성, `_postflop` 멀티웨이/보드/narrow/committed 통합, `StrategyConfig` 확장. `CALL_FLOOR=16` 상수 제거.
- `app/strategy/equity.py` — `equity_mc_multi(hole, board, n_opps, opp_combos_list, samples, rng)` 추가. 기존 `equity_mc` 유지.
- `app/strategy/opp_range.py` — `all_opp_combos(req)`, `narrow_by_postflop(combos, player, history, board)` 추가. `estimate_tier` 는 다음 버전에서 profile 파라미터 추가 예정.

---

## v0 (baseline, ~2026-04-19) — 룰 기반 엔트리 + 포스트플롭 MC Equity

초기 `BalancedStrategy` — 참고용 baseline. v1 이후 실운영은 v1 부터.

### 프리플롭
- 엔트리: `is_pair OR is_suited OR is_top300` (`hand_ranges.is_top_300`, ~306 combos)
- 진입 후 `to_call == 0` → `check`
- 진입 후 `0 < to_call ≤ max(pot * 2, CALL_FLOOR=16)` → `call`
- 진입 후 `to_call > 상한` → `fold`
- **raise / 3bet / position / M-ratio 전부 없음**

### 포스트플롭 (flop/turn/river 동일 로직)
- `classify_hand(hole + board)` 로 내 메이드핸드 분류
- `infer_opp_combos(req)` 로 **활성 상대 1명** (`primary_threat`) 의 tier 기반 combo 리스트 추정
- `equity_mc(hole, board, 2000, opp_combos)` 로 MC equity
- `pot_odds = to_call / (pot + to_call)` 비교
- 결정:
  - `equity ≥ 0.80` → `raise`(target=pot/2)
  - `equity ≥ 0.65 & to_call == 0` → `bet`(pot/3)
  - `equity ≥ pot_odds + 0.03` → `call`
  - `equity < pot_odds - 0.03` 또는 `to_call > my_stack` → `fold`
  - 그 외 → `to_call == 0 이면 check, 아니면 fold`

### 실측 결과
- 실전 5개 룸(`room_836/837/838/839/842`): **전부 31~48핸드 안에 탈락 (0승 5패)**
- 프리플롭 raise 0%, 멀티웨이 equity 과대, 블라인드 상승에도 동일 CALL_FLOOR(16) 로 숏스택 말라죽음

### 관련 파일 (v0 시점)
- `app/strategy/rule_based.py` — `CALL_FLOOR = 16`, `_preflop_decision`, `BalancedStrategy.decide`
- `app/strategy/equity.py` — `equity_mc`
- `app/strategy/hand_ranges.py` — `is_top_300`
- `app/strategy/opp_range.py` — `estimate_tier`, `primary_threat`, `infer_opp_combos`
- `app/strategy/hand_eval.py` — `classify_hand`, `rank7`

---

## 새 버전 추가 가이드

1. 이 파일 맨 위에 `## vN (YYYY-MM-DD) — 요약` 섹션 추가
2. 동기 / 변경 / 파라미터 / 측정 / 리스크 / 관련 파일 6개 소제목은 유지
3. 이전 버전 섹션은 **삭제하지 말고** 그대로 아래에 둔다 (누적)
4. 측정은 가능하면 `.venv/bin/python scripts/ab_compare.py --debug-glob '.debug/room_*.jsonl' --baseline <prev.json>` 결과로 before/after 비교
5. StrategyConfig 필드 추가/변경이 있으면 파라미터 표에 반영
