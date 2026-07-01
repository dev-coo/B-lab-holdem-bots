"""세션 요약 작성기.

게임 종료(`game_end`) 시점 또는 강제 플러시 시 `.debug/room_{id}.jsonl` 을 스트리밍
스캔해 해당 `run_id` 범위의 이벤트만 집계하고 `.debug/summary_{id}_{run_id}.json`
에 JSON 을 쓴다. 같은 경로의 `opponent_profiles.json` 도 읽기-병합-쓰기(tmp+rename)
방식으로 누적 갱신.

외부 의존성 없음(stdlib + pydantic 모델은 직접 사용하지 않음 — 파일의 model_dump 된
JSON 만 읽음). 같은 파일에 대한 경합은 단일 프로세스 가정 + `fcntl.flock` 으로 방어.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from holdem_core.core.logging import get_logger
from holdem_core.debug.store import DebugStore, jsonl_writes_enabled
from holdem_core.hand_eval import classify_hand, rank7

logger = get_logger(__name__)

_SCHEMA_VERSION = 1


class SummaryWriter:
    """`.debug/` 아래 세션 요약 + 상대 프로필 누적 관리.

    SQLite 백엔드 (`DebugStore`) 와 기존 JSON 파일 양쪽에 쓴다. JSON 쓰기는
    `HOLDEM_DEBUG_JSONL` 으로 끌 수 있다 (마이그레이션 안전망).
    """

    def __init__(
        self,
        base_dir: Path | str,
        bot_name: str,
        *,
        store: DebugStore | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.bot_name = bot_name
        # room_id -> run_id 마지막으로 시작된 run (flush_pending 용)
        self._last_run: dict[int, str] = {}
        # 외부에서 store 를 넘겨주면 그걸 쓰고, 아니면 우리가 열고 닫는 책임을 진다.
        if store is not None:
            self.store: DebugStore | None = store
            self._owns_store = False
        else:
            try:
                self.store = DebugStore.open(self.base_dir)
                self._owns_store = True
            except Exception as e:  # noqa: BLE001
                logger.warning("summary_store_open_failed", extra={"error": repr(e)})
                self.store = None
                self._owns_store = False

    def close(self) -> None:
        if self.store is not None and self._owns_store:
            try:
                self.store.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("summary_store_close_failed", extra={"error": repr(e)})
        if self._owns_store:
            self.store = None

    def note_run(self, room_id: int, run_id: str) -> None:
        if room_id and run_id:
            self._last_run[room_id] = run_id

    def write(
        self,
        room_id: int,
        run_id: str,
        rankings: list[dict[str, Any]] | None = None,
    ) -> Path:
        """지정된 (room_id, run_id) 범위의 이벤트를 집계해 summary 파일 작성.

        이벤트 소스는 SQLite (`DebugStore`) 가 있으면 그걸, 없으면 기존 JSONL.
        결과는 SQLite 와 JSON 양쪽에 쓴다 (JSON 은 `HOLDEM_DEBUG_JSONL` gate).
        """
        events: list[dict[str, Any]] = []
        if self.store is not None:
            try:
                events = self.store.fetch_events(
                    room_id=room_id, run_id=run_id, include_markers=False
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("summary_store_fetch_failed", extra={"error": repr(e)})
                events = []
        if not events:
            events = list(_stream_events(self.base_dir / f"room_{room_id}.jsonl", run_id))
        summary = _build_summary(
            room_id=room_id,
            run_id=run_id,
            bot_name=self.bot_name,
            events=events,
            rankings=rankings or [],
        )
        if self.store is not None:
            try:
                self.store.upsert_summary(summary)
            except Exception as e:  # noqa: BLE001
                logger.warning("summary_store_upsert_failed", extra={"error": repr(e)})
        out_path = self.base_dir / f"summary_{room_id}_{run_id}.json"
        if jsonl_writes_enabled():
            _atomic_write_json(out_path, summary)
        try:
            self._merge_profiles(summary)
        except Exception:  # noqa: BLE001 — 프로필 병합 실패는 치명적이지 않음
            logger.exception("opponent_profiles_merge_failed")
        return out_path

    def flush_pending(self) -> None:
        """game_end 없이 끊긴 세션들에 대해 마지막 run_id 로 강제 요약 작성."""
        for room_id, run_id in list(self._last_run.items()):
            out_path = self.base_dir / f"summary_{room_id}_{run_id}.json"
            already_present = out_path.exists()
            if not already_present and self.store is not None:
                try:
                    if self.store.get_summary(room_id, run_id, self.bot_name) is not None:
                        already_present = True
                except Exception:  # noqa: BLE001
                    pass
            if already_present:
                continue
            try:
                self.write(room_id, run_id, rankings=[])
            except Exception:  # noqa: BLE001
                logger.exception("summary_flush_failed", extra={"room_id": room_id})

    def _merge_profiles(self, summary: dict[str, Any]) -> None:
        """opponent_profiles.json 을 읽기-병합-쓰기 로 누적 갱신.

        SQLite 백엔드가 있으면 같은 delta 를 `merge_opponent_profile()` 로도 누적.
        JSON 쓰기는 `HOLDEM_DEBUG_JSONL` 으로 끌 수 있지만, 다음 호출에서 누적
        시드 역할을 하므로 가능한 한 유지한다.
        """
        if self.store is not None:
            for name, prof in (summary.get("opponents") or {}).items():
                if not isinstance(prof, dict):
                    continue
                try:
                    self.store.merge_opponent_profile(name, prof)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "store_profile_merge_failed",
                        extra={"error": repr(e), "player": name},
                    )
        if not jsonl_writes_enabled():
            return
        profile_path = self.base_dir / "opponent_profiles.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        current: dict[str, Any] = {}
        if profile_path.exists():
            try:
                current = json.loads(profile_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                current = {}
        if not isinstance(current, dict):
            current = {}
        players: dict[str, Any] = current.get("players") or {}

        for name, prof in (summary.get("opponents") or {}).items():
            if not isinstance(prof, dict):
                continue
            entry = players.get(name) or {}
            entry["hands_seen"] = int(entry.get("hands_seen", 0)) + int(prof.get("hands_seen", 0))
            entry["vpip_n"] = int(entry.get("vpip_n", 0)) + int(prof.get("vpip_n", 0))
            entry["pfr_n"] = int(entry.get("pfr_n", 0)) + int(prof.get("pfr_n", 0))
            entry["threebet_n"] = int(entry.get("threebet_n", 0)) + int(prof.get("threebet_n", 0))
            # opponents_out 에서는 "showdowns" / "showdown_won_n" 이라는 키를 쓴다.
            sd_n = prof.get("showdown_n")
            if sd_n is None:
                sd_n = prof.get("showdowns", 0)
            entry["showdown_n"] = int(entry.get("showdown_n", 0)) + int(sd_n or 0)
            entry["showdown_won_n"] = int(entry.get("showdown_won_n", 0)) + int(
                prof.get("showdown_won_n", 0) or 0
            )
            # v5.4: 누적 wssd_pct 미리 컴퓨팅. strategy._postflop 가 직접 읽음.
            sd_total = entry["showdown_n"]
            if sd_total > 0:
                entry["wssd_pct"] = round(entry["showdown_won_n"] / sd_total, 4)
            else:
                entry["wssd_pct"] = 0.0
            hist: dict[str, int] = dict(entry.get("made_hand_histogram") or {})
            for cat, cnt in (prof.get("made_hand_histogram") or {}).items():
                hist[cat] = int(hist.get(cat, 0)) + int(cnt)
            entry["made_hand_histogram"] = hist
            entry["last_updated"] = time.time()
            players[name] = entry

        out = {
            "schema_version": _SCHEMA_VERSION,
            "updated_at": time.time(),
            "players": players,
        }
        _atomic_write_json(profile_path, out)


def _stream_events(path: Path, run_id: str) -> list[dict[str, Any]]:
    """주어진 run_id 범위의 record 리스트 (순서 보존).

    `_run_started` 마커로 블록을 분리. 지정된 run_id 블록만 반환.
    """
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    current_run: str | None = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "_run_started" in rec:
                    current_run = rec.get("run_id")
                    continue
                if current_run != run_id:
                    continue
                out.append(rec)
    except OSError as e:
        logger.warning("summary_stream_failed", extra={"error": repr(e), "path": str(path)})
    return out


def _build_summary(
    *,
    room_id: int,
    run_id: str,
    bot_name: str,
    events: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
) -> dict[str, Any]:
    """events 리스트로 summary dict 만든다."""
    started_at: float | None = None
    ended_at: float | None = None
    total_hands = 0
    participated_hands = 0
    vpip_hits = 0
    pfr_hits = 0
    showdowns = 0
    showdowns_won = 0
    max_stack = 0
    min_stack = 10**9
    decisions_summary: Counter[str] = Counter()
    elimination: dict[str, Any] | None = None

    # opponent 집계 상태
    opp_stats: dict[str, dict[str, Any]] = {}

    # 핸드 단위 루프: hand_start 이벤트를 기준으로 구간을 나눔.
    hand_blocks = _split_hands(events)

    for block in hand_blocks:
        hs = block["hand_start"]
        if hs is None:
            continue
        total_hands += 1
        if started_at is None and "ts" in block:
            started_at = block["ts_start"]
        ended_at = block.get("ts_end", ended_at)

        hs_evt = hs.get("event") or {}
        my_stack = int(hs_evt.get("your_stack") or 0)
        if my_stack > max_stack:
            max_stack = my_stack
        if my_stack < min_stack:
            min_stack = my_stack

        my_cards = list(hs_evt.get("your_cards") or [])
        # 플레이어 목록
        players = hs_evt.get("players") or []

        # 내 결정들을 inbound event 순서에 맞춰 phase 추정.
        # outbound action 은 직전 inbound action_request 의 phase 를 따른다.
        annotated_outs = _annotate_outbound_phases(block)

        # 내 프리플롭 액션 기록 (vpip / pfr 판정용)
        my_preflop_action: str | None = None
        my_participated = False
        for rec in annotated_outs:
            payload = rec.get("payload") or {}
            meta = rec.get("meta") or {}
            phase = meta.get("phase") or rec.get("_phase") or "preflop"
            act = payload.get("action") or meta.get("action")
            to_call = meta.get("to_call") if isinstance(meta, dict) else None
            if to_call is None:
                to_call = rec.get("_to_call")
            if act:
                decisions_summary[f"{phase}_{act}"] += 1
            if phase == "preflop":
                # BB 에서 to_call==0 인 check/call 은 자발적 참여 아님
                voluntary = act in ("call", "raise", "allin") and (to_call or 0) > 0
                if voluntary or act in ("raise", "allin"):
                    my_participated = True
                if act in ("raise", "allin"):
                    my_preflop_action = "raise"
                elif act == "call" and my_preflop_action is None and voluntary:
                    my_preflop_action = "call"

        if my_participated:
            participated_hands += 1
            vpip_hits += 1
        if my_preflop_action == "raise":
            pfr_hits += 1

        # 상대 액션 집계 (action_performed in-events)
        _update_opp_actions(block, bot_name, opp_stats)

        # hand_result 처리
        hr = block.get("hand_result")
        if hr is not None:
            hr_evt = hr.get("event") or {}
            showdown_entries = list(hr_evt.get("showdown") or [])
            board_final = list(hr_evt.get("community_cards") or [])
            winners = hr_evt.get("winners") or []
            eliminated = list(hr_evt.get("eliminated") or [])
            winner_names = {w.get("name") for w in winners if isinstance(w, dict)}

            my_in_sd = any(
                isinstance(s, dict) and s.get("name") == bot_name for s in showdown_entries
            )
            if my_in_sd:
                showdowns += 1
                if bot_name in winner_names:
                    showdowns_won += 1

            # 상대 쇼다운 통계
            for s in showdown_entries:
                if not isinstance(s, dict):
                    continue
                name = s.get("name")
                if not name or name == bot_name:
                    continue
                st = opp_stats.setdefault(name, _new_opp_stat())
                st["showdown_n"] += 1
                if name in winner_names:
                    st["showdown_won_n"] += 1
                cards = s.get("cards") or []
                if len(cards) >= 2 and len(board_final) >= 3:
                    try:
                        made = classify_hand(list(cards) + list(board_final))
                        cat = str(made.get("category") or "unknown")
                        st["made_hand_histogram"][cat] = st["made_hand_histogram"].get(cat, 0) + 1
                    except Exception:  # noqa: BLE001
                        pass

            # hands_seen: hand_start 에 있던 player 마다 +1
            for p in players:
                if not isinstance(p, dict):
                    continue
                name = p.get("name")
                if not name or name == bot_name:
                    continue
                st = opp_stats.setdefault(name, _new_opp_stat())
                st["hands_seen"] += 1

            # 탈락 판정
            if elimination is None and bot_name in eliminated:
                elimination = _build_elimination_info(
                    block=block,
                    bot_name=bot_name,
                    board_final=board_final,
                    showdown_entries=showdown_entries,
                    hand_number=int(hr_evt.get("hand_number") or hs_evt.get("hand_number") or 0),
                )

    if min_stack == 10**9:
        min_stack = 0

    vpip = vpip_hits / participated_hands if participated_hands > 0 else 0.0
    # VPIP 는 "참여 / 전체 핸드" 가 일반적이므로 total 로 다시 계산.
    vpip = vpip_hits / total_hands if total_hands > 0 else 0.0
    pfr = pfr_hits / total_hands if total_hands > 0 else 0.0
    sd_win_rate = showdowns_won / showdowns if showdowns > 0 else 0.0

    # 랭킹에서 내 최종 순위/칩
    final_rank: int | None = None
    final_chips: int | None = None
    for r in rankings:
        if isinstance(r, dict) and r.get("name") == bot_name:
            final_rank = r.get("rank")
            final_chips = r.get("chips")
            break

    # 상대 요약 프로필 변환
    opponents_out: dict[str, Any] = {}
    for name, st in opp_stats.items():
        hs_count = int(st["hands_seen"]) or 1
        opponents_out[name] = {
            "hands_seen": int(st["hands_seen"]),
            "vpip_n": int(st["vpip_n"]),
            "pfr_n": int(st["pfr_n"]),
            "threebet_n": int(st["threebet_n"]),
            "vpip": round(st["vpip_n"] / hs_count, 4) if hs_count else 0.0,
            "pfr": round(st["pfr_n"] / hs_count, 4) if hs_count else 0.0,
            "threebet": round(st["threebet_n"] / hs_count, 4) if hs_count else 0.0,
            "showdowns": int(st["showdown_n"]),
            "showdown_won_n": int(st["showdown_won_n"]),
            "showdown_win_rate": (
                round(st["showdown_won_n"] / st["showdown_n"], 4) if st["showdown_n"] > 0 else 0.0
            ),
            "made_hand_histogram": dict(st["made_hand_histogram"]),
        }

    return {
        "schema_version": _SCHEMA_VERSION,
        "room_id": room_id,
        "run_id": run_id,
        "bot_name": bot_name,
        "started_at": started_at,
        "ended_at": ended_at,
        "total_hands": total_hands,
        "participated_hands": participated_hands,
        "vpip": round(vpip, 4),
        "pfr": round(pfr, 4),
        "showdowns": showdowns,
        "showdowns_won": showdowns_won,
        "showdown_win_rate": round(sd_win_rate, 4),
        "final_rank": final_rank,
        "final_chips": final_chips,
        "elimination": elimination,
        "max_stack": max_stack,
        "min_stack": min_stack,
        "opponents": opponents_out,
        "decisions_summary": dict(decisions_summary),
    }


def _new_opp_stat() -> dict[str, Any]:
    return {
        "hands_seen": 0,
        "vpip_n": 0,
        "pfr_n": 0,
        "threebet_n": 0,
        "showdown_n": 0,
        "showdown_won_n": 0,
        "made_hand_histogram": {},
    }


def _split_hands(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """events 를 hand_start ~ hand_result(or 다음 hand_start) 단위로 묶는다."""
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for rec in events:
        kind = _record_kind(rec)
        if kind == "hand_start":
            if current is not None:
                blocks.append(current)
            current = {
                "hand_start": rec,
                "hand_result": None,
                "outbound_actions": [],
                "inbound": [],
                "ts_start": rec.get("ts"),
                "ts_end": rec.get("ts"),
            }
            continue
        if current is None:
            # hand_start 전의 이벤트는 무시
            continue
        current["ts_end"] = rec.get("ts", current.get("ts_end"))
        if kind == "hand_result":
            current["hand_result"] = rec
            blocks.append(current)
            current = None
            continue
        # inbound/outbound 모두 순서 보존을 위해 inbound 리스트에 함께 넣는다.
        current["inbound"].append(rec)
        if rec.get("dir") == "out" and rec.get("kind") == "action":
            current["outbound_actions"].append(rec)
    if current is not None:
        blocks.append(current)
    return blocks


def _record_kind(rec: dict[str, Any]) -> str | None:
    if rec.get("dir") == "in":
        return rec.get("type")
    return None


def _annotate_outbound_phases(block: dict[str, Any]) -> list[dict[str, Any]]:
    """block 의 inbound 스트림을 따라가며, outbound action 레코드마다 _phase / _to_call 을 붙인다."""
    current_phase = "preflop"
    last_to_call: int | None = None
    out_list: list[dict[str, Any]] = []
    # hand_start 부터 시작, block["inbound"] 는 이미 hand_start 이후 이벤트만 포함
    combined: list[dict[str, Any]] = []
    combined.extend(block.get("inbound", []))
    # 실제 시간 순서는 이미 파일 순서 그대로. 우리는 inbound 리스트 안에 out 레코드도 섞여있는지 확인.
    # _split_hands 에서는 out 레코드는 outbound_actions 에만 넣고 inbound 에도 동시에 append 하므로
    # inbound 리스트에 out 레코드도 섞여있을 것. (기존 구현 참고)
    for rec in combined:
        dir_ = rec.get("dir")
        t = rec.get("type") if dir_ == "in" else None
        if t == "phase_change":
            evt = rec.get("event") or {}
            current_phase = evt.get("phase") or current_phase
            continue
        if t == "action_request":
            evt = rec.get("event") or {}
            current_phase = evt.get("phase") or current_phase
            last_to_call = evt.get("to_call")
            continue
        if dir_ == "out" and rec.get("kind") == "action":
            annotated = dict(rec)
            annotated["_phase"] = current_phase
            annotated["_to_call"] = last_to_call
            out_list.append(annotated)
    return out_list


def _update_opp_actions(
    block: dict[str, Any], bot_name: str, opp_stats: dict[str, dict[str, Any]]
) -> None:
    """이 핸드의 action_performed in-events 로 상대 VPIP/PFR/3bet 카운트."""
    # 프리플롭 라이즈 횟수 추적
    preflop_raise_count = 0
    # 플레이어별: 이 핸드에서 프리플롭에 '자발적'(bb check 제외) 참여 했는지
    preflop_voluntary: dict[str, bool] = {}
    preflop_raised_by: set[str] = set()
    threebet_by: set[str] = set()
    current_phase = "preflop"
    for rec in block.get("inbound", []):
        t = rec.get("type")
        if t == "phase_change":
            evt = rec.get("event") or {}
            current_phase = evt.get("phase") or current_phase
            continue
        if t != "action_performed":
            continue
        evt = rec.get("event") or {}
        player = evt.get("player")
        action = evt.get("action")
        if not player or player == bot_name:
            continue
        if current_phase != "preflop":
            continue
        if action in ("call", "raise", "allin"):
            preflop_voluntary[player] = True
        if action in ("raise", "allin"):
            if preflop_raise_count == 0:
                preflop_raised_by.add(player)
            elif preflop_raise_count >= 1:
                threebet_by.add(player)
            preflop_raise_count += 1

    for name, did_vpip in preflop_voluntary.items():
        if did_vpip:
            st = opp_stats.setdefault(name, _new_opp_stat())
            st["vpip_n"] += 1
    for name in preflop_raised_by:
        st = opp_stats.setdefault(name, _new_opp_stat())
        st["pfr_n"] += 1
    for name in threebet_by:
        st = opp_stats.setdefault(name, _new_opp_stat())
        st["threebet_n"] += 1


def _build_elimination_info(
    *,
    block: dict[str, Any],
    bot_name: str,
    board_final: list[str],
    showdown_entries: list[dict[str, Any]],
    hand_number: int,
) -> dict[str, Any]:
    """탈락 정보 추출: 마지막 phase, cause, 상대 카드 등."""
    # 내 카드
    hs_evt = (block.get("hand_start") or {}).get("event") or {}
    my_cards = list(hs_evt.get("your_cards") or [])

    # 마지막 phase: phase_change 중 마지막 것
    last_phase = "preflop"
    for rec in block.get("inbound", []):
        if rec.get("type") == "phase_change":
            evt = rec.get("event") or {}
            last_phase = evt.get("phase") or last_phase

    # 내 마지막 액션
    my_last_action: str | None = None
    for out in block.get("outbound_actions", []):
        payload = out.get("payload") or {}
        act = payload.get("action")
        if act:
            my_last_action = act

    # 상대 쇼다운에서 첫 번째 non-bot
    villain: str | None = None
    villain_cards: list[str] = []
    for s in showdown_entries:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        if not name or name == bot_name:
            continue
        villain = name
        villain_cards = list(s.get("cards") or [])
        break

    # cause 추정
    cause = _classify_elimination_cause(
        my_last_action=my_last_action,
        my_cards=my_cards,
        board_final=board_final,
        villain_cards=villain_cards,
        last_phase=last_phase,
        showdown_entries=showdown_entries,
        bot_name=bot_name,
    )

    return {
        "hand_number": hand_number,
        "phase": last_phase,
        "cause": cause,
        "your_cards": my_cards,
        "board": board_final,
        "villain": villain,
        "villain_cards": villain_cards,
        "my_last_action": my_last_action,
    }


def _classify_elimination_cause(
    *,
    my_last_action: str | None,
    my_cards: list[str],
    board_final: list[str],
    villain_cards: list[str],
    last_phase: str,
    showdown_entries: list[dict[str, Any]],
    bot_name: str,
) -> str:
    """탈락 원인 분류. last_action 별로 3-계층 세분화.

    카테고리:
    - folded_bust             : fold 후 스택 0 (이전 핸드들에서 누적 손실)
    - forced_showdown_dominated : 액션 없이 (None) 쇼다운 간 뒤 패배 (BB 블라인드 묶임 등)
    - forced_showdown_beat    : 액션 없이 쇼다운, 내가 비교상 이긴 것처럼 보이지만 탈락 (side-pot)
    - blind_out               : 액션 없이 & 쇼다운 無 — blind 만 포스트하고 끝난 핸드
    - allin_call_dominated    : 내가 allin/call → 쇼다운 패배
    - allin_bad_beat          : 내가 allin/call → 쇼다운 카드상 우위였는데 run-out 역전 (기록용)
    - allin_no_showdown       : 내가 allin/call → 쇼다운 정보 없음
    - aggressive_bet_into_better : 내가 raise 후 쇼다운 패배
    - checked_down_loss       : 내가 check/call 만으로 쇼다운 패배 (passive bust)
    - unknown                 : 위 어디에도 해당 안 됨 (버그 색출용)
    """
    in_sd = any(isinstance(s, dict) and s.get("name") == bot_name for s in showdown_entries)

    # 쇼다운 카드 비교 가능한 경우 결과 먼저 계산.
    cmp_result: str | None = None  # "win" / "lose" / None
    if in_sd and my_cards and len(board_final) >= 3 and len(villain_cards) >= 2:
        try:
            my_r = rank7(my_cards + board_final)
            opp_r = rank7(villain_cards + board_final)
            cmp_result = "win" if my_r > opp_r else "lose"
        except Exception:  # noqa: BLE001
            cmp_result = None

    # 액션 없이 탈락 — BB 블라인드 묶임, 시간초과, 혹은 상대 allin 으로 자동 진행.
    if my_last_action is None:
        if in_sd:
            return "forced_showdown_beat" if cmp_result == "win" else "forced_showdown_dominated"
        return "blind_out"

    if my_last_action == "fold":
        return "folded_bust"

    if my_last_action in ("allin", "call"):
        if cmp_result == "lose":
            return "allin_call_dominated"
        if cmp_result == "win":
            # 카드상 우위였는데 탈락 — 쇼다운 기록에 내 row 는 있지만 승자에 없는 side-pot 구조.
            return "allin_bad_beat"
        return "allin_no_showdown"

    if my_last_action == "raise":
        return "aggressive_bet_into_better"

    if my_last_action == "check":
        return "checked_down_loss"

    return "unknown"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """tmp + os.replace 로 원자적 쓰기."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
