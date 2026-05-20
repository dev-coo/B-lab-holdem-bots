"""실시간 상대 트래커.

세션 시작 시 빈 상태. 게임 진행하며 상대들의 액션을 누적 관찰해 stat을 갱신.
충분한 표본(MIN_SAMPLE)이 쌓인 상대만 archetype 분류 → exploit 레이어가 사용.

핵심 stat
  - vpip / pfr / 3bet / fold_to_3bet
  - cbet (프리플랍 레이저로 플랍 베팅)
  - postflop_af (포스트 (raise+allin) / call 비율)
  - wtsd (saw_flop → showdown 비율)

archetype 분류
  - station   : VPIP > 32, PFR < 8, AF < 1.5
  - nit       : VPIP < 15, PFR <= VPIP
  - lag       : VPIP > 30, PFR > 22, AF > 3
  - tag       : VPIP 14~28, PFR 11~24
  - passive   : AF < 1.5 (위 분류 무관 추가 태그 가능)
  - stubborn  : fold_to_3bet < 25 (추가 태그)
  - 그 외      : "unknown" (표본 미만 or 분류 안 됨)

크래시 대응 — 30초마다 data/session_tracker.json 에 자동 스냅샷.
시즌 리셋: 그 파일을 지우거나 OpponentTracker.reset() 호출.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

MIN_SAMPLE = 30  # archetype 분류에 필요한 최소 핸드 수
SNAPSHOT_PATH = Path(__file__).parent.parent / "data" / "session_tracker.json"
SNAPSHOT_INTERVAL = 30.0  # 초


def _new_player_state() -> dict:
    return {
        "hands": 0,
        "vpip_opp": 0, "vpip": 0,
        "pfr_opp": 0, "pfr": 0,
        "threebet_opp": 0, "threebet": 0,
        "f3b_opp": 0, "f3b": 0,
        "cbet_opp": 0, "cbet": 0,
        "saw_flop": 0, "showdown": 0,
        "post_bets_raises": 0, "post_calls": 0,
    }


class OpponentTracker:
    """게임 중 상대 액션을 실시간 누적."""

    def __init__(self, snapshot_path: Path | None = SNAPSHOT_PATH, reset: bool = False):
        self.players: dict[str, dict] = defaultdict(_new_player_state)
        # 핸드 단위 임시 상태 — room_id → hand_state
        self._cur_hand: dict = {}
        self._snapshot_path = snapshot_path
        self._last_snapshot = time.time()
        if reset:
            # 대회 시작시 누적 데이터 wipe — 외부 봇 모집단이 다르므로 기존 통계 무효
            if self._snapshot_path and self._snapshot_path.exists():
                try:
                    self._snapshot_path.unlink()
                except OSError:
                    pass
        else:
            self._load_snapshot()

    # ────────────── 시즌 / 영속성 ──────────────
    def reset(self) -> None:
        self.players.clear()
        self._cur_hand.clear()
        if self._snapshot_path and self._snapshot_path.exists():
            self._snapshot_path.unlink()

    def _load_snapshot(self) -> None:
        if not self._snapshot_path or not self._snapshot_path.exists():
            return
        try:
            with self._snapshot_path.open(encoding="utf-8") as f:
                data = json.load(f)
            for name, state in data.items():
                self.players[name] = {**_new_player_state(), **state}
        except (json.JSONDecodeError, OSError):
            pass

    def _maybe_snapshot(self) -> None:
        now = time.time()
        if now - self._last_snapshot < SNAPSHOT_INTERVAL or not self._snapshot_path:
            return
        try:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._snapshot_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(dict(self.players), f, ensure_ascii=False)
            tmp.replace(self._snapshot_path)
            self._last_snapshot = now
        except OSError:
            pass

    # ────────────── 이벤트 흡수 ──────────────
    def observe(self, msg: dict) -> None:
        """WS에서 받은 모든 메시지를 통과시키면 됨. 자기 분류해 처리."""
        t = msg.get("type")
        room_id = msg.get("room_id")

        if t == "hand_start":
            self._begin_hand(room_id, msg)
        elif t == "action_performed":
            self._record_action(room_id, msg)
        elif t == "phase_change":
            h = self._cur_hand.get(room_id)
            if h is not None:
                h["phase"] = msg.get("phase", h["phase"])
        elif t == "hand_result":
            self._end_hand(room_id, msg)

        self._maybe_snapshot()

    # ────────────── 핸드 라이프사이클 ──────────────
    def _begin_hand(self, room_id, msg: dict) -> None:
        seat_of = {p["name"]: p.get("position", "") for p in msg.get("players", [])}
        self._cur_hand[room_id] = {
            "phase": "preflop",
            "seat_of": seat_of,
            "active": set(seat_of.keys()),
            "preflop_actions": [],   # [(player, action)] 순서대로
            "postflop_streets": defaultdict(lambda: []),  # phase → [(player, action)]
            "first_raiser": None,    # 프리플랍 첫 레이저
            "saw_flop": set(),
        }

    def _record_action(self, room_id, msg: dict) -> None:
        h = self._cur_hand.get(room_id)
        if h is None:
            return
        player = msg.get("player")
        action = msg.get("action")
        if not player or not action:
            return
        phase = h["phase"]
        if phase == "preflop":
            h["preflop_actions"].append((player, action))
            if action in ("raise", "allin") and h["first_raiser"] is None:
                h["first_raiser"] = player
        else:
            h["postflop_streets"][phase].append((player, action))

    def _end_hand(self, room_id, msg: dict) -> None:
        h = self._cur_hand.pop(room_id, None)
        if h is None:
            return

        # 플랍 발생 여부 — 권위 데이터: hand_result.community_cards
        community = msg.get("community_cards", [])
        had_flop = len(community) >= 3

        # 각 플레이어의 프리플랍 액션 모음
        per_player_pre: dict[str, list[str]] = defaultdict(list)
        for p, a in h["preflop_actions"]:
            per_player_pre[p].append(a)

        # 프리플랍 레이즈 순서
        raise_seq = [p for p, a in h["preflop_actions"] if a in ("raise", "allin")]

        # 쇼다운 / saw_flop
        showdown_set = {s["name"] for s in msg.get("showdown", [])}
        if had_flop:
            for p in h["active"]:
                if "fold" not in per_player_pre.get(p, []):
                    h["saw_flop"].add(p)

        # 각 플레이어 stat 갱신
        for player in h["active"]:
            s = self.players[player]
            s["hands"] += 1

            actions = per_player_pre.get(player, [])

            # VPIP
            s["vpip_opp"] += 1
            if any(a in ("call", "raise", "allin") for a in actions):
                s["vpip"] += 1
            # PFR
            s["pfr_opp"] += 1
            if any(a in ("raise", "allin") for a in actions):
                s["pfr"] += 1

            # 3bet — 레이즈 순서 2번째 이후로 이 플레이어가 등장하면 3벳
            if len(raise_seq) >= 1 and raise_seq[0] != player:
                s["threebet_opp"] += 1
            for idx, p in enumerate(raise_seq):
                if idx >= 1 and p == player:
                    s["threebet"] += 1
                    break

            # Fold to 3bet — 내가 첫 레이저인데 3벳 등장 후 fold
            if raise_seq and raise_seq[0] == player and len(raise_seq) >= 2:
                s["f3b_opp"] += 1
                first_raise_done = False
                faced = False
                for a in actions:
                    if a in ("raise", "allin") and not first_raise_done:
                        first_raise_done = True
                        continue
                    if first_raise_done and not faced:
                        if a == "fold":
                            s["f3b"] += 1
                        if a in ("fold", "call", "raise", "allin"):
                            faced = True
                            break

            # C-bet — 첫 레이저 + 플랍 봤으면 기회
            if raise_seq and raise_seq[0] == player and player in h["saw_flop"]:
                s["cbet_opp"] += 1
                flop_actions = [a for p, a in h["postflop_streets"]["flop"] if p == player]
                if flop_actions and flop_actions[0] in ("raise", "allin"):
                    s["cbet"] += 1

            # 포스트플랍 aggression
            for street in ("flop", "turn", "river"):
                for p, a in h["postflop_streets"][street]:
                    if p != player:
                        continue
                    if a in ("raise", "allin"):
                        s["post_bets_raises"] += 1
                    elif a == "call":
                        s["post_calls"] += 1

            # saw_flop, showdown
            if player in h["saw_flop"]:
                s["saw_flop"] += 1
            if player in showdown_set:
                s["showdown"] += 1

    # ────────────── 조회 / 분류 ──────────────
    def get_profile(self, player: str) -> dict:
        s = self.players.get(player)
        if not s or s["hands"] < MIN_SAMPLE:
            return {"name": player, "hands": s["hands"] if s else 0, "archetype": "unknown"}

        def pct(num, den):
            return 100 * num / den if den else 0.0

        vpip = pct(s["vpip"], s["vpip_opp"])
        pfr = pct(s["pfr"], s["pfr_opp"])
        threebet = pct(s["threebet"], s["threebet_opp"])
        f3b = pct(s["f3b"], s["f3b_opp"])
        cbet = pct(s["cbet"], s["cbet_opp"])
        wtsd = pct(s["showdown"], s["saw_flop"])
        af = (s["post_bets_raises"] / s["post_calls"]) if s["post_calls"] else float("inf")
        if af == float("inf"):
            af_disp = 99.0  # 표시상 cap
        else:
            af_disp = af

        # archetype 판정
        archetype = "tag"  # default
        if vpip > 32 and pfr < 8 and af < 1.5:
            archetype = "station"
        elif vpip < 15:
            archetype = "nit"
        elif vpip > 30 and pfr > 22 and af > 3:
            archetype = "lag"
        elif 14 <= vpip <= 28 and 11 <= pfr <= 24:
            archetype = "tag"
        else:
            archetype = "loose"

        tags = []
        # 태그는 해당 stat의 표본이 충분할 때만 적용
        if s["post_calls"] + s["post_bets_raises"] >= 20 and af < 1.5:
            tags.append("passive")
        if s["f3b_opp"] >= 10 and f3b < 25:
            tags.append("stubborn")
        if s["saw_flop"] >= 15 and wtsd > 75:
            tags.append("calldown")

        return {
            "name": player,
            "hands": s["hands"],
            "archetype": archetype,
            "tags": tags,
            "vpip": round(vpip, 1),
            "pfr": round(pfr, 1),
            "3bet": round(threebet, 1),
            "f3b": round(f3b, 1),
            "cbet": round(cbet, 1),
            "wtsd": round(wtsd, 1),
            "af": round(af_disp, 2),
        }

    def all_profiles(self) -> list[dict]:
        return [self.get_profile(p) for p in self.players]
