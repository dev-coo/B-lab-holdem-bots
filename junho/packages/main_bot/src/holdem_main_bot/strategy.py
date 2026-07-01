"""BalancedStrategy — 포지션/M-ratio/레인지/멀티웨이/보드 텍스처 인지.

Preflop:
- M < push_fold 구간은 push_fold_decision 위임 (shove-or-fold).
- 포지션별 open raise (EP/MP/LP/SB) + 3bet + 4bet + cold-call.
- amount 는 BOT_REFERENCE §6.2 규칙 — "이번 라운드 총 베팅액".

Postflop:
- 멀티웨이(active 상대 2+) 면 equity_mc_multi 사용 + multiway_raise_penalty 가산.
- 보드 텍스처 → size_bet 로 동적 사이징.
- 상대 레인지는 infer_opp_combos 후 narrow_by_postflop 로 좁힘.
- committed(to_call+pot >= my_stack*0.5) & m<10 & equity>=0.35 → allin.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from holdem_core.core.logging import get_logger, register_decision_logger
from holdem_core.hand_eval import classify_hand
from holdem_core.models.actions import Action
from holdem_core.models.events import ActionRequest

from holdem_main_bot.bluff_model import (
    OppBluffEstimate,
    estimate_opp_bluff_prob,
    observe_hand_result,
)
from holdem_main_bot.bluff_prior import BluffPriorStore
from holdem_main_bot.board import BoardTexture, board_texture, size_bet
from holdem_main_bot.draw_detect import detect_draws
from holdem_core.equity import equity_mc, equity_mc_multi
from holdem_main_bot.ev_engine import action_ev, estimate_fold_equity
from holdem_main_bot.opponent_class import (
    ClassificationConfig,
    OpponentClass,
    classify_all,
    resolve_table_mode,
)
from holdem_main_bot.opp_range import (
    all_opp_combos,
    infer_opp_combos,
    narrow_by_postflop,
)
from holdem_main_bot.position import Position, active_count, classify_position
from holdem_main_bot.preflop_ranges import (
    call_range,
    four_bet_range,
    hand_key,
    hu_call_range,
    hu_open_range,
    hu_three_bet_range,
    iso_limp_range,
    open_range,
    three_bet_range,
)
from holdem_main_bot.range_advantage import (
    hero_range_combos,
    my_preflop_actions,
    range_advantage,
)
from holdem_main_bot.spr_tree import adjust_for_bucket, spr_bucket, spr_value
from holdem_main_bot.tournament import (
    effective_m,
    m_regime,
    push_fold_decision,
)

register_decision_logger(__name__)
logger = get_logger(__name__)


def _default_open_size_by_pos() -> dict[str, float]:
    # v2: position-aware squeeze. EP 는 4-way 로 빠지지 않게 크게, LP 는 스틸 타이트.
    return {"EP": 3.5, "MP": 3.0, "LP": 2.5, "SB": 2.5, "BB": 2.0}


@dataclass
class StrategyConfig:
    # === 기존 ===
    mc_samples: int = 2000
    equity_call_margin: float = 0.03  # v4: 0.05 → 0.03 (counterfactual_wrong_fold 4.1% 완화)
    equity_value_bet_threshold: float = 0.62  # v4: 0.65 → 0.62 (value 구간 확대)
    equity_raise_threshold: float = 0.80
    max_bet_fraction_of_pot: float = 0.5
    postflop_call_cap_fraction: float = 1.0

    # === D.3 프리플롭 사이징 ===
    open_size_bb: float = 2.5  # deprecated fallback
    open_size_bb_by_pos: dict[str, float] = field(default_factory=_default_open_size_by_pos)
    three_bet_mult_ip: float = 3.0
    three_bet_mult_oop: float = 3.5
    four_bet_mult: float = 2.3
    preflop_call_cap_bb: float = 10.0  # v2: 8.0 → 10.0 (BB defense 확장)

    # === D.2 M-ratio ===
    m_healthy: float = 20.0
    m_tight: float = 12.0  # v2: 10.0 → 12.0 (tight regime 더 자주 발동)
    m_push_fold: float = 6.0  # v5.2: 7.0 → 6.0 (M[6-7]서 shove→정상결정; desperate 탈락 감소)
    m_desperate: float = 3.0

    # === v5.2 Preflop equity gate (push/call shove 전 검증) =====================
    # 탈락의 52.2% 가 allin_call_dominated → hand_key match 만으로 shove/call 하면
    # 상대 range 에 behind 되는 경우가 많음. shove/call 결정 전에 상대 추정 range
    # 대비 equity_mc 로 2차 검증해서 dominated spot 에서 fold.
    enable_preflop_equity_gate: bool = True
    preflop_equity_gate_samples: int = 400  # MC 샘플. 400 이면 ~30ms.
    preflop_shove_equity_min: float = 0.36  # first-in shove / raise 후 shove 최소 equity
    preflop_call_shove_equity_min: float = 0.45  # 상대 shove 에 call 할 때 최소 equity

    # === v5.3 Heads-up (2-handed) 전용 설정 =====================================
    # 실측 55게임 2등 탈락 25건(45%) + HU 구간 520핸드 fold 65.4% → blind-bleed.
    # HU 에서 일반 6-max 레인지(OPEN_LP 40%) 가 너무 좁아서 SB blind 헌납 반복.
    # HU 전용 레인지(HU_OPEN_BTN 87%, HU_CALL_BB 38%, HU_3BET_BB 8%) + 작은 open
    # size + tight regime 완화로 탈출.
    enable_hu_mode: bool = True
    hu_open_size_bb: float = 2.0  # HU BTN min-raise 사이즈 (기존 LP 2.5bb → 2.0bb)
    # v5.3.1: m_tight_bonus 3.0 → 5.0 (HU 에선 M=7 이상이면 정상 play 로 진입)
    hu_m_tight_bonus: float = 5.0  # HU 에선 m_tight 임계값을 이만큼 내림 (12→7)
    hu_call_shove_equity_min: float = 0.40  # HU 상대 shove range 가 넓음 (0.45 → 0.40)

    # === v5.3.1 HU M-threshold 하향 (push_fold 진입 지연) =======================
    # 실측: v5.3 반영된 HU 결정 861건 중 83.5% 가 push_fold/desperate 경로로 빠져서
    # HU 레인지(hu_open_raise/hu_call) 는 겨우 6.5% 만 작동. HU 에선 blind=SB+BB
    # 총 3unit 이지만 정상 play 로도 pot 가 작아 M 이 작아도 실제 위험은 낮음.
    # push_fold/desperate 구간을 HU 에선 더 얇은 스택에서만 발동하도록 bonus 하향.
    hu_m_push_fold_bonus: float = 2.0  # m_push_fold 6.0 - 2.0 = 4.0
    hu_m_desperate_bonus: float = 1.0  # m_desperate 3.0 - 1.0 = 2.0
    hu_m_healthy_bonus: float = 8.0  # m_healthy 20 - 8 = 12 (HU M≥12 면 healthy)

    # === v5.4 P1-5: vs wide-3bettor (LAG) call defense 보강 ===================
    # 17K핸드 분석에서 너구리쿤 (3bet rate 17%) 의 3bet 71% 가 fold-win 으로 끝남.
    # 우리 봇이 fold_vs_3bet 1886회 — over-fold. 기본 call_vs_3bet 은 QQ/JJ/AKo
    # 만 허용. 누적 stat 으로 wide-3bettor 식별되면 추가 hand 도 call.
    vs_wide_3bettor_threebet_rate: float = 0.10  # threebet_n/hands_seen 이 이 이상이면 wide
    vs_wide_3bettor_min_hands: int = 100  # 누적 시그널 신뢰 임계
    # call 추가 허용 (premium 외): 미디엄 페어 + 강한 broadway. wide 3bettor 만 적용.
    vs_wide_3bet_extra_calls: frozenset[str] = frozenset(
        {"TT", "99", "AQs", "AQo", "AKs", "KQs", "AJs"}
    )
    # === v5.5.1: 추가 발견 두 가지 ============================================
    # (A) volume-aggression 분석: 너구리쿤 open 후 3bet 받으면 fold 1.1%, 4bet 75%.
    # → 너구리쿤급 wide-3bettor 가 open 한 spot 에서 우리 3bet bluff 거의 무의미.
    # threebet_set ∩ premium 만 남기고 나머지는 call/fold 로 다운그레이드.
    vs_wide_4bettor_disable_3bet_bluff: bool = True
    # 우리 3bet 유지하는 strict value (wide-4bettor 상대로도 3bet 가치 있음)
    vs_wide_4bettor_threebet_value: frozenset[str] = frozenset(
        {"AA", "KK", "QQ", "JJ", "AKs", "AKo", "AQs"}
    )
    # (B) bluff-showdown 분석: 너구리쿤 turn/river all-in 의 fold-equity 11% 미만,
    # sd_win 70%+ → call threshold 보수화. top10/top20 상대 + turn/river 일 때
    # commit_floor 추가 +0.05.
    commit_floor_turn_river_bonus: float = 0.05

    # === v5.5.2: headup-loss 분석 — preflop blind-bleed (F1+F5) ================
    # 너구리쿤 winner 핸드의 우리 결정 42K 중 fold 60.2%, preflop fold 77.7%.
    # 너구리쿤 raise→우리 반응에서 small/medium 사이즈 fold% 70-76%, fold 후
    # 너구리쿤 winner 비율 58-74% — cheap mini-raise 만으로 우리 blind 회수 중.
    # wide-opener 가 mini-raise (≤2.5bb) 한 spot 에서 BB defend 보강.
    vs_wide_opener_bb_defend: bool = True
    vs_wide_opener_min_size_bb: float = 2.5  # to_call 이 이 이하 (BB 단위) 면 cheap
    # cold_call set 에 추가될 connectors / suited gappers (BB 만 적용).
    # 너구리쿤 wide_open 79% vs 표준 BB call 36% 의 갭을 메우는 sticky range.
    vs_wide_opener_bb_extra_calls: frozenset[str] = frozenset(
        {
            "T9s", "98s", "87s", "76s", "65s", "54s",  # suited connectors
            "J9s", "T8s", "97s", "86s", "75s",  # one-gappers
            "K9s", "Q9s", "J8s",  # blocker suited
            "A9s", "A8s", "A7s",  # suited Ax
            "55", "44", "33", "22",  # small pairs (set mining)
        }
    )

    # === D.4 멀티웨이 ===
    multiway_raise_penalty: float = 0.10  # v4: 0.08 → 0.10 (aggressive_bet_into_better 1.2% 완화)
    multiway_min_samples_per_opp: int = 500
    equity_call_margin_multiway: float = 0.07  # v4: 0.08 → 0.07 (멀티웨이 call 약간 확대)
    equity_raise_threshold_multiway_base: float = 0.87  # v4: 0.85 → 0.87 (3-way base 상향)

    # === E.1/E.2 보드/사이징 ===
    bet_frac_dry_strong: float = 0.5
    bet_frac_wet_strong: float = 0.75
    bet_frac_dry_value: float = 0.33
    bet_frac_wet_value: float = 0.6
    river_value_mult: float = 1.2

    # === v2 멀티웨이 bet 사이즈 (value 축소) ===
    bet_frac_dry_strong_multiway: float = 0.33
    bet_frac_wet_strong_multiway: float = 0.5
    bet_frac_dry_value_multiway: float = 0.25
    bet_frac_wet_value_multiway: float = 0.33

    # === F.3 상대 프로필 ===
    # v5.4: 15 → 200. 실데이터에서 ≤200 hands 대상은 VPIP 표준편차 ~7%p 라
    # tier 보정이 잡음에 휘둘림. 실측 누적: Wooz 9803/쪼랩익명이4 21216/Hugo 10351
    # /고니 7700/편경장 5489 — 주요 상대는 모두 통과. 90~250 짜리 신규 상대는
    # base tier (action 만으로) 분류로 폴백.
    profile_min_hands: int = 200
    profile_vpip_wide: float = 0.30  # v4: 0.40 → 0.30 (실전 상대 max VPIP 25% — 0.40 과도)
    profile_vpip_tight: float = 0.18
    profile_path: str = ".debug/opponent_profiles.json"
    # v5.4: 상대 W$SD 가 높으면 (nit-y SD) 그 상대의 aggression 에 더 보수적.
    # 편경장 W$SD 67.9% / 고니 69.2% — 편경장은 nit (VPIP 14%) → 진짜 강할 때만 SD,
    # 고니는 LAG (VPIP 53%) → 강한 핸드까지 끌고가는 폭이 다름. wssd_pct 만으로는
    # 부족하지만 nit 식별에는 유효. confidence 는 showdown_n 기반.
    wssd_pct_high: float = 0.62
    wssd_aggro_margin_bonus: float = 0.02
    wssd_min_showdowns: int = 50  # showdown_n 이 이 미만이면 보정 안 함

    # === v3 드로우(flush/straight) 보조 규칙 ===
    # 홀카드 suited 로 플롭에 내 슈트 2+ 면 플러시 드로우. 저렴한 call 허용, raise 금지.
    draw_call_pot_ratio_max: float = 0.35  # to_call / (pot+to_call) 이 이 비율 이하면 드로우로 call
    draw_call_stack_ratio_max: float = 0.15  # to_call / my_stack 이 이 비율 이하면 허용
    draw_no_aggression: bool = True  # 드로우만 이유면 raise/오픈베팅 금지

    # === v3 듀얼 모드 뼈대 ===
    # "auto" — 상대 분류로 자동 선택 (당분간 exploit 유지, balanced 는 v3.x 에서 활성)
    # "exploit" — 현 v2 로직 (script/약한 봇 상대 공격적)
    # "balanced" — GTO-lean + randomization (강한 봇 상대, 미구현/뼈대만)
    mode: str = "auto"

    # === v4 top10 상대 보수 편향 ===
    # loss-patterns.md §G: 봇 vs top10 tier 상대 승률 51.9% (겨우 break-even).
    # 주요 위협이 top10 일 때 raise/call 임계값을 약간 올려서 aggressive_bet_into_better 방지.
    top10_raise_thr_bonus: float = 0.03  # opp_tier == "top10" 이면 raise_thr += 0.03
    top10_call_margin_bonus: float = 0.01  # opp_tier == "top10" 이면 call margin += 0.01

    # === v4 River call 완화 ===
    # pattern-hunter 권고: river + pot_odds >= 0.25 + to_call > 0 에서
    # counterfactual_wrong_fold 발생 빈도 높음 → call margin 추가 완화로 회수.
    river_call_margin_discount: float = (
        0.01  # phase==river AND pot_odds>=river_call_pot_odds_min 이면 margin -= 0.01
    )
    river_call_pot_odds_min: float = 0.25

    # === v5 §A: fold_equity + EV(action) argmax ==================================
    # enable_ev_engine 이 True 면 postflop step5 가 EV argmax 로 동작. 단 기존
    # threshold 는 safety floor 로 유지 (equity < equity_raise_threshold 인 spot
    # 에서는 safety 가 raise 를 걸러 downgrade). False 면 v4 경로.
    enable_ev_engine: bool = True
    # EV choice 와 threshold choice 가 다르면 meta 에 'ev_overrode' = True 기록.
    ev_fe_top10_cap: float = 0.45
    ev_fe_default_cap: float = 0.65
    # EV argmax 가 raise 를 선택했을 때, equity 가 이 값보다 낮으면 safety 로
    # call/check 로 downgrade (순수 bluff 방지).
    ev_raise_equity_floor: float = 0.35
    # v5.4: opp_tier 별 conditional floor — strong opp 상대로는 더 높은 commit 마지노선.
    # 너구리쿤 분석에서 우리 봇 8건 dominated 탈락이 모두 equity 0.36-0.40 commit
    # 후 발생. top10/top20 LAG 상대일 때 0.35 floor 가 너무 관대.
    ev_raise_equity_floor_top10: float = 0.45
    ev_raise_equity_floor_top20: float = 0.40
    # short-stack committed_shove 룰 (m<10 + committed) 의 equity 임계 — 같은 spot.
    committed_shove_equity_floor: float = 0.35
    committed_shove_equity_floor_top10: float = 0.45
    committed_shove_equity_floor_top20: float = 0.40
    # EV 가 call/raise 를 골랐는데 pot_odds 가 극단적으로 나쁘면(>0.6) 강제
    # fold — stack 을 레인지 완전 역전 spot 에서 보호.
    ev_extreme_pot_odds_fold: float = 0.6

    # === v5 §B: SPR-indexed decision tree =======================================
    enable_spr_tree: bool = True
    spr_low_max: float = 3.0  # spr <= 3 → low bucket (commit)
    spr_high_min: float = 10.0  # spr > 10 → high bucket (pot control)
    # bucket 별 보정. low 면 raise_thr 를 낮추고 / bet 키움, high 면 반대.
    spr_raise_thr_low: float = 0.05
    spr_raise_thr_high: float = 0.05
    spr_call_margin_low: float = 0.02
    spr_call_margin_high: float = 0.02
    spr_draw_pot_low: float = 0.05  # low 에서 더 싸게 draw
    spr_draw_pot_high: float = 0.05  # high 에서 draw pot ratio 완화 축소
    spr_bet_frac_low: float = 1.2  # low 에서 bet size × 1.2 (commit)
    spr_bet_frac_high: float = 0.8  # high 에서 × 0.8 (pot control)

    # === v5 §C: range_advantage board-aware scaling =============================
    enable_range_advantage: bool = True
    range_advantage_samples: int = 400  # MC 샘플. 비용 작게.
    ra_high_threshold: float = 0.60  # RA > 0.60 → raise_thr 내림
    ra_low_threshold: float = 0.40  # RA < 0.40 → raise_thr 올림
    ra_raise_thr_delta: float = 0.04

    # === v5 §J: limp isolation =================================================
    enable_iso_limp: bool = True
    iso_limp_size_bb: float = 3.5  # 림프 상대에게 iso-raise (3.5bb)

    # === v5.1 뻥카 감지 Beta prior =============================================
    # BluffPriorStore 기반 (player × street × sizing × action_type) posterior 로
    # 상대 aggressive action 의 뻥카 확률 추정. enable_bluff_model=False 면 비활성.
    enable_bluff_model: bool = True
    bluff_prior_path: str = ".debug/bluff_prior.json"
    # posterior 가중치 (min_confidence 이상일 때만 조정 적용)
    # v5.2: 0.10 → 0.05 (포스트플롭 샘플이 전체의 10.5% 뿐이라 conf 쌓기 어려움)
    # v5.4: 0.05 → 0.12. 실측 .debug/main/bluff_prior.json 784 버킷 중 n=0.2 짜리
    # 잡음 버킷이 conf=0.01 로 통과해 결정 흔드는 사고 차단. 0.12 면 n≈2.7 이상
    # (소프트 14회 ~ 하드 3회) 이라야 firing — strong signal 만.
    bluff_min_confidence: float = 0.12
    # p_bluff 가 이 값 이상이면 "강한 뻥카 시그널" — call margin 완화
    # v5.2: 0.55 → 0.50 (middle 영역 넓어서 시그널 감지 확대)
    bluff_high_threshold: float = 0.50
    # p_bluff 가 이 값 이하면 "강한 value 시그널" — call margin 엄격
    bluff_low_threshold: float = 0.25
    # margin 최대 조정폭 (confidence × delta 로 스케일)
    bluff_margin_delta: float = 0.04
    # 상대가 뻥카 성향 높으면 fold_equity 를 낮춤 (내가 raise 해도 잘 안 죽음)
    bluff_fe_delta: float = 0.10
    # v5.4 P1-3: river 는 value-heavy 라 bluff_low 시그널 추가 부스트
    # (.debug/main 분석 — river/medium/bet posterior p_bluff=0.23, conf 0.99
    # 인 너구리쿤 같은 상대 spot 에서 hero-fold 더 강하게).
    bluff_river_value_boost: float = 1.5
    # v5.4 P1-4: flop/turn small raise 의 bluff_priors 가 ~0.45 (너구리쿤 데이터)
    # — bluff_high_threshold 0.50 미달이라 미발동. mid 영역도 절반 효과로 잡는다.
    bluff_mid_threshold: float = 0.40
    bluff_mid_scale: float = 0.5
    # 핸드 종료 시 equity MC 샘플 수 (posterior 갱신 비용)
    bluff_observe_equity_samples: int = 200
    # save 주기 (매 N 핸드마다 디스크 flush)
    bluff_save_interval: int = 20

    # === SQLite 마이그레이션 ===
    # `{debug_dir}/holdem.db` 가 있으면 opponent profiles / bluff prior 를 DB 에서
    # 우선 로드. 없으면 기존 JSON 경로 (profile_path / bluff_prior_path) 폴백.
    # None 이면 JSON 만 사용. 봇 __main__ 에서 settings.DEBUG_DIR 로 주입.
    debug_dir: str | None = None


# ─── 공통 헬퍼 ───────────────────────────────────────────────────────────────


def _clamp_raise_amount(target: int, req: ActionRequest) -> int:
    """raise amount clamp: min_raise 보다 작으면 서버가 폴드 처리함. 스택 초과면 allin."""
    amount = max(int(target), int(req.min_raise))
    amount = min(amount, int(req.my_stack))
    return amount


def _count_preflop_raises(history: list[Any]) -> int:
    cnt = 0
    for a in history:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("phase") == "preflop" and d.get("action") in ("raise", "allin"):
            cnt += 1
    return cnt


def _last_preflop_raiser_seat(history: list[Any], players: list[Any]) -> str | None:
    name: str | None = None
    for a in history:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("phase") != "preflop":
            continue
        if d.get("action") in ("raise", "allin"):
            n = d.get("player")
            if isinstance(n, str):
                name = n
    if not name:
        return None
    for p in players:
        pd = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if pd.get("name") == name:
            pos = pd.get("position")
            if isinstance(pos, str):
                return pos
    return None


def _last_preflop_raise_amount(history: list[Any]) -> int:
    """가장 최근 프리플롭 raise/allin 의 amount (이번 라운드 총 베팅)."""
    amt = 0
    for a in history:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("phase") != "preflop":
            continue
        if d.get("action") in ("raise", "allin"):
            v = d.get("amount", 0)
            if isinstance(v, (int, float)):
                amt = max(amt, int(v))
    return amt


def _count_preflop_calls(history: list[Any]) -> int:
    cnt = 0
    for a in history:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("phase") == "preflop" and d.get("action") == "call":
            cnt += 1
    return cnt


def _my_player_name(players: list[Any], my_seat: str) -> str | None:
    """req.seat 에 해당하는 player.name 반환. history 와 매칭하려면 이름이 필요."""
    for p in players:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if d.get("position") == my_seat:
            name = d.get("name")
            return name if isinstance(name, str) else None
    return None


def _active_nonfolded_opps(players: list[Any], my_seat: str) -> int:
    """내 상대 중 폴드/탈락 안 한 사람 수(현재 라운드에서 여전히 플레이 중)."""
    n = 0
    for p in players:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if d.get("position") == my_seat:
            continue
        if d.get("status") in ("folded", "eliminated"):
            continue
        n += 1
    return n


# ─── Preflop ─────────────────────────────────────────────────────────────────


def _preflop_decision(
    req: ActionRequest,
    cfg: StrategyConfig,
    profiles: dict | None = None,
) -> tuple[Action, dict[str, object]]:
    room_id = req.room_id
    c1, c2 = req.your_cards[0], req.your_cards[1]
    key = hand_key(c1, c2)
    pos: Position = classify_position(req.seat, req.players)
    m = effective_m(req)
    # v5.3: HU(2-handed) 모드 — regime / range / size 모두 전용.
    # v5.3.1: m_push_fold/m_desperate 도 하향. 실측 HU 83.5% 가 push_fold 경로로
    # 빠져서 HU 레인지가 안 먹히던 문제.
    n_active = active_count(req.players)
    is_hu = cfg.enable_hu_mode and n_active == 2
    if is_hu:
        from dataclasses import replace as _dc_replace

        hu_push_fold = max(1.0, cfg.m_push_fold - cfg.hu_m_push_fold_bonus)  # 6.0 → 4.0
        hu_desperate = max(0.5, cfg.m_desperate - cfg.hu_m_desperate_bonus)  # 3.0 → 2.0
        hu_tight = max(hu_push_fold, cfg.m_tight - cfg.hu_m_tight_bonus)  # 12 → 7
        hu_healthy = max(hu_tight, cfg.m_healthy - cfg.hu_m_healthy_bonus)  # 20 → 12
        hu_cfg = _dc_replace(
            cfg,
            m_healthy=hu_healthy,
            m_tight=hu_tight,
            m_push_fold=hu_push_fold,
            m_desperate=hu_desperate,
        )
        regime = m_regime(m, hu_cfg)
        # push_fold_decision 도 이 hu_cfg 를 받도록 아래로 전달용으로 교체.
        cfg_for_push = hu_cfg
    else:
        regime = m_regime(m, cfg)
        cfg_for_push = cfg
    bb = req.blind[1] if len(req.blind) >= 2 else 2
    history = req.action_history
    raise_cnt = _count_preflop_raises(history)
    last_raiser_seat = _last_preflop_raiser_seat(history, req.players)
    last_raise_amt = _last_preflop_raise_amount(history)

    flags: dict[str, object] = {
        "pos": pos,
        "m_ratio": round(m, 2),
        "regime": regime,
        "hand_key": key,
        "facing_raise_cnt": raise_cnt,
        "active_n": n_active,
        "is_hu": is_hu,
    }

    # 1) M-ratio 기반 push_fold 위임.
    pf = push_fold_decision(req, pos, key, cfg_for_push, profiles=profiles)
    if pf is not None:
        flags["reason"] = f"push_fold_{regime}"
        return pf, flags

    # 2) 포지션별 오픈/3bet/4bet/폴드.
    is_pair = c1[0] == c2[0]
    is_suited = c1[1] == c2[1]
    flags["is_pair"] = is_pair
    flags["is_suited"] = is_suited

    if raise_cnt == 0:
        # v5 §J: limp isolation. raise 없이 call(림프) 만 있었고 내가 LP 면 iso-raise.
        call_cnt = _count_preflop_calls(history)
        flags["facing_limp_cnt"] = call_cnt
        if (
            cfg.enable_iso_limp
            and call_cnt >= 1
            and pos == "LP"
            and req.to_call > 0
            and key in iso_limp_range()
        ):
            size_bb = cfg.iso_limp_size_bb
            # 림프 상대 1명당 +1bb 씩 압박. 다수 림프면 iso 커짐.
            target_bb = size_bb + max(0, call_cnt - 1) * 1.0
            target = max(int(bb * target_bb), req.min_raise)
            amount = _clamp_raise_amount(target, req)
            flags["reason"] = "iso_limp_raise"
            flags["iso_size"] = amount
            flags["iso_limpers"] = call_cnt
            return Action(room_id=room_id, action="raise", amount=amount), flags
        # unopened — BB 에서는 check 옵션, 그 외는 open or fold.
        if pos == "BB" and req.to_call == 0:
            flags["reason"] = "bb_check_unopened"
            return Action(room_id=room_id, action="check"), flags
        # SB 완강 림프 금지 — raise or fold.
        # v5.3: HU 면 HU_OPEN_BTN (~87%) + hu_open_size_bb (2.0bb 기본).
        open_set = hu_open_range() if (is_hu and pos == "LP") else open_range(pos)
        if key in open_set:
            if is_hu and pos == "LP":
                size_bb = cfg.hu_open_size_bb
            else:
                # v2: position-aware open size. EP 는 3.5bb, LP 는 2.5bb 등.
                size_bb = cfg.open_size_bb_by_pos.get(pos, cfg.open_size_bb)
            target = max(int(bb * size_bb), req.min_raise)
            if regime == "tight":
                # tight 구간은 약간 더 큰 오픈 (+0.5bb) 으로 압박.
                target = max(target, int(bb * (size_bb + 0.5)))
            amount = _clamp_raise_amount(target, req)
            flags["reason"] = "hu_open_raise" if (is_hu and pos == "LP") else "open_raise"
            flags["open_size"] = amount
            flags["open_size_bb"] = size_bb
            return Action(room_id=room_id, action="raise", amount=amount), flags
        # fold 혹은 check(BB)
        if req.to_call == 0:
            flags["reason"] = "unopened_check"
            return Action(room_id=room_id, action="check"), flags
        flags["reason"] = "unopened_fold"
        return Action(room_id=room_id, action="fold"), flags

    if raise_cnt == 1:
        vs_pos: Position = (
            classify_position(last_raiser_seat, req.players)
            if last_raiser_seat is not None
            else "MP"
        )
        flags["vs_pos"] = vs_pos
        # v5.3: HU BB 에서 상대(BTN=LP) open 에 대해 전용 defend 범위.
        hu_bb_defend = is_hu and pos == "BB"
        three_bet_set = hu_three_bet_range() if hu_bb_defend else three_bet_range(pos, vs_pos)
        call_set = hu_call_range() if hu_bb_defend else call_range(pos, vs_pos)
        # v5.5.1 (A): wide-4bettor (= wide-3bettor 상관) 가 open 한 spot 이면
        # 3bet bluff 비활성. 우리 strict value 만 3bet, 나머지는 call set 폴백.
        opener_name = _last_preflop_raiser_name(history, req.players)
        opener_is_wide = bool(
            opener_name and _is_wide_3bettor(profiles, opener_name, cfg)
        )
        if cfg.vs_wide_4bettor_disable_3bet_bluff and opener_is_wide:
            three_bet_set = three_bet_set & cfg.vs_wide_4bettor_threebet_value
            flags["vs_wide_4bettor"] = opener_name
        # v5.5.2: wide-opener 가 mini-raise 한 BB defend spot 에서 call set 확장.
        # cheap min-raise 에 우리가 기본 fold 하던 connectors/suited 까지 sticky 하게.
        if (
            cfg.vs_wide_opener_bb_defend
            and pos == "BB"
            and opener_is_wide
            and req.to_call <= int(bb * cfg.vs_wide_opener_min_size_bb)
        ):
            call_set = call_set | cfg.vs_wide_opener_bb_extra_calls
            flags["vs_wide_opener_bb_defend"] = opener_name
        # 3bet?
        if key in three_bet_set:
            mult = cfg.three_bet_mult_ip if pos in ("LP",) else cfg.three_bet_mult_oop
            target = max(int(last_raise_amt * mult), req.min_raise)
            amount = _clamp_raise_amount(target, req)
            flags["reason"] = "hu_three_bet" if hu_bb_defend else "three_bet"
            flags["threebet_size"] = amount
            return Action(room_id=room_id, action="raise", amount=amount), flags
        # cold-call 범위?
        cap = int(bb * cfg.preflop_call_cap_bb)
        flags["call_cap"] = cap
        if key in call_set and req.to_call <= cap:
            flags["reason"] = "hu_call" if hu_bb_defend else "cold_call"
            return Action(room_id=room_id, action="call"), flags
        # 무리한 call → fold. BB 에서 할인 폴드 기준은 별도로 두지 않음(보수적).
        if req.to_call == 0:
            flags["reason"] = "check_vs_raise_ignored"
            return Action(room_id=room_id, action="check"), flags
        flags["reason"] = "fold_vs_raise"
        return Action(room_id=room_id, action="fold"), flags

    # raise_cnt >= 2: 3bet+ faced → 4bet value only 혹은 fold.
    if key in four_bet_range():
        # shove 위주. 딥스택이면 4bet 후 콜 유도.
        target = max(int(last_raise_amt * cfg.four_bet_mult), req.min_raise)
        amount = _clamp_raise_amount(target, req)
        flags["reason"] = "four_bet"
        flags["fourbet_size"] = amount
        return Action(room_id=room_id, action="raise", amount=amount), flags
    # 프리미엄 페어이되 AA/KK 아닌 QQ/JJ 는 call 보수적 선택지
    if key in {"QQ", "JJ", "AKo"}:
        cap = int(bb * cfg.preflop_call_cap_bb * 2)  # 딥 call 허용
        if req.to_call <= cap:
            flags["reason"] = "call_vs_3bet_premium"
            return Action(room_id=room_id, action="call"), flags
    # v5.4 P1-5: vs wide-3bettor 면 추가 call 허용.
    raiser_name = _last_preflop_raiser_name(history, req.players)
    if (
        raiser_name
        and key in cfg.vs_wide_3bet_extra_calls
        and _is_wide_3bettor(profiles, raiser_name, cfg)
    ):
        cap = int(bb * cfg.preflop_call_cap_bb * 2)
        if req.to_call <= cap:
            flags["reason"] = "call_vs_wide_3bet"
            flags["wide_3bettor"] = raiser_name
            return Action(room_id=room_id, action="call"), flags
    if req.to_call == 0:
        flags["reason"] = "check_vs_3bet"
        return Action(room_id=room_id, action="check"), flags
    flags["reason"] = "fold_vs_3bet"
    return Action(room_id=room_id, action="fold"), flags


def _last_preflop_raiser_name(history, players) -> str | None:
    """프리플롭 마지막 raise 의 player name."""
    last_seat = _last_preflop_raiser_seat(history, players)
    if last_seat is None:
        return None
    for p in players:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if d.get("position") == last_seat or d.get("seat") == last_seat:
            name = d.get("name")
            if isinstance(name, str):
                return name
    return None


def _is_wide_3bettor(
    profiles: dict | None, name: str, cfg: StrategyConfig
) -> bool:
    """누적 profile 의 threebet_n/hands_seen 이 임계 이상이면 wide 3bettor."""
    if not profiles:
        return False
    prof = profiles.get(name)
    if not isinstance(prof, dict):
        return False
    try:
        n = int(prof.get("hands_seen", 0) or 0)
        threebet_n = int(prof.get("threebet_n", 0) or 0)
    except (TypeError, ValueError):
        return False
    if n < cfg.vs_wide_3bettor_min_hands:
        return False
    return (threebet_n / n) >= cfg.vs_wide_3bettor_threebet_rate


def _build_meta(req: ActionRequest, action: Action, flags: dict[str, object]) -> dict[str, object]:
    meta: dict[str, object] = {
        "hand_number": req.hand_number,
        "phase": req.phase,
        "seat": req.seat,
        "your_cards": list(req.your_cards),
        "community_cards": list(req.community_cards),
        "to_call": req.to_call,
        "pot": req.pot,
        "min_raise": req.min_raise,
        "my_stack": req.my_stack,
        "action": action.action,
        "amount": action.amount,
    }
    meta.update(flags)
    return meta


def _log_decision(req: ActionRequest, action: Action, flags: dict[str, object]) -> None:
    extra: dict[str, object] = {
        "room_id": req.room_id,
        "hand_number": req.hand_number,
        "phase": req.phase,
        "seat": req.seat,
        "your_cards": list(req.your_cards),
        "community_cards": list(req.community_cards),
        "to_call": req.to_call,
        "pot": req.pot,
        "action": action.action,
        "amount": action.amount,
    }
    extra.update(flags)
    logger.info("decision", extra=extra)


def _load_opponent_profiles(
    path: str, debug_dir: str | None = None
) -> dict[str, dict[str, Any]]:
    """`{name: OppProfile}` 반환. SQLite 우선, JSON 폴백.

    `debug_dir` 가 지정되고 `{debug_dir}/holdem.db` 가 존재하면 DebugStore 에서
    `get_opponent_profiles()` 로 읽는다. 없으면 기존 JSON 경로 (`path`) 로 폴백.
    파일/DB 없거나 스키마 불일치면 빈 dict. summary.py 가 게임 종료마다 갱신.
    """
    # 1) SQLite 경로 우선
    if debug_dir:
        try:
            from holdem_core.debug.store import DebugStore, default_db_path

            db_path = default_db_path(debug_dir)
            if db_path.exists():
                ds = DebugStore.open(debug_dir, read_only=True)
                try:
                    return ds.get_opponent_profiles()
                finally:
                    ds.close()
        except (OSError, ImportError):
            pass
    # 2) JSON 폴백
    try:
        p = Path(path)
        if not p.exists():
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    players = raw.get("players")
    if not isinstance(players, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, data in players.items():
        if isinstance(name, str) and isinstance(data, dict):
            out[name] = data
    return out


class BalancedStrategy:
    """포지션/M-ratio/보드 텍스처/멀티웨이/상대프로필/듀얼모드 인지 룰 기반 전략."""

    def __init__(
        self,
        cfg: StrategyConfig | None = None,
        bot_name: str | None = None,
    ) -> None:
        self.cfg = cfg or StrategyConfig()
        self._bot_name = bot_name  # bluff prior 에서 자기 자신 제외하려면 필요
        self._profiles: dict[str, dict[str, Any]] = _load_opponent_profiles(
            self.cfg.profile_path, debug_dir=self.cfg.debug_dir
        )
        self._opp_classes: dict[str, OpponentClass] = classify_all(self._profiles)
        self._profile_hits = 0  # 디버그 지표
        # Bluff Beta prior — SQLite 우선, JSON 폴백.
        self._bluff_store = self._load_bluff_store()
        self._bluff_hands_since_save = 0

    def _load_bluff_store(self) -> BluffPriorStore:
        """SQLite DB 가 있으면 open_db, 없으면 JSON path 로 load."""
        cfg = self.cfg
        if cfg.debug_dir:
            try:
                from holdem_core.debug.store import default_db_path

                if default_db_path(cfg.debug_dir).exists():
                    bs = BluffPriorStore.open_db(cfg.debug_dir)
                    # JSON 도 dual-write 하려면 path 지정.
                    bs.path = Path(cfg.bluff_prior_path) if cfg.bluff_prior_path else None
                    return bs
            except (OSError, ImportError):
                pass
        return BluffPriorStore.load(cfg.bluff_prior_path)

    def reload_profiles(self, *, clean: bool = False) -> dict[str, Any]:
        """프로필 + bluff prior 를 외부 DB/파일에서 재동기화.

        clean=False: in-flight observation 손실 방지를 위해 save_if_dirty 를 먼저 호출.
        clean=True: rename/외부 머지 직후 — stale in-memory data 가 DB 에 다시
        upsert 되는 race 를 피하려고 save 를 스킵하고 즉시 DB 에서 rehydrate.
        반환: 호출자 (HTTP endpoint 등) 가 보고용으로 쓸 카운트 + 타임스탬프.
        """
        if not clean:
            try:
                self._bluff_store.save_if_dirty()
            except Exception:
                logger.exception("bluff_save_before_reload_failed")
        self._profiles = _load_opponent_profiles(
            self.cfg.profile_path, debug_dir=self.cfg.debug_dir
        )
        self._opp_classes = classify_all(self._profiles)
        try:
            bluff_buckets = self._bluff_store.reload_from_db()
        except Exception:
            logger.exception("bluff_reload_failed")
            bluff_buckets = len(self._bluff_store.buckets)
        self._bluff_hands_since_save = 0
        return {
            "profiles_count": len(self._profiles),
            "bluff_buckets": bluff_buckets,
            "ts": time.time(),
        }

    def on_hand_result(
        self,
        evt: Any,
        pre_history: list[Any],
        my_seat: str | None,
    ) -> None:
        """핸드 종료 시 ws/client.py 에서 호출. posterior 업데이트 + 주기적 flush."""
        if not self.cfg.enable_bluff_model:
            return
        try:
            observe_hand_result(
                evt,
                pre_history,
                self._bluff_store,
                self._bot_name,
                equity_samples=self.cfg.bluff_observe_equity_samples,
            )
        except Exception:
            logger.exception("bluff_observe_failed")
            return
        self._bluff_hands_since_save += 1
        if (
            self._bluff_store._dirty
            and self._bluff_hands_since_save >= self.cfg.bluff_save_interval
        ):
            try:
                self._bluff_store.save()
                self._bluff_hands_since_save = 0
            except Exception:
                logger.exception("bluff_save_failed")

    def _resolve_mode_for_request(self, req: ActionRequest) -> str:
        """이번 결정에 사용할 모드 ('exploit' / 'balanced')."""
        active_names: list[str] = []
        for p in req.players:
            d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
            if d.get("status") in ("folded", "eliminated"):
                continue
            if d.get("position") == req.seat:
                continue
            name = d.get("name")
            if isinstance(name, str):
                active_names.append(name)
        return resolve_table_mode(active_names, self._opp_classes, self.cfg.mode)

    def decide(self, req: ActionRequest) -> Action:
        # v3 듀얼 모드: 실제 전략 분기는 아직 exploit 경로 공유. mode 값은 meta 로 기록해서
        # 다음 iteration 에서 balanced 분기 추가 시 확인 가능.
        table_mode = self._resolve_mode_for_request(req)
        if req.phase == "preflop":
            action, flags = _preflop_decision(req, self.cfg, profiles=self._profiles)
        else:
            action, flags = self._postflop(req)
        flags["table_mode"] = table_mode
        flags["cfg_mode"] = self.cfg.mode
        action.meta = _build_meta(req, action, flags)
        _log_decision(req, action, flags)
        return action

    def _postflop(self, req: ActionRequest) -> tuple[Action, dict[str, object]]:
        cfg = self.cfg
        room_id = req.room_id
        hole = list(req.your_cards)
        board = list(req.community_cards)

        # 1) 메이드핸드
        made = classify_hand(hole + board)

        # 2) 멀티웨이 판정
        n_opps = _active_nonfolded_opps(req.players, req.seat)
        multiway = n_opps >= 2

        # 3) 상대 레인지 (포스트플롭 narrow 반영)
        history_raw = [
            a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in req.action_history
        ]
        texture = board_texture(board)

        # v3: 내 드로우(플러시/스트레이트) 감지 — 싸게 보고 싶을 때 call 허용.
        draw = detect_draws(hole, board)

        # 4) equity 계산
        t0 = time.monotonic()
        flags_tier: str | None
        opp_threat: str | None
        # v2: profile 을 opp_range 계층에 전달해서 VPIP 기반 tier 보정.
        profile_kwargs = {
            "profiles": self._profiles or None,
            "profile_min_hands": cfg.profile_min_hands,
            "profile_vpip_tight": cfg.profile_vpip_tight,
            "profile_vpip_wide": cfg.profile_vpip_wide,
        }
        if multiway:
            # 멀티웨이: 활성 상대 각각의 tier 조회 + narrow.
            opp_list = all_opp_combos(req, **profile_kwargs)
            combos_list: list[list[tuple[str, str]] | None] = []
            for name, combos in opp_list:
                if combos is None:
                    combos_list.append(None)
                    continue
                narrowed = narrow_by_postflop(combos, name, history_raw, board)
                combos_list.append(narrowed)
            samples = max(
                cfg.mc_samples,
                cfg.multiway_min_samples_per_opp * (n_opps + 1),
            )
            equity = equity_mc_multi(
                hole,
                board,
                n_opps=n_opps,
                opp_combos_list=combos_list,
                samples=samples,
            )
            flags_tier = "multiway"
            opp_threat = f"{len(opp_list)}opps"
            combos_n = sum(len(c) if c else 0 for c in combos_list)
            samples_used = samples
            hu_opp_combos: list[tuple[str, str]] | None = None
        else:
            opp_combos, threat_name, tier = infer_opp_combos(req, **profile_kwargs)
            # narrow 적용
            if opp_combos and threat_name:
                opp_combos = narrow_by_postflop(opp_combos, threat_name, history_raw, board)
            samples_used = cfg.mc_samples
            equity = equity_mc(
                hole,
                board,
                samples=samples_used,
                opp_combos=opp_combos,
            )
            flags_tier = tier
            opp_threat = threat_name
            combos_n = len(opp_combos) if opp_combos else 0
            hu_opp_combos = opp_combos
        equity_ms = (time.monotonic() - t0) * 1000.0

        pot_odds = req.to_call / (req.pot + req.to_call) if req.to_call > 0 else 0.0
        m = effective_m(req)

        # v2: multiway 는 base=0.85 로 시작하고, 4-way 이상(n_opps>=3) 부터 추가 페널티.
        # 이전 코드는 base + penalty*(n-1) 로 중첩되어 3-way 에서 0.85, 4-way 에서 0.93 로
        # 과도했음. 이제 3-way=0.85, 4-way=0.85+0.08=0.93, 5-way=0.85+0.16=0.95(clamp).
        if multiway:
            raise_thr = cfg.equity_raise_threshold_multiway_base
            if n_opps >= 3:
                raise_thr += cfg.multiway_raise_penalty * (n_opps - 2)
            raise_thr = min(0.95, raise_thr)
            value_thr = min(0.90, cfg.equity_value_bet_threshold + 0.05 * (n_opps - 1))
        else:
            raise_thr = cfg.equity_raise_threshold
            value_thr = cfg.equity_value_bet_threshold

        # v4: top10 상대 보수 편향. primary threat tier 가 top10 이면 raise_thr 미세 상향.
        top10_threat = (not multiway) and flags_tier == "top10"
        if top10_threat:
            raise_thr = min(0.95, raise_thr + cfg.top10_raise_thr_bonus)

        # v5.4: opp_threat 의 W$SD 가 높으면 (nit-y SD) margin 약간 상향 — 그 상대가
        # bet 으로 SD 까지 끌고 가면 강한 핸드일 확률 높음. raise_thr 도 미세 상향.
        wssd_aggro_threat = False
        if opp_threat and not multiway:
            prof_t = self._profiles.get(opp_threat)
            if isinstance(prof_t, dict):
                sd_n = int(prof_t.get("showdown_n") or prof_t.get("showdowns") or 0)
                sd_w = int(prof_t.get("showdown_won_n") or 0)
                if sd_n >= cfg.wssd_min_showdowns:
                    wssd = sd_w / sd_n if sd_n > 0 else 0.0
                    if wssd >= cfg.wssd_pct_high:
                        wssd_aggro_threat = True
                        raise_thr = min(0.95, raise_thr + cfg.wssd_aggro_margin_bonus)

        # v5 §B: SPR-indexed threshold/sizing adjustment.
        spr_val = spr_value(req.my_stack, req.pot)
        bucket = spr_bucket(req.my_stack, req.pot, cfg.spr_low_max, cfg.spr_high_min)
        spr_adj = adjust_for_bucket(
            bucket,
            cfg.spr_raise_thr_low,
            cfg.spr_raise_thr_high,
            cfg.spr_call_margin_low,
            cfg.spr_call_margin_high,
            cfg.spr_draw_pot_low,
            cfg.spr_draw_pot_high,
            cfg.spr_bet_frac_low,
            cfg.spr_bet_frac_high,
        )
        if cfg.enable_spr_tree:
            raise_thr = max(0.35, min(0.98, raise_thr + spr_adj.raise_thr_delta))

        # v5 §C: range_advantage. hero 레인지 재구성 + MC.
        ra_value: float | None = None
        ra_delta: float = 0.0
        if cfg.enable_range_advantage and not multiway and len(board) >= 3:
            my_name = _my_player_name(req.players, req.seat)
            if my_name:
                pos_for_ra: Position = classify_position(req.seat, req.players)
                mine_actions = my_preflop_actions(history_raw, my_name)
                dead = set(hole) | set(board)
                hero_combos = hero_range_combos(pos_for_ra, mine_actions, dead, vs_pos=None)
                ra_opp_combos = hu_opp_combos
                try:
                    ra_value = range_advantage(
                        hero_combos,
                        ra_opp_combos,
                        board,
                        samples=cfg.range_advantage_samples,
                    )
                except Exception:
                    ra_value = None
                if ra_value is not None:
                    if ra_value >= cfg.ra_high_threshold:
                        ra_delta = -cfg.ra_raise_thr_delta
                    elif ra_value <= cfg.ra_low_threshold:
                        ra_delta = cfg.ra_raise_thr_delta
                    raise_thr = max(0.35, min(0.98, raise_thr + ra_delta))

        flags: dict[str, object] = {
            "equity": round(equity, 4),
            "pot_odds": round(pot_odds, 4),
            "equity_ms": round(equity_ms, 1),
            "mc_samples": samples_used,
            "made_hand": made["category"],
            "made_hand_ko": made["category_ko"],
            "opp_tier": flags_tier,
            "opp_threat": opp_threat,
            "opp_combos_n": combos_n,
            "multiway": multiway,
            "n_opps": n_opps,
            "m_ratio": round(m, 2),
            "texture_wetness": texture.wetness,
            "texture_flush_draw": texture.flush_draw,
            "texture_flush_made": texture.flush_made,
            "texture_straight_draw": texture.straight_draw,
            "texture_straight_made": texture.straight_made,
            "texture_paired": texture.paired,
            "raise_thr": round(raise_thr, 3),
            "value_thr": round(value_thr, 3),
            "top10_threat": top10_threat,
            "wssd_aggro_threat": wssd_aggro_threat,
            "profiles_loaded": len(self._profiles),
            "draw_flush": draw.has_flush_draw,
            "draw_flush_made": draw.has_flush_made,
            "draw_oesd": draw.has_oesd,
            "draw_gutshot": draw.has_gutshot,
            "draw_outs": draw.outs,
            "draw_live": draw.is_live_draw,
            "spr": round(spr_val, 2),
            "spr_bucket": bucket,
            "spr_raise_thr_delta": round(spr_adj.raise_thr_delta, 3),
            "spr_bet_frac_mult": round(spr_adj.bet_frac_mult, 2),
            "range_advantage": round(ra_value, 3) if ra_value is not None else None,
            "ra_delta": round(ra_delta, 3),
        }

        # committed allin short-stack
        committed = (req.to_call + req.pot) >= int(req.my_stack * 0.5)
        flags["committed"] = committed
        # v5.4: tier-conditional commit floor. strong opp 일수록 더 높은 equity 요구.
        if flags_tier == "top10":
            commit_floor = cfg.committed_shove_equity_floor_top10
        elif flags_tier == "top20":
            commit_floor = cfg.committed_shove_equity_floor_top20
        else:
            commit_floor = cfg.committed_shove_equity_floor
        # v5.5.1 (B): turn/river 의 strong opp shove 는 fold-equity 11% 미만 +
        # sd_win 70%+ → 더 보수적 floor.
        if flags_tier in ("top10", "top20") and req.phase in ("turn", "river"):
            commit_floor += cfg.commit_floor_turn_river_bonus
            flags["commit_floor_late_bonus"] = True
        flags["commit_floor"] = commit_floor
        if committed and m < 10 and equity >= commit_floor and req.my_stack > 0:
            flags["reason"] = "committed_shove"
            return Action(room_id=room_id, action="allin", amount=req.my_stack), flags

        # v3 드로우 우선 처리: made hand 가 약한데 드로우만 있으면 싸게 call, raise 금지.
        # (equity 가 raise_thr 이상인 경우는 made hand 가 이미 강하므로 드로우 규칙 생략)
        draw_only = (
            draw.is_live_draw
            and equity < raise_thr
            and made["category_rank"] <= 2  # high_card 또는 one_pair 이하
        )
        if draw_only and cfg.draw_no_aggression:
            # to_call==0 이면 무료 체크 (공짜로 본다)
            if req.to_call == 0:
                flags["reason"] = "draw_check_free"
                return Action(room_id=room_id, action="check"), flags
            # 비싼 가격이면 fold, 싸면 call (pot-odds + 스택 비율 양쪽 조건)
            price_pot_ratio = req.to_call / max(req.pot + req.to_call, 1)
            price_stack_ratio = req.to_call / max(req.my_stack, 1)
            flags["draw_price_pot"] = round(price_pot_ratio, 3)
            flags["draw_price_stack"] = round(price_stack_ratio, 3)
            draw_pot_max = cfg.draw_call_pot_ratio_max
            if cfg.enable_spr_tree:
                draw_pot_max = max(0.1, min(0.6, draw_pot_max + spr_adj.draw_pot_ratio_delta))
            if (
                price_pot_ratio <= draw_pot_max
                and price_stack_ratio <= cfg.draw_call_stack_ratio_max
            ):
                flags["reason"] = "draw_call_cheap"
                return Action(room_id=room_id, action="call"), flags
            # 싸지 않으면 일반 equity 비교로 진행 (아래 fallthrough). 기록만.
            flags["draw_too_expensive"] = True

        # --- 기본 사이징 타겟 (SPR bet_frac 배율 적용) ----------------------------
        def _sized_target() -> int:
            raw = size_bet(
                req.phase,
                equity,
                texture,
                req.pot,
                req.min_raise,
                req.my_stack,
                cfg,
                n_opps=n_opps,
            )
            if cfg.enable_spr_tree and spr_adj.bet_frac_mult != 1.0:
                raw = int(raw * spr_adj.bet_frac_mult)
                raw = max(req.min_raise, min(raw, req.my_stack))
            return raw

        # call margin 계산 (EV / threshold 양쪽에서 재사용).
        if multiway:
            margin = cfg.equity_call_margin_multiway
            if n_opps >= 3:
                margin += 0.02 * (n_opps - 2)
        else:
            margin = cfg.equity_call_margin
        if top10_threat:
            margin += cfg.top10_call_margin_bonus
        if wssd_aggro_threat:
            margin += cfg.wssd_aggro_margin_bonus
        river_discount = req.phase == "river" and pot_odds >= cfg.river_call_pot_odds_min
        if river_discount:
            margin = max(0.0, margin - cfg.river_call_margin_discount)
            flags["river_margin_discount"] = True
        if cfg.enable_spr_tree:
            margin = max(0.0, margin + spr_adj.call_margin_delta)

        # v5.1 뻥카 Beta prior: 상대의 최근 aggressive action 에 대한 뻥카 posterior.
        # confidence 기반 blend 로 margin / fold_equity 모두 조정.
        bluff_est: OppBluffEstimate | None = None
        bluff_margin_adj = 0.0
        bluff_fe_adj = 0.0
        if cfg.enable_bluff_model:
            try:
                bluff_est = estimate_opp_bluff_prob(req, self._bluff_store)
            except Exception:
                bluff_est = None
                logger.exception("bluff_estimate_failed")
            if bluff_est is not None and bluff_est.confidence >= cfg.bluff_min_confidence:
                # confidence 로 스케일. 확실한 정보일수록 크게 반영.
                scale = bluff_est.confidence
                if bluff_est.prob >= cfg.bluff_high_threshold:
                    # 뻥카 성향 높음 → 내가 call 하기 더 유리 (margin 완화)
                    bluff_margin_adj = -cfg.bluff_margin_delta * scale
                    # 뻥카쟁이는 raise 당해도 잘 fold 안 함
                    bluff_fe_adj = -cfg.bluff_fe_delta * scale
                elif bluff_est.prob <= cfg.bluff_low_threshold:
                    # value 성향 → 엄격하게 (margin 상향)
                    bluff_margin_adj = cfg.bluff_margin_delta * scale
                    # value 중심 상대는 raise 당하면 약한건 접음
                    bluff_fe_adj = cfg.bluff_fe_delta * scale
                    # v5.4 P1-3: river 는 value-heavy 가 더 강한 시그널이라 boost.
                    if req.phase == "river":
                        bluff_margin_adj *= cfg.bluff_river_value_boost
                        flags["bluff_river_boost"] = True
                elif (
                    req.phase in ("flop", "turn")
                    and cfg.bluff_mid_threshold <= bluff_est.prob < cfg.bluff_high_threshold
                ):
                    # v5.4 P1-4: flop/turn 에서 0.40-0.50 mid posterior 도 절반 효과로 활용.
                    # (너구리쿤 flop/small/raise 0.45 같은 spot — 무시하면 over-fold).
                    half = scale * cfg.bluff_mid_scale
                    bluff_margin_adj = -cfg.bluff_margin_delta * half
                    bluff_fe_adj = -cfg.bluff_fe_delta * half
                    flags["bluff_mid_signal"] = True
                margin = max(0.0, margin + bluff_margin_adj)
        if bluff_est is not None:
            flags["opp_bluff_prob"] = round(bluff_est.prob, 3)
            flags["opp_bluff_conf"] = round(bluff_est.confidence, 3)
            flags["opp_bluff_player"] = bluff_est.player
            flags["opp_bluff_action"] = bluff_est.action
            flags["opp_bluff_sizing"] = bluff_est.sizing
            flags["opp_bluff_reason"] = bluff_est.reason
            if bluff_margin_adj != 0.0:
                flags["bluff_margin_adj"] = round(bluff_margin_adj, 3)
            if bluff_fe_adj != 0.0:
                flags["bluff_fe_adj"] = round(bluff_fe_adj, 3)

        # v5 §A: EV-based decision (argmax). 기존 threshold 는 safety floor 유지.
        if cfg.enable_ev_engine:
            profile_stats = self._profiles.get(opp_threat or "", None) if opp_threat else None
            fe = estimate_fold_equity(
                opp_tier=flags_tier if isinstance(flags_tier, str) else None,
                board_wetness=texture.wetness,
                profile_stats=profile_stats,
                phase=req.phase,
                multiway=multiway,
            )
            if bluff_fe_adj != 0.0:
                fe = max(0.05, min(0.70, fe + bluff_fe_adj))
            target_raise = _sized_target()
            ev = action_ev(
                equity=equity,
                pot=req.pot,
                to_call=req.to_call,
                my_stack=req.my_stack,
                raise_size=target_raise,
                fold_equity=fe,
            )
            flags["fe"] = round(fe, 3)
            flags["ev_raise"] = round(ev.ev_raise, 1)
            flags["ev_call"] = round(ev.ev_call, 1)
            flags["ev_check"] = round(ev.ev_check, 1)
            flags["ev_choice"] = ev.choice

            # Safety 1: EV argmax 가 raise 를 골랐지만 equity 너무 낮으면 downgrade.
            # v5.4: tier-conditional floor.
            if flags_tier == "top10":
                ev_floor = cfg.ev_raise_equity_floor_top10
            elif flags_tier == "top20":
                ev_floor = cfg.ev_raise_equity_floor_top20
            else:
                ev_floor = cfg.ev_raise_equity_floor
            flags["ev_floor"] = ev_floor
            if ev.choice == "raise" and equity < ev_floor:
                flags["ev_safety"] = "raise_floor_block"
                # to_call==0 이면 check, 아니면 call 또는 fold 중 EV 우선.
                ev = action_ev(
                    equity=equity,
                    pot=req.pot,
                    to_call=req.to_call,
                    my_stack=req.my_stack,
                    raise_size=req.to_call,
                    fold_equity=fe,
                )
            # Safety 2: pot_odds 극단적으로 나쁘면 fold 강제.
            if (
                ev.choice in ("call", "raise")
                and pot_odds >= cfg.ev_extreme_pot_odds_fold
                and equity < pot_odds
            ):
                flags["ev_safety"] = "extreme_pot_odds_fold"
                action = Action(room_id=room_id, action="fold")
                flags["reason"] = "ev_extreme_fold"
                return action, flags

            # EV argmax 결과를 Action 으로 번역.
            if ev.choice == "raise":
                target = target_raise
                amount = _clamp_raise_amount(target, req)
                # 추가 safety: equity 가 raise_thr 에도 못 미치고 to_call>0 이면
                # (pure bluff raise 시도), margin check 로 하강 — v4 호환 call 시도.
                if equity < raise_thr and req.to_call > 0 and equity < pot_odds + margin:
                    # EV+ 가 아니면 fold (EV 가 양수여도 보수적 기본값).
                    if ev.ev_raise <= 0 and ev.ev_call <= 0:
                        flags["reason"] = "ev_bluff_blocked_fold"
                        return Action(room_id=room_id, action="fold"), flags
                flags["reason"] = (
                    "ev_raise_strong"
                    if equity >= raise_thr
                    else ("ev_raise_thin" if req.to_call == 0 else "ev_raise_bluff")
                )
                flags["bet_target"] = amount
                return Action(room_id=room_id, action="raise", amount=amount), flags

            if ev.choice == "call":
                # to_call==0 이면 check 대신 value_bet 여부 재확인.
                if req.to_call == 0 and equity >= value_thr:
                    target = _sized_target()
                    amount = _clamp_raise_amount(target, req)
                    flags["reason"] = "ev_value_bet"
                    flags["bet_target"] = amount
                    return Action(room_id=room_id, action="raise", amount=amount), flags
                max_call = int(req.my_stack * cfg.postflop_call_cap_fraction)
                if req.to_call > max_call:
                    flags["reason"] = "ev_call_cap_exceeded"
                    return Action(room_id=room_id, action="fold"), flags
                flags["reason"] = "ev_call"
                return Action(room_id=room_id, action="call"), flags

            if ev.choice == "check":
                flags["reason"] = "ev_check"
                return Action(room_id=room_id, action="check"), flags

            # fold
            flags["reason"] = "ev_fold"
            return Action(room_id=room_id, action="fold"), flags

        # --- v4 호환 경로 (enable_ev_engine=False 시) ------------------------------

        # 1) 매우 강함 → raise/bet
        if equity >= raise_thr:
            target = _sized_target()
            amount = _clamp_raise_amount(target, req)
            flags["reason"] = "raise_strong" if req.to_call > 0 else "bet_strong"
            flags["bet_target"] = amount
            return Action(room_id=room_id, action="raise", amount=amount), flags

        # 2) 체크백 value bet
        if equity >= value_thr and req.to_call == 0:
            target = _sized_target()
            amount = _clamp_raise_amount(target, req)
            flags["reason"] = "value_bet"
            flags["bet_target"] = amount
            return Action(room_id=room_id, action="raise", amount=amount), flags

        # 3) 콜 상황
        if req.to_call > 0:
            max_call = int(req.my_stack * cfg.postflop_call_cap_fraction)
            if req.to_call > max_call:
                flags["reason"] = "call_cap_exceeded"
                return Action(room_id=room_id, action="fold"), flags
            if equity >= pot_odds + margin:
                flags["reason"] = "positive_ev_call"
                return Action(room_id=room_id, action="call"), flags
            flags["reason"] = "negative_ev_fold"
            return Action(room_id=room_id, action="fold"), flags

        # 4) 프리 체크
        flags["reason"] = "check_free"
        return Action(room_id=room_id, action="check"), flags
