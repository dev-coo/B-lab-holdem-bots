# 용어 사전

관련: [LOGIC.md](./LOGIC.md) · [WORKFLOW.md](./WORKFLOW.md)

이 저장소 (코드·문서·로그·대시보드) 에서 자주 나오는 용어를 포커/봇 관점에서 최소한으로 정리.

---

## 1. 판 구성

| 용어 | 의미 |
|---|---|
| **핸드 (hand)** | 게임 한 판. 카드 돌리고 → 베팅 → 승자 결정까지 1 사이클. `hand_number` 로 구분. |
| **홀카드 (hole cards)** | 나한테만 보이는 내 카드 2장. `your_cards` 필드. |
| **커뮤니티 카드 / 보드 (community / board)** | 모두가 공유하는 공개 카드. 최대 5장. `community_cards` 필드. |
| **쇼다운 (showdown)** | 리버까지 온 뒤 살아남은 플레이어들이 홀카드 공개. 승자 결정. `hand_result` 이벤트. |

## 2. 페이즈 (phase)

베팅 라운드의 단계. `action_request.phase` 로 구분.

| 페이즈 | 보드 카드 수 | 설명 |
|---|---|---|
| `preflop` | 0 | 홀카드만 받은 직후, 첫 베팅 라운드 |
| `flop` | 3 | 보드에 3장 공개 |
| `turn` | 4 | 4번째 카드 공개 |
| `river` | 5 | 마지막 카드 공개, 쇼다운 직전 |

## 3. 돈 관련

| 용어 | 의미 |
|---|---|
| **팟 (pot)** | 현재 판에 쌓인 칩 총합. 승자가 가져감. |
| **스택 (stack)** | 내 앞에 남은 칩. `my_stack`. |
| **블라인드 (SB/BB)** | 강제 베팅. Small Blind / Big Blind. `blind=[SB, BB]`. |
| **to_call** | 이 판에 계속 참여하려면 내가 추가로 내야 하는 금액. 0 이면 공짜 체크 가능. |
| **min_raise** | 레이즈 시 최소로 맞춰야 하는 이번 라운드 총 베팅 목표액. |

## 4. 액션

서버에 보낼 수 있는 5 가지. `type=action` 메시지로 전송.

| 액션 | 언제 | amount |
|---|---|---|
| `fold` | 포기 | 불필요 |
| `check` | to_call==0 일 때 패스 | 불필요 |
| `call` | 상대 베팅에 맞춤 | 불필요 (서버 계산) |
| `raise` | 레이즈 / 오픈 벳. `amount` 는 **이번 라운드 총 베팅 목표액** (추가 금액 아님) | 필수 |
| `allin` | 올인 | 불필요 |

## 5. 전략 수학

| 용어 | 공식 / 의미 |
|---|---|
| **equity (승률)** | 지금 내 패가 최종적으로 이길 확률. 0.0 ~ 1.0. 상대 홀카드·미래 보드를 모르므로 **추정값**. |
| **pot odds (팟 오즈)** | `to_call / (pot + to_call)`. "장기적으로 콜이 수익이 되려면 내 승률이 최소 얼마여야 하는가". |
| **EV (expected value, 기댓값)** | `승률 × 얻을 돈 − 패배확률 × 잃을 돈`. 양수면 +EV (장기적으로 이득), 음수면 −EV. |
| **+EV 콜의 조건** | `equity > pot_odds` |
| **마진 (call margin)** | equity 추정값은 노이즈가 있으므로 `equity > pot_odds + 0.03` 정도만 콜. 현재 `EQUITY_CALL_MARGIN=0.03`. |

## 6. 추정 기법

