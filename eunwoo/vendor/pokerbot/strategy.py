"""포커 봇 전략 — 헤즈업 + 멀티웨이(3-9인) 대응

Phase 7: 멀티웨이 전략 설계 + 구현

- wooz (ExploitativeLAG): 상대 약점을 착취하는 루즈 공격형
- hugo (AdaptiveTAG): GTO 기반 타이트 공격형 + 상대 적응

멀티웨이 핵심 원칙:
  - 프리플롭: 포지션별 오픈 레인지 축소 (EP < MP < LP)
  - 포스트플롭: 블러프 빈도 대폭 감소, 밸류 위주
  - equity: 상대 수 반영 (2명+ → equity 하락)
  - OOP에서 더 타이트
"""

from __future__ import annotations
import random
from abc import ABC, abstractmethod

from models import ActionRequest, ActionResponse
from game_state import GameState
from profiler import Profiler, PlayerType, PlayerStats, AdaptiveParams
from hand_eval import hand_strength_score, preflop_tier, detect_draws
from equity import calc_equity
from hot_config import HotConfig
from preflop_equity import lookup_preflop_equity, is_in_push_range
from range_estimator import RangeEstimator


# ═══════════════════════════════════════════════════════════════
# 포지션 카테고리 (멀티웨이)
# ═══════════════════════════════════════════════════════════════

# 포지션 → 카테고리 매핑 (3-9인)
# EP = early position (UTG, UTG+1, UTG+2)
# MP = middle position (MP, HJ)
# LP = late position (CO, BTN)
# BLIND = SB, BB
POSITION_CATEGORY = {
    "utg": "EP", "utg1": "EP", "utg2": "EP",
    "mp": "MP", "mp1": "MP", "hj": "MP",
    "co": "LP", "btn": "LP",
    "sb": "BLIND", "bb": "BLIND",
}

# 포지션별 오픈 레인지 — 최대 프리플롭 티어 (낮을수록 타이트)
# EP: 매우 타이트, MP: 보통, LP: 넓게, BLIND: 상황에 따라
MULTIWAY_OPEN_TIER = {
    "EP": 3,   # AA-QQ, AKs-AQs, AKo (tier 1-3)
    "MP": 4,   # + AJs, KQs, TT-99, A9s+ (tier 1-4)
    "LP": 6,   # + suited connectors, broadways (tier 1-6)
    "BLIND": 5,  # SB/BB은 스퀴즈/디펜스 기반
}


class BaseStrategy(ABC):

    def __init__(self, profiler: Profiler, config: HotConfig = None):
        self.profiler = profiler
        self.config = config
        self.use_ai = False

    def _cfg(self, key: str, default):
        """Hot Reload 설정값 조회"""
        if self.config:
            return self.config.get(key, default)
        return default

    @abstractmethod
    def decide(self, req: ActionRequest, state: GameState | None) -> ActionResponse:
        ...

    # ── 액션 헬퍼 ──

    def _fold(self) -> ActionResponse:
        return ActionResponse(action="fold")

    def _check(self) -> ActionResponse:
        return ActionResponse(action="check")

    def _call(self) -> ActionResponse:
        return ActionResponse(action="call")

    def _raise(self, amount: int) -> ActionResponse:
        return ActionResponse(action="raise", amount=amount)

    def _allin(self) -> ActionResponse:
        return ActionResponse(action="allin")

    def _safe_raise(self, amount: int, req: ActionRequest) -> ActionResponse:
        max_amt = req.my_stack + req.investment
        amount = max(amount, req.min_raise)
        if amount >= max_amt:
            return self._allin()
        return self._raise(amount)

    def _check_or_fold(self, req: ActionRequest) -> ActionResponse:
        return self._check() if self._can_check(req) else self._fold()

    # ── 상황 판단 ──

    def _can_check(self, req: ActionRequest) -> bool:
        return req.to_call == 0

    def _pot_odds(self, req: ActionRequest) -> float:
        if req.to_call == 0:
            return 0.0
        return req.to_call / (req.pot + req.to_call)

    def _spr(self, req: ActionRequest) -> float:
        if req.pot == 0:
            return float("inf")
        return req.my_stack / req.pot

    def _bb(self, req: ActionRequest) -> int:
        return req.blind[1] if len(req.blind) >= 2 else 2

    def _effective_stack_bb(self, req: ActionRequest) -> float:
        """유효 스택 (BB 단위) — 숏스택 판단"""
        bb = self._bb(req)
        return req.my_stack / bb if bb > 0 else 999

    def _active_count(self, req: ActionRequest) -> int:
        return sum(1 for p in req.players if p.status in ("active", "allin"))

    def _is_btn(self, req: ActionRequest) -> bool:
        return req.seat == "btn"

    def _is_bb(self, req: ActionRequest) -> bool:
        return req.seat == "bb"

    def _is_sb(self, req: ActionRequest) -> bool:
        return req.seat == "sb"

    def _is_heads_up(self, req: ActionRequest) -> bool:
        return self._active_count(req) == 2

    def _is_multiway(self, req: ActionRequest) -> bool:
        """멀티웨이(3인 이상) 여부"""
        return self._active_count(req) >= 3

    def _num_players_total(self, req: ActionRequest) -> int:
        """테이블 전체 플레이어 수 (eliminated 제외)"""
        return len([p for p in req.players if p.status != "eliminated"])

    def _position_category(self, req: ActionRequest) -> str:
        """현재 포지션 카테고리 (EP/MP/LP/BLIND)"""
        return POSITION_CATEGORY.get(req.seat, "MP")

    def _multiway_open_tier(self, req: ActionRequest) -> int:
        """멀티웨이에서 현 포지션의 최대 오픈 티어"""
        cat = self._position_category(req)
        return MULTIWAY_OPEN_TIER.get(cat, 5)

    def _players_yet_to_act(self, req: ActionRequest) -> int:
        """프리플롭에서 아직 행동하지 않은 플레이어 수 (대략 추정)"""
        acted = set()
        for a in req.action_history:
            if a.phase == "preflop":
                acted.add(a.player)
        active_names = {p.name for p in req.players if p.status in ("active", "allin")}
        return len(active_names - acted)

    def _phase_raises(self, req: ActionRequest) -> int:
        return sum(1 for a in req.action_history if a.action == "raise" and a.phase == req.phase)

    def _last_aggressor(self, req: ActionRequest) -> PlayerStats | None:
        for a in reversed(req.action_history):
            if a.phase == req.phase and a.action == "raise":
                return self.profiler.get_stats(req.game_id, a.player)
        return None

    def _opponent_profile(self, req: ActionRequest) -> PlayerStats | None:
        """직접 상대의 프로파일 (헤즈업) 또는 최근 어그레서 (멀티웨이)"""
        if self._is_multiway(req):
            return self._last_aggressor(req)
        opp_pos = "btn" if req.seat == "bb" else "bb"
        for p in req.players:
            if p.position == opp_pos:
                return self.profiler.get_stats(req.game_id, p.name)
        return None

    def _is_ip(self, req: ActionRequest) -> bool:
        """포스트플롭에서 IP(인포지션) 여부"""
        if self._is_multiway(req):
            # 멀티웨이: BTN이 최고 IP, CO는 준 IP
            return req.seat in ("btn", "co")
        return self._is_btn(req)

    def _bet_size_for_position(self, req: ActionRequest, street: str,
                                base_low: float, base_high: float) -> int:
        """포지션 기반 벳 사이즈 — IP는 작게, OOP는 크게"""
        if self._is_multiway(req):
            # 멀티웨이: 벳 사이즈 10-20% 키움 (프로텍션)
            mw_mult = 1.15
        else:
            mw_mult = 1.0

        if self._is_ip(req):
            ratio = random.uniform(base_low * 0.7, base_high * 0.8) * mw_mult
        else:
            ratio = random.uniform(base_low * 1.0, base_high * 1.15) * mw_mult
        return max(int(req.pot * ratio), req.min_raise)

    def _estimate_opp_range(self, req: ActionRequest) -> RangeEstimator:
        """현재 핸드의 상대 레인지 추정"""
        opp = self._opponent_profile(req)
        est = RangeEstimator(opp)
        my_name = None
        for p in req.players:
            if p.position == req.seat:
                my_name = p.name
                break
        if my_name:
            for rec in req.action_history:
                if rec.player == my_name:
                    continue
                bet_pct = 0
                if rec.amount and req.pot > 0:
                    bet_pct = rec.amount / max(1, req.pot)
                est.update(rec.phase, rec.action, bet_pct_pot=bet_pct)
        return est

    def _adaptive(self) -> AdaptiveParams:
        """적응형 파라미터 조회"""
        return self.profiler.get_adaptive_params()

    def _try_ai_decision(self, req: ActionRequest) -> ActionResponse | None:
        """AI 모드: claude -p로 포스트플롭 판단 시도. 실패 시 None."""
        if not self.use_ai:
            return None
        if req.phase == "preflop":
            return None  # 프리플롭은 기존 룰 유지 (속도)

        from claude_advisor import ask_claude, build_game_context

        context = build_game_context(req, None, self.profiler)
        result = ask_claude(context, timeout=60)
        if result is None:
            return None

        # confidence < 0.5면 기존 룰 우선
        if result.get("confidence", 0) < 0.5:
            import logging
            logging.getLogger("pokerbot.ai").info(
                f"AI confidence {result['confidence']:.2f} < 0.5 → 룰 기반 폴백"
            )
            return None

        action = result["action"]

        # check: to_call > 0이면 fold로 변환
        if action == "check":
            if req.to_call > 0:
                return self._fold()
            return self._check()

        if action == "fold":
            # 체크 가능하면 체크로 보정 (무의미한 폴드 방지)
            if req.to_call == 0:
                return self._check()
            return self._fold()

        if action == "call":
            if req.to_call == 0:
                return self._check()
            return self._call()

        if action == "raise":
            raise_amount = result.get("raise_amount")
            if raise_amount is not None:
                # min_raise ~ max_raise 범위 내로 보정
                max_amt = req.my_stack + req.investment
                raise_amount = max(raise_amount, req.min_raise)
                if raise_amount >= max_amt:
                    return self._allin()
                return self._raise(raise_amount)
            else:
                return self._safe_raise(req.min_raise, req)

        return None

    def _gto_river_bluff_freq(self, req: ActionRequest, bet_size_ratio: float) -> float:
        """GTO 리버 블러프 빈도 = bet / (bet + pot). 상대 폴드율로 착취 보정."""
        gto_freq = bet_size_ratio / (1.0 + bet_size_ratio)

        # 멀티웨이: 블러프 빈도 대폭 감소 (상대가 여러 명이면 누군가 콜할 확률 급증)
        num_opp = max(1, self._active_count(req) - 1)
        if num_opp >= 2:
            # n명 상대 → 모두 폴드 확률 = fold_rate^n → 블러프 효율 급감
            gto_freq *= max(0.1, 1.0 / num_opp)

        opp = self._last_aggressor(req) or self._opponent_profile(req)
        if opp and opp.hands_seen >= 5:
            mdf = 1.0 / (1.0 + bet_size_ratio)
            opp_fold = opp.fold_rate
            if opp_fold > (1 - mdf):
                return min(gto_freq * 1.4, 0.50)
            elif opp_fold < (1 - mdf) * 0.7:
                return gto_freq * 0.5
        return gto_freq

    # ── 멀티웨이 공통 포스트플롭 ──

    def _multiway_postflop(self, req: ActionRequest, aggression: str = "normal") -> ActionResponse:
        """멀티웨이 포스트플롭 — 밸류 위주, 블러프 최소화

        aggression: "aggressive" (wooz), "normal" (hugo)
        """
        num_opp = max(1, self._active_count(req) - 1)
        equity = calc_equity(req.pocket_cards, req.community_cards,
                             num_opponents=num_opp, simulations=800)

        spr = self._spr(req)
        pot_odds = self._pot_odds(req)
        ip = self._is_ip(req)
        is_river = req.phase == "river"

        # 레인지 추정
        opp = self._last_aggressor(req) or self._opponent_profile(req)
        opp_type = opp.effective_type if opp and opp.hands_seen >= 5 else PlayerType.UNKNOWN

        opp_range = self._estimate_opp_range(req)
        range_top, range_pol = opp_range.get_range()
        if req.to_call > 0 and range_top < 0.30:
            equity *= 0.88  # 멀티웨이에서 더 보수적 하향
        elif req.to_call > 0 and range_pol > 0.6:
            equity *= 0.93

        # 멀티웨이 equity 임계값은 헤즈업보다 높아야 함
        # 2명 상대 → +5%, 3명 → +8%, 4명+ → +10%
        mw_penalty = min(0.10, 0.03 * num_opp)

        nut_threshold = 0.80 + mw_penalty
        strong_threshold = 0.60 + mw_penalty
        medium_threshold = 0.40 + mw_penalty
        weak_threshold = 0.25 + mw_penalty

        # ── 넛급 ──
        if equity >= nut_threshold:
            if req.to_call > 0:
                if spr < 3:
                    return self._allin()
                return self._safe_raise(int(req.min_raise * 2), req)
            # 멀티웨이 넛: 항상 밸류벳 (트랩 안 함 — 프리카드 위험)
            size = self._bet_size_for_position(req, req.phase, 0.65, 0.85)
            return self._safe_raise(size, req)

        # ── 강한 핸드 ──
        if equity >= strong_threshold:
            if req.to_call > 0:
                return self._call()
            if self._can_check(req):
                # 멀티웨이: IP면 밸류벳, OOP면 체크레이즈 기회 대기
                if ip:
                    size = self._bet_size_for_position(req, req.phase, 0.50, 0.70)
                    return self._safe_raise(size, req)
                # OOP: 밸류벳 위주 (체크레이즈 트랩은 멀티웨이에서 위험)
                if random.random() < 0.65:
                    size = self._bet_size_for_position(req, req.phase, 0.55, 0.75)
                    return self._safe_raise(size, req)
                return self._check()
            return self._call()

        # ── 중간 핸드 ──
        if equity >= medium_threshold:
            if self._can_check(req):
                # 멀티웨이 중간 핸드: 주로 체크 (팟 컨트롤)
                if ip and aggression == "aggressive" and random.random() < 0.35:
                    size = self._bet_size_for_position(req, req.phase, 0.35, 0.50)
                    return self._safe_raise(size, req)
                return self._check()
            # 콜 판정: 팟오즈 기반 (멀티웨이 암묵적 오즈 고려)
            # 멀티웨이에서 implied odds가 좋음 (맞으면 여러 상대에서 칩 회수)
            implied_bonus = 0.03 * num_opp  # 상대가 많을수록 implied odds 증가
            if pot_odds < equity + implied_bonus:
                return self._call()
            return self._fold()

        # ── 약한 핸드 (드로우) ──
        if equity >= weak_threshold:
            if self._can_check(req):
                return self._check()
            # 드로우: 멀티웨이에서 팟오즈 좋으면 콜 (implied odds)
            implied_bonus = 0.03 * num_opp
            if pot_odds < equity + implied_bonus:
                return self._call()
            return self._fold()

        # ── 쓰레기 ──
        if self._can_check(req):
            # 멀티웨이: 블러프 거의 안 함 (누군가 콜할 확률 높음)
            if is_river and num_opp == 2 and ip and aggression == "aggressive":
                bluff_freq = self._gto_river_bluff_freq(req, 0.67)
                if random.random() < bluff_freq:
                    size = max(int(req.pot * 0.67), req.min_raise)
                    return self._safe_raise(size, req)
            return self._check()
        return self._fold()