| 용어 | 의미 |
|---|---|
| **Monte Carlo (MC)** | 랜덤 시나리오를 많이 돌려 확률을 근사. 정확 계산이 비현실적일 때 씀. |
| **MC 샘플 수** | 몇 번 돌릴지. 현재 `MC_SAMPLES=2000` → 플롭당 약 ±1% 오차. |
| **레인지 (range)** | 어떤 플레이어가 들고 있을 수 있는 홀카드 **집합**. 예: "프리플롭 레이즈 → 상위 20% 레인지". 봇은 `opp_range.estimate_tier` 로 상대 프리플롭 액션 + 누적 profile(VPIP) 기반 tier (top10/20/40/any) 를 추정해 `tier_combos` 로 샘플링. `narrow_by_postflop` 로 포스트플롭 aggression 반영 추가 축소. |
| **made-hand** | 이미 완성된 패. 페어/투페어/트립스/스트레이트/플러시… |
| **드로우 (draw)** | 아직 미완성이지만 다음 카드로 완성될 수 있는 패. 플러시 드로우, 스트레이트 드로우 등. |

## 7. 포지션 & 스택 뎁스

| 용어 | 의미 |
|---|---|
| **포지션 (position)** | 딜러 기준 자리. `btn` / `sb` / `bb` / `utg` / `mp` / `hj` / `co` 등. 포스트플롭에서 뒤 포지션이 유리. |
| **M ratio** | `stack / (SB + BB)`. 토너먼트에서 스택 여유 지표. 높으면 여유, 낮으면 몰림. |

## 8. 표기법

| 용어 | 의미 |
|---|---|
| **카드 표기** | `랭크+슈트` 2글자. 랭크: `23456789TJQKA`, 슈트: `s/h/d/c`. 예: `Ah`=A♥, `Tc`=10♣. |
| **핸드 키** | 슈트 무시하고 랭크 + suited/offsuit. 예: `AKs`, `AKo`, `TT`. 169 가지 클래스. |
| **top300** | Equity 상위 클래스 묶음 ~306 combos. 코드: `holdem_main_bot/hand_ranges.py`. **v1 이전 레거시** — 현재 봇은 `preflop_ranges.py` 의 position-별 레인지(`OPEN_EP/MP/LP/SB`, `THREE_BET_*`, `FOUR_BET_VALUE`, `CALL_VS_OPEN_*`) 사용. |

## 9. 봇 내부 용어 (코드/로그)

`.debug/room_*.jsonl` outbound 레코드의 `meta` 필드, 대시보드 오버레이, 리포트에서 자주 등장.