# ═══════════════════════════════════════════════════════════════
# wooz — Exploitative LAG
# ═══════════════════════════════════════════════════════════════

class ExploitativeLAG(BaseStrategy):
    """wooz — 상대 약점을 파고드는 공격형

    헤즈업: BTN(SB) 프리플롭 거의 모든 핸드 참여
    멀티웨이: 포지션별 타이트 레인지 + 밸류 위주
    BB: 넓은 디펜스 + 리스틸
    포스트플롭: 공격적 C-bet + 상대별 조정
    """

    def decide(self, req: ActionRequest, state: GameState | None) -> ActionResponse:
        eff_bb = self._effective_stack_bb(req)

        # 순수 Push/Fold: 10BB 미만만 (Nash 기반)
        if eff_bb < 10 and req.phase == "preflop":
            return self._push_fold(req, eff_bb)

        if req.phase == "preflop":
            if self._is_multiway(req):
                return self._preflop_multiway(req)
            return self._preflop(req)

        # AI 모드: 포스트플롭에서 claude 판단 시도
        ai_decision = self._try_ai_decision(req)
        if ai_decision is not None:
            return ai_decision

        if self._is_multiway(req):
            return self._multiway_postflop(req, aggression="aggressive")
        return self._postflop(req)

    def _push_fold(self, req: ActionRequest, eff_bb: float) -> ActionResponse:
        """Nash 균형 기반 푸시/폴드 (10BB 미만)"""
        is_btn = self._is_btn(req)

        # BB: 상대 올인에 대한 콜 (equity 기반)
        if not is_btn and req.to_call > 0:
            eq = lookup_preflop_equity(req.pocket_cards)
            pot_odds = self._pot_odds(req)
            if is_in_push_range(req.pocket_cards, eff_bb, is_btn=False) and eq > pot_odds:
                return self._allin() if req.to_call >= req.my_stack * 0.5 else self._call()
            return self._fold()

        # BTN: Nash 푸시 레인지
        if is_btn:
            if is_in_push_range(req.pocket_cards, eff_bb, is_btn=True):
                return self._allin()
            return self._fold()

        return self._check()

    # ── 멀티웨이 프리플롭 ──

    def _preflop_multiway(self, req: ActionRequest) -> ActionResponse:
        """멀티웨이 프리플롭 — 포지션별 오픈 레인지 축소"""
        tier = preflop_tier(req.pocket_cards)
        bb = self._bb(req)
        raises = self._phase_raises(req)
        pos_cat = self._position_category(req)
        max_tier = self._multiway_open_tier(req)
        num_players = self._num_players_total(req)

        # 오픈 레이즈 (아직 아무도 레이즈 안 했을 때)
        if raises == 0:
            if tier <= max_tier:
                # 사이즈: 2.5BB + 0.5BB per limper (멀티웨이 표준)
                limpers = sum(
                    1 for a in req.action_history
                    if a.phase == "preflop" and a.action == "call"
                )
                raise_size = int(bb * (2.5 + 0.5 * limpers))

                # EP: 프리미엄만, 큰 사이즈
                if pos_cat == "EP":
                    if tier <= 2:
                        return self._safe_raise(bb * 3, req)
                    if tier <= 3:
                        return self._safe_raise(int(bb * 2.5), req)
                    return self._fold()

                # MP: 보통 레인지
                if pos_cat == "MP":
                    if tier <= 2:
                        return self._safe_raise(bb * 3, req)
                    if tier <= 4:
                        return self._safe_raise(raise_size, req)
                    return self._fold()

                # LP (CO/BTN): 넓은 레인지, 스틸 포함
                if pos_cat == "LP":
                    if tier <= 2:
                        return self._safe_raise(bb * 3, req)
                    if tier <= 5:
                        return self._safe_raise(raise_size, req)
                    if tier <= 6:
                        # CO/BTN 스틸: 남은 플레이어 수에 따라 빈도 조절
                        steal_prob = 0.60 if self._players_yet_to_act(req) <= 3 else 0.30
                        if random.random() < steal_prob:
                            return self._safe_raise(int(bb * 2.2), req)
                    return self._fold()

                # BLIND (SB): 스퀴즈 기회 또는 콤플릿
                if pos_cat == "BLIND":
                    if self._is_sb(req):
                        if tier <= 4:
                            return self._safe_raise(raise_size, req)
                        # SB 콤플릿 (멀티웨이에선 폴드 > 콤플릿)
                        return self._fold()
                    # BB check
                    return self._check()

                return self._safe_raise(raise_size, req) if tier <= max_tier else self._fold()
            return self._check_or_fold(req)

        # 이미 레이즈가 있을 때 — 콜/3벳/폴드
        if raises >= 1:
            aggressor = self._last_aggressor(req)
            agg_pos = None
            for a in reversed(req.action_history):
                if a.phase == "preflop" and a.action == "raise":
                    for p in req.players:
                        if p.name == a.player:
                            agg_pos = p.position
                            break
                    break
            agg_cat = POSITION_CATEGORY.get(agg_pos, "MP") if agg_pos else "MP"

            # EP 레이즈에 대한 대응 (강한 레인지로 추정)
            if agg_cat == "EP":
                if tier <= 2:
                    return self._safe_raise(int(req.min_raise * 2.5), req)
                if tier <= 3:
                    return self._call()
                return self._fold()

            # MP 레이즈
            if agg_cat == "MP":
                if tier <= 2:
                    return self._safe_raise(int(req.min_raise * 2.5), req)
                if tier <= 4:
                    return self._call()
                # LP에서 콜 가능 (implied odds)
                if pos_cat == "LP" and tier <= 5 and req.to_call <= bb * 4:
                    return self._call()
                return self._fold()

            # LP 레이즈 (넓은 레인지 → 3벳 기회)
            if tier <= 2:
                return self._safe_raise(int(req.min_raise * 3), req)
            if tier <= 3:
                # 3벳 블러프 (상대 LP 오픈이 넓을 때)
                if random.random() < 0.30:
                    return self._safe_raise(req.min_raise, req)
                return self._call()
            if tier <= 5:
                if req.to_call <= bb * 4:
                    return self._call()
                return self._fold()
            return self._fold()

        return self._check_or_fold(req)

    # ── 헤즈업 프리플롭 (기존) ──

    def _preflop(self, req: ActionRequest) -> ActionResponse:
        tier = preflop_tier(req.pocket_cards)
        bb = self._bb(req)
        raises = self._phase_raises(req)
        is_btn = self._is_btn(req)

        # ── BTN (SB) — 오픈 레이즈 (적응형 스틸 빈도) ──
        if is_btn and raises == 0:
            bb_profile = None
            for p in req.players:
                if p.position == "bb":
                    bb_profile = self.profiler.get_stats(req.game_id, p.name)
            bb_fold_rate = bb_profile.fold_rate if bb_profile and bb_profile.hands_seen >= 5 else 0.4
            bb_type = bb_profile.effective_type if bb_profile and bb_profile.hands_seen >= 5 else PlayerType.UNKNOWN
            adapt = self._adaptive()

            # TAG BB: tier 5+ 대부분 폴드 → 스틸 빈도 대폭 상향
            if bb_type == PlayerType.TAG:
                if tier <= 2:
                    return self._safe_raise(bb * 3, req)
                if tier <= 5:
                    return self._safe_raise(int(bb * 2.5), req)
                if tier <= 7:
                    # TAG는 프리미엄만 3벳 → 민레이즈 스틸 매우 효율적
                    return self._safe_raise(bb * 2, req) if random.random() < 0.92 else self._fold()
                # 티어 8: TAG BB 폴드율 높으므로 여전히 스틸 시도
                return self._safe_raise(bb * 2, req) if random.random() < 0.60 else self._fold()

            if tier <= 2:
                return self._safe_raise(bb * 3, req)
            if tier <= 5:
                return self._safe_raise(int(bb * 2.5), req)
            if tier <= 7:
                steal_base = 0.8 if bb_fold_rate > 0.5 else 0.55
                steal_prob = min(0.95, steal_base * adapt.steal_freq / 0.70)
                return self._safe_raise(bb * 2, req) if random.random() < steal_prob else self._fold()
            steal_base = 0.5 if bb_fold_rate > 0.5 else 0.2
            steal_prob = min(0.70, steal_base * adapt.steal_freq / 0.70)
            return self._safe_raise(bb * 2, req) if random.random() < steal_prob else self._fold()

        # ── BB — 상대 레이즈 대응 ──
        if self._is_bb(req) and raises >= 1:
            aggressor = self._last_aggressor(req)
            opp_vpip = aggressor.vpip if aggressor and aggressor.hands_seen >= 5 else 0.5
            opp_type = aggressor.effective_type if aggressor and aggressor.hands_seen >= 5 else PlayerType.UNKNOWN
            is_loose = opp_vpip > 0.55

            # TAG BTN 오픈: 좁은 레인지 (tier 1-4) → 넓은 디펜스 + 3벳 확대
            if opp_type == PlayerType.TAG:
                if tier <= 2:
                    return self._safe_raise(int(req.min_raise * 3), req)
                # TAG 오픈 레인지가 좁으므로 3벳으로 폴드 유도 (TAG는 프리미엄만 콜)
                if tier <= 3:
                    if random.random() < 0.55:
                        return self._safe_raise(req.min_raise, req)
                    return self._call()
                # tier 4-5: TAG 오픈에 넓게 콜 (포스트플롭에서 착취)
                if tier <= 5:
                    return self._call()
                # tier 6-7: TAG 오픈은 좁지만 우리가 포지셔널 디스어드밴티지
                # → 가끔 콜 (포스트플롭에서 TAG가 체크하면 스틸)
                if tier <= 7:
                    if req.to_call <= bb * 3:
                        return self._call() if random.random() < 0.55 else self._fold()
                    return self._fold()
                return self._fold()

            if tier <= 2:
                return self._safe_raise(int(req.min_raise * 3), req)
            if tier <= 3:
                if is_loose and random.random() < 0.45:
                    return self._safe_raise(req.min_raise, req)
                return self._call()
            if tier <= 5:
                if req.to_call <= bb * 4:
                    return self._call()
                return self._fold()
            if tier <= 7:
                if req.to_call <= bb * 3:
                    return self._call() if random.random() < 0.50 else self._fold()
                return self._fold()
            if req.to_call <= bb:
                return self._call() if random.random() < 0.3 else self._fold()
            return self._fold()

        # BTN 3벳에 대한 대응
        if is_btn and raises >= 1:
            aggressor = self._last_aggressor(req)
            agg_type = aggressor.effective_type if aggressor else PlayerType.UNKNOWN

            if tier <= 2:
                return self._safe_raise(int(req.min_raise * 2.5), req)
            if tier <= 4:
                if agg_type == PlayerType.TAG and tier >= 4:
                    return self._fold()
                return self._call()
            return self._fold()

        return self._check_or_fold(req)

    # ── 헤즈업 포스트플롭 (기존) ──

    def _postflop(self, req: ActionRequest) -> ActionResponse:
        """equity 기반 포스트플롭 — 레인지 추정 + 적응형 + IP/OOP + GTO 블러프"""
        num_opp = max(1, self._active_count(req) - 1)
        equity = calc_equity(req.pocket_cards, req.community_cards,
                             num_opponents=num_opp, simulations=800)

        spr = self._spr(req)
        pot_odds = self._pot_odds(req)
        ip = self._is_ip(req)
        is_river = req.phase == "river"
        adapt = self._adaptive()

        # 상대 프로파일 + 레인지 추정
        opp = self._last_aggressor(req) or self._opponent_profile(req)
        opp_type = opp.effective_type if opp and opp.hands_seen >= 5 else PlayerType.UNKNOWN
        is_maniac = (opp and opp.hands_seen >= 5
                     and opp.vpip > 0.85 and opp.fold_rate < 0.15)
        opp_aggressive = is_maniac or opp_type == PlayerType.LAG
        is_calling_station = (opp and opp.hands_seen >= 5
                              and opp.vpip > 0.60 and opp.af < 1.0)

        # 틸트/전략전환 감지 → 착취 강화
        is_tilting = opp.is_tilting if opp and opp.hands_seen >= 15 else False
        style_shifted = opp.style_shift if opp and opp.hands_seen >= 10 else False

        # TAG/TAP 전용: 포스트플롭 착취 분기
        is_tag = opp_type in (PlayerType.TAG, PlayerType.TAP)

        # 레인지 추정: 상대가 벳/레이즈했으면 레인지 축소 → equity 보정
        opp_range = self._estimate_opp_range(req)
        range_top, range_pol = opp_range.get_range()
        opp_strength = opp_range.get_opponent_strength_estimate()

        # 틸트 상대 착취: 틸트 시 VPIP 급증 → 약한 핸드로 참여 → 밸류벳 강화
        if is_tilting:
            equity *= 1.10  # 상대 레인지 약화 → 우리 equity 상향

        # TAG가 벳했을 때: 레인지가 매우 좁음 (strength >= 0.7) → 더 큰 equity 하향
        if req.to_call > 0 and is_tag:
            equity *= 0.85  # TAG 벳 = 거의 밸류 → 우리 equity 15% 하향
        elif req.to_call > 0 and range_top < 0.30:
            equity *= 0.90
        elif req.to_call > 0 and range_pol > 0.6:
            equity *= 0.95

        # TAG 체크 감지: 이번 스트리트에서 상대가 체크했는지
        tag_checked_this_street = False
        if is_tag and ip:
            for a in req.action_history:
                if a.phase == req.phase and a.action == "check":
                    # 상대의 체크인지 확인 (내 이름 아닌 사람)
                    my_name = None
                    for p in req.players:
                        if p.position == req.seat:
                            my_name = p.name
                    if a.player != my_name:
                        tag_checked_this_street = True

        # ── 넛급 (equity 80%+) ──
        if equity >= 0.80:
            if req.to_call > 0:
                if spr < 3:
                    return self._allin()
                return self._safe_raise(int(req.min_raise * 2), req)
            if opp_aggressive and not ip and random.random() < 0.25:
                return self._check()
            size = self._bet_size_for_position(req, req.phase, 0.6, 0.85)
            return self._safe_raise(size, req)

        # ── 강한 핸드 (equity 60-80%) ──
        if equity >= 0.60:
            if req.to_call > 0:
                if is_maniac:
                    return self._safe_raise(req.min_raise, req)
                # TAG 벳 = 밸류 → 콜하되 레이즈는 자제
                return self._call()
            if self._can_check(req):
                if is_calling_station:
                    size = self._bet_size_for_position(req, req.phase, 0.55, 0.75)
                    return self._safe_raise(size, req)
                # TAG 체크 후 IP → 밸류벳 (TAG는 체크하면 약함)
                if is_tag and tag_checked_this_street:
                    size = self._bet_size_for_position(req, req.phase, 0.55, 0.70)
                    return self._safe_raise(size, req)
                if not ip and random.random() < 0.15:
                    return self._check()
                size = self._bet_size_for_position(req, req.phase, 0.45, 0.65)
                return self._safe_raise(size, req)
            return self._call()

        # ── 중간 핸드 (equity 40-60%) — 핵심 구간 ──
        if equity >= 0.40:
            if self._can_check(req):
                if is_calling_station:
                    size = self._bet_size_for_position(req, req.phase, 0.45, 0.60)
                    return self._safe_raise(size, req)
                if is_maniac:
                    return self._check()
                # TAG 착취: 체크했으면 프로빙 벳 (TAG는 약한 핸드로 체크 → 폴드)
                if is_tag and tag_checked_this_street:
                    if random.random() < 0.75:
                        size = self._bet_size_for_position(req, req.phase, 0.40, 0.55)
                        return self._safe_raise(size, req)
                    return self._check()
                # TAG OOP: 플롭/턴 벳으로 공격 (TAG가 미들 핸드 폴드)
                if is_tag and not ip:
                    if random.random() < 0.45:
                        size = self._bet_size_for_position(req, req.phase, 0.45, 0.60)
                        return self._safe_raise(size, req)
                    return self._check()
                if opp_aggressive:
                    if random.random() < 0.60:
                        size = self._bet_size_for_position(req, req.phase, 0.45, 0.60)
                        return self._safe_raise(size, req)
                    return self._check()
                elif ip:
                    if random.random() < 0.65:
                        size = self._bet_size_for_position(req, req.phase, 0.33, 0.50)
                        return self._safe_raise(size, req)
                    return self._check()
                else:
                    if random.random() < 0.30:
                        size = self._bet_size_for_position(req, req.phase, 0.45, 0.55)
                        return self._safe_raise(size, req)
                    return self._check()
            # TAG 벳에 대한 콜: 타이트하게 (TAG 벳 = strength >= 0.7)
            bet_pct = req.to_call / max(1, req.pot - req.to_call)
            if is_maniac:
                if pot_odds < equity + 0.15:
                    return self._call()
            elif is_tag:
                # TAG 벳 = 강한 핸드 → 팟오즈보다 보수적으로 콜
                if pot_odds < equity * 0.90:
                    return self._call()
                return self._fold()
            elif opp_aggressive:
                bonus = 0.08 if bet_pct > 0.7 else 0.12
                if pot_odds < equity + bonus:
                    return self._call()
            elif pot_odds < equity:
                return self._call()
            return self._fold()

        # ── 약한 핸드 (equity 25-40%) ──
        if equity >= 0.25:
            if self._can_check(req):
                # TAG 체크 후 IP → 프로빙 벳으로 스틸 (핵심 착취)
                if is_tag and tag_checked_this_street:
                    if random.random() < 0.55:
                        size = self._bet_size_for_position(req, req.phase, 0.40, 0.55)
                        return self._safe_raise(size, req)
                    return self._check()
                # TAG OOP: 가끔 리드벳으로 폴드 유도
                if is_tag and not ip and random.random() < 0.20:
                    size = self._bet_size_for_position(req, req.phase, 0.50, 0.65)
                    return self._safe_raise(size, req)
                return self._check()
            # TAG 벳에 대한 콜: 매우 타이트 (TAG 벳 = 진짜 강함)
            bet_pct = req.to_call / max(1, req.pot - req.to_call)
            if is_maniac:
                if pot_odds < equity * 1.15:
                    return self._call()
            elif is_tag:
                # TAG 벳 = 거의 넛급 → 아주 좋은 팟오즈에서만 콜
                if pot_odds < equity * 0.70:
                    return self._call()
                return self._fold()
            elif opp_aggressive:
                mult = 0.95 if bet_pct > 0.7 else 1.05
                if pot_odds < equity * mult:
                    return self._call()
            elif pot_odds < equity * 0.80:
                return self._call()
            return self._fold()

        # ── 쓰레기 (equity < 25%) ──
        if self._can_check(req):
            if is_calling_station or is_maniac:
                return self._check()
            # TAG 체크 후 IP → 블러프 벳 (TAG는 약하면 폴드)
            if is_tag and tag_checked_this_street:
                bluff_prob = 0.40 if req.phase in ("flop", "turn") else 0.30
                if random.random() < bluff_prob:
                    size = self._bet_size_for_position(req, req.phase, 0.35, 0.50)
                    return self._safe_raise(size, req)
                return self._check()
            if is_river:
                bluff_size_ratio = 0.67
                bluff_freq = self._gto_river_bluff_freq(req, bluff_size_ratio)
                if random.random() < bluff_freq:
                    size = max(int(req.pot * bluff_size_ratio), req.min_raise)
                    return self._safe_raise(size, req)
            elif ip and is_tag and random.random() < 0.25:
                # TAG OOP 체크: 넓은 블러프 빈도
                size = self._bet_size_for_position(req, req.phase, 0.35, 0.45)
                return self._safe_raise(size, req)
            elif ip and opp_type in (PlayerType.TAG, PlayerType.TAP) and random.random() < 0.18:
                size = self._bet_size_for_position(req, req.phase, 0.35, 0.45)
                return self._safe_raise(size, req)
            return self._check()
        # TAG 벳 = 진짜 강함 → 쓰레기로 콜하지 않음
        if is_tag:
            return self._fold()
        if opp_aggressive and equity > 0.15 and pot_odds < 0.25:
            return self._call()
        return self._fold()


# ═══════════════════════════════════════════════════════════════
# hugo — Adaptive TAG
# ═══════════════════════════════════════════════════════════════

class AdaptiveTAG(BaseStrategy):
    """hugo — GTO 기반 + 상대 적응

    헤즈업: BTN 넓은 오픈, BB 적극 디펜스
    멀티웨이: 타이트 레인지 + 수학적 판단
    포스트플롭: 팟오즈 기반 수학적 판단
    밸류:블러프 ≈ 2:1
    """

    def decide(self, req: ActionRequest, state: GameState | None) -> ActionResponse:
        eff_bb = self._effective_stack_bb(req)

        # 순수 Push/Fold: 10BB 미만만 (Nash 기반)
        if eff_bb < 10 and req.phase == "preflop":
            return self._push_fold(req, eff_bb)

        if req.phase == "preflop":
            if self._is_multiway(req):
                return self._preflop_multiway(req)
            return self._preflop(req)

        # AI 모드: 포스트플롭에서 claude 판단 시도
        ai_decision = self._try_ai_decision(req)
        if ai_decision is not None:
            return ai_decision

        if self._is_multiway(req):
            return self._multiway_postflop(req, aggression="normal")
        return self._postflop(req)

    def _push_fold(self, req: ActionRequest, eff_bb: float) -> ActionResponse:
        """Nash 균형 기반 푸시/폴드 (10BB 미만)"""
        is_btn = self._is_btn(req)

        if not is_btn and req.to_call > 0:
            eq = lookup_preflop_equity(req.pocket_cards)
            pot_odds = self._pot_odds(req)
            if is_in_push_range(req.pocket_cards, eff_bb, is_btn=False) and eq > pot_odds:
                return self._allin() if req.to_call >= req.my_stack * 0.5 else self._call()
            return self._fold()

        if is_btn:
            if is_in_push_range(req.pocket_cards, eff_bb, is_btn=True):
                return self._allin()
            return self._fold()

        return self._check()

    # ── 멀티웨이 프리플롭 ──

    def _preflop_multiway(self, req: ActionRequest) -> ActionResponse:
        """멀티웨이 프리플롭 — hugo는 wooz보다 1단계 타이트"""
        tier = preflop_tier(req.pocket_cards)
        bb = self._bb(req)
        raises = self._phase_raises(req)
        pos_cat = self._position_category(req)
        max_tier = max(1, self._multiway_open_tier(req) - 1)  # wooz보다 1단계 타이트

        if raises == 0:
            limpers = sum(
                1 for a in req.action_history
                if a.phase == "preflop" and a.action == "call"
            )
            raise_size = int(bb * (2.5 + 0.5 * limpers))

            if pos_cat == "EP":
                if tier <= 2:
                    return self._safe_raise(bb * 3, req)
                return self._fold()

            if pos_cat == "MP":
                if tier <= 2:
                    return self._safe_raise(bb * 3, req)
                if tier <= 3:
                    return self._safe_raise(raise_size, req)
                return self._fold()

            if pos_cat == "LP":
                if tier <= 2:
                    return self._safe_raise(bb * 3, req)
                if tier <= 4:
                    return self._safe_raise(raise_size, req)
                if tier <= 5:
                    steal_prob = 0.45 if self._players_yet_to_act(req) <= 3 else 0.20
                    if random.random() < steal_prob:
                        return self._safe_raise(int(bb * 2.2), req)
                return self._fold()

            if pos_cat == "BLIND":
                if self._is_sb(req):
                    if tier <= 3:
                        return self._safe_raise(raise_size, req)
                    return self._fold()
                return self._check()

            return self._safe_raise(raise_size, req) if tier <= max_tier else self._fold()

        # 이미 레이즈가 있을 때
        if raises >= 1:
            aggressor = self._last_aggressor(req)
            agg_pos = None
            for a in reversed(req.action_history):
                if a.phase == "preflop" and a.action == "raise":
                    for p in req.players:
                        if p.name == a.player:
                            agg_pos = p.position
                            break
                    break
            agg_cat = POSITION_CATEGORY.get(agg_pos, "MP") if agg_pos else "MP"

            # EP 레이즈 대응 (매우 강한 레인지)
            if agg_cat == "EP":
                if tier <= 1:
                    return self._safe_raise(int(req.min_raise * 2.5), req)
                if tier <= 2:
                    return self._call()
                return self._fold()

            # MP 레이즈
            if agg_cat == "MP":
                if tier <= 2:
                    return self._safe_raise(int(req.min_raise * 2.5), req)
                if tier <= 3:
                    return self._call()
                if pos_cat == "LP" and tier <= 4 and req.to_call <= bb * 4:
                    return self._call()
                return self._fold()

            # LP 레이즈
            if tier <= 2:
                return self._safe_raise(int(req.min_raise * 3), req)
            if tier <= 3:
                return self._call()
            if tier <= 4 and req.to_call <= bb * 4:
                return self._call()
            return self._fold()

        return self._check_or_fold(req)

    # ── 헤즈업 프리플롭 (기존) ──

    def _preflop(self, req: ActionRequest) -> ActionResponse:
        tier = preflop_tier(req.pocket_cards)
        bb = self._bb(req)
        raises = self._phase_raises(req)
        is_btn = self._is_btn(req)

        # ── BTN 오픈 ──
        if is_btn and raises == 0:
            if tier <= 2:
                return self._safe_raise(bb * 3, req)
            if tier <= 4:
                return self._safe_raise(int(bb * 2.5), req)
            if tier <= 6:
                return self._safe_raise(bb * 2, req)
            if random.random() < 0.35:
                return self._safe_raise(bb * 2, req)
            return self._fold()

        # ── BB 디펜스 ──
        if self._is_bb(req) and raises >= 1:
            aggressor = self._last_aggressor(req)
            opp_vpip = aggressor.vpip if aggressor and aggressor.hands_seen >= 5 else 0.5

            if tier <= 1:
                return self._safe_raise(int(req.min_raise * 3), req)
            if tier == 2:
                if opp_vpip > 0.5:
                    return self._safe_raise(req.min_raise, req) if random.random() < 0.6 else self._call()
                return self._call()
            if tier <= 4:
                if req.to_call <= bb * 4:
                    return self._call()
                return self._fold()
            if tier <= 6:
                defend_threshold = bb * 4 if opp_vpip > 0.45 else bb * 3
                if req.to_call <= defend_threshold:
                    return self._call()
                if opp_vpip > 0.5 and random.random() < 0.2:
                    return self._safe_raise(req.min_raise, req)
                return self._fold()
            if tier == 7:
                if req.to_call <= bb * 2:
                    return self._call() if random.random() < 0.45 else self._fold()
                return self._fold()
            if req.to_call <= bb and random.random() < 0.2:
                return self._call()
            return self._fold()

        # BTN vs 3벳
        if is_btn and raises >= 1:
            if tier <= 2:
                return self._safe_raise(int(req.min_raise * 2.5), req)
            if tier <= 3:
                return self._call()
            if tier == 4 and req.to_call <= bb * 6:
                return self._call()
            return self._fold()

        return self._check_or_fold(req)

    # ── 헤즈업 포스트플롭 (기존) ──

    def _postflop(self, req: ActionRequest) -> ActionResponse:
        """equity 기반 포스트플롭 — GTO + 레인지 추정 + 적응형 + IP/OOP"""
        num_opp = max(1, self._active_count(req) - 1)
        equity = calc_equity(req.pocket_cards, req.community_cards,
                             num_opponents=num_opp, simulations=800)

        spr = self._spr(req)
        pot_odds = self._pot_odds(req)
        ip = self._is_ip(req)
        is_river = req.phase == "river"

        opp = self._last_aggressor(req) or self._opponent_profile(req)
        opp_type = opp.effective_type if opp and opp.hands_seen >= 5 else PlayerType.UNKNOWN
        is_maniac = (opp and opp.hands_seen >= 5
                     and opp.vpip > 0.85 and opp.fold_rate < 0.15)
        opp_aggressive = is_maniac or opp_type == PlayerType.LAG
        is_calling_station = (opp and opp.hands_seen >= 5
                              and opp.vpip > 0.60 and opp.af < 1.0)

        opp_range = self._estimate_opp_range(req)
        range_top, range_pol = opp_range.get_range()
        if req.to_call > 0 and range_top < 0.30:
            equity *= 0.90
        elif req.to_call > 0 and range_pol > 0.6:
            equity *= 0.95

        # ── 넛급 (80%+) ──
        if equity >= 0.80:
            if req.to_call > 0:
                if spr < 3:
                    return self._allin()
                return self._safe_raise(req.min_raise, req) if random.random() < 0.6 else self._call()
            if opp_aggressive and not ip and random.random() < 0.20:
                return self._check()
            size = self._bet_size_for_position(req, req.phase, 0.55, 0.75)
            return self._safe_raise(size, req)

        # ── 강한 (60-80%) ──
        if equity >= 0.60:
            if req.to_call > 0:
                return self._call()
            if self._can_check(req):
                if is_calling_station:
                    size = self._bet_size_for_position(req, req.phase, 0.55, 0.70)
                    return self._safe_raise(size, req)
                if not ip and random.random() < 0.10:
                    return self._check()
                if random.random() < 0.60:
                    size = self._bet_size_for_position(req, req.phase, 0.45, 0.6)
                    return self._safe_raise(size, req)
                return self._check()
            return self._call()

        # ── 중간 (40-60%) ──
        if equity >= 0.40:
            if self._can_check(req):
                if is_calling_station:
                    size = self._bet_size_for_position(req, req.phase, 0.40, 0.55)
                    return self._safe_raise(size, req)
                if opp_aggressive and random.random() < 0.55:
                    size = self._bet_size_for_position(req, req.phase, 0.40, 0.55)
                    return self._safe_raise(size, req)
                elif ip:
                    if random.random() < 0.55:
                        size = self._bet_size_for_position(req, req.phase, 0.33, 0.50)
                        return self._safe_raise(size, req)
                    return self._check()
                else:
                    if random.random() < 0.30:
                        size = self._bet_size_for_position(req, req.phase, 0.45, 0.55)
                        return self._safe_raise(size, req)
                    return self._check()
            if opp_aggressive and pot_odds < equity + 0.10:
                return self._call()
            elif pot_odds < equity:
                return self._call()
            return self._fold()

        # ── 약한 (25-40%) ──
        if equity >= 0.25:
            if self._can_check(req):
                if opp_type not in (PlayerType.LAP,) and random.random() < 0.15:
                    size = self._bet_size_for_position(req, req.phase, 0.40, 0.50)
                    return self._safe_raise(size, req)
                return self._check()
            if opp_aggressive and pot_odds < equity * 1.0:
                return self._call()
            elif pot_odds < equity * 0.85:
                return self._call()
            return self._fold()

        # ── 쓰레기 (<25%) — GTO 리버 블러프 ──
        if self._can_check(req):
            if is_calling_station:
                return self._check()
            if is_river:
                bluff_size_ratio = 0.67
                bluff_freq = self._gto_river_bluff_freq(req, bluff_size_ratio) * 0.8
                if random.random() < bluff_freq:
                    size = max(int(req.pot * bluff_size_ratio), req.min_raise)
                    return self._safe_raise(size, req)
            return self._check()
        if opp_aggressive and equity > 0.15 and pot_odds < 0.25:
            return self._call()
        return self._fold()