| 용어 | 의미 |
|---|---|
| **`Action.meta`** | 봇이 내보내는 `Action` 모델의 `exclude=True` 필드. 결정 근거 dict (equity, pot_odds, reason, pos 등). 네트워크로는 나가지 않고 `DebugDumper.outbound(meta=...)` 가 `.debug/room_*.jsonl` 에만 병합 기록. |
| **`table_mode`** | 이번 결정의 실행 모드. `exploit` (스크립트 봇 상대 공격적) / `balanced` (강한 봇 상대 보수적). `cfg.mode="auto"` 면 `resolve_table_mode` 가 활성 상대 분류로 결정. v3 기준 두 경로 동일(기록만), v3.x 에서 실제 분기 예정. |
| **`opp_class` / `OpponentClass`** | 개별 상대 봇 분류. `unknown` / `script` / `adaptive`. 기준은 `opponent_class.classify_opponent`: VPIP-PFR 차이 · 3bet 빈도 · hands_seen. |
| **`profile` / `OpponentProfile`** | `.debug/opponent_profiles.json` 에 누적된 상대 통계 dict. `hands_seen, vpip_n, pfr_n, threebet_n, showdown_n, showdown_won_n, made_hand_histogram`. `SummaryWriter.write` 가 game_end 시 병합. |
| **`regime`** | M-ratio 구간 분류. `healthy` (≥20) / `tight` (≥12) / `push_fold` (≥7) / `desperate` (<7). `tournament.m_regime` 산출. |
| **`raise_thr` / `value_thr`** | 포스트플롭에서 현재 결정에 쓰인 raise/value bet 기준 equity. multiway 면 base + penalty. |
| **`pot_odds`** | `to_call / (pot + to_call)`. 장기 +EV call 조건 = `equity ≥ pot_odds + margin`. |
| **`equity` / `equity_mc` / `equity_mc_multi`** | Monte Carlo 승률. 1:1 은 `equity_mc`, 멀티웨이는 `equity_mc_multi` (상대별 `opp_combos_list`). 타이는 1/k 로 분배. |
| **`narrow_by_postflop`** | 상대의 포스트플롭 aggression (flop raise/allin 등) 으로 combos 리스트 추가 필터링. |
| **`tier_combos`** | tier (top10/20/40/any) 에 속한 169 핸드 클래스를 실제 `(card1, card2)` combos 로 확장 (내 홀·보드 제외). |
| **`draw_live`** | 내 홀+보드로 감지한 live draw 여부 (flush_draw or OESD or gutshot, made 아님). `draw_detect.DrawInfo.is_live_draw`. |
| **`flush_draw`** | 홀 suited + hole+board 에서 내 슈트 4장 = 9 outs. v3 규칙: raise 금지, to_call 싸면 call. |
| **`OESD`** | Open-ended Straight Draw. 4연속 랭크 = 8 outs. |
| **`gutshot`** | Inside straight draw. 1칸 틈 = 4 outs. |
| **`outs`** | 다음 카드로 메이드될 수 있는 카드 개수. flush_draw=9, OESD=8, gutshot=4. |
| **`made_hand_category`** | `hand_eval.classify_hand` 결과의 `category_rank`. 1=high_card, 2=one_pair, 3=two_pair, 4=trips, 5=straight, 6=flush, 7=full_house, 8=quads, 9=straight_flush. |
| **`committed`** | `to_call + pot ≥ my_stack × 0.5` 상태. M<10 이면 equity≥0.35 로 allin 발동. |
| **`wetness`** | `board_texture` 가 산출하는 보드 drawy 지수 (0=dry ~ 3=very wet). `size_bet` 이 이 값으로 사이즈 결정. |
| **`hand_key`** | 슈트 무시한 핸드 클래스 문자열. `AA`, `AKs`, `AKo`. 레인지 매칭 키. |
| **`run_id`** | `DebugDumper.begin_run` 이 할당하는 UUID. 한 번의 WS 연결 세션 단위. 재접속하면 새 run_id. 같은 룸 파일에 여러 run_id 가 축적될 수 있음. |
| **`reason`** | meta 에 기록되는 결정 사유 문자열. 예: `open_raise`, `positive_ev_call`, `draw_check_free`, `push_fold_desperate`, `committed_shove`. 전체 목록은 [LOGIC.md §5](./LOGIC.md). |

---

## 10. 이 서버의 비표준 룰

일반 텍사스 홀덤과 다른 점. `hand_eval.py` 는 이 룰에 맞춰 구현됨.

| 룰 | 내용 |
|---|---|
| **백스트레이트(A-2-3-4-5) 불인정** | A 는 **오직 하이(14)** 로만 취급. `A-2-3-4-5` 는 스트레이트 아닌 **A-하이 하이카드**. 같은 무늬면 플러시(A-하이). 스트레이트 플러시도 아님. |
| 가장 낮은 스트레이트 | `2-3-4-5-6` |
| 가장 높은 스트레이트 | `T-J-Q-K-A` (브로드웨이) |

---

## 자주 같이 나오는 약어

- **BB** = Big Blind (금액) 또는 big blind 자리
- **SB** = Small Blind
- **UTG** = Under The Gun (프리플롭 첫 액션 자리)
- **CO** = Cut-off (딜러 직전)
- **BTN** = Button (딜러)
- **MC** = Monte Carlo
- **EV** = Expected Value
- **+EV / −EV** = 장기적으로 이득 / 손해인 결정
