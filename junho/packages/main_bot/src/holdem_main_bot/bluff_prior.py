"""뻥카 성향 Beta prior 저장소.

핵심 아이디어: 같은 상대가 1000+ 핸드 반복된다는 전제 하에, 플레이어별
(street × sizing_bucket × action_type) 버킷에서 "이 베팅이 뻥카였는가" 의
베이지안 posterior 를 누적한다.

수학 모델
---------
각 버킷은 독립 Beta(α, β) — α 는 "bluff 목격 수", β 는 "value 목격 수".
소프트 evidence 는 weight<1 로 누적 (쇼다운 없이 fold 로 이긴 aggressive 는 소프트).

`prob_bluff()` 는 posterior mean α/(α+β), `confidence()` 는 표본 크기 기반
shrinkage 계수 n/(n+K) (K=20, CLAUDE.md 분석 리포트 합의).

라벨링 규칙 (build_bluff_dataset.py 와 _observe_showdown_hand 가 공유)
--------------------------------------------------------------------
쇼다운에서 aggressive action 시점의 equity(vs random):
  equity <  0.40  → bluff   : α += 1.0
  0.40 ≤ equity < 0.65  → semi : α += 0.3, β += 0.3
  equity ≥ 0.65  → value   : β += 1.0

폴드로 이긴 aggressive action (쇼다운 없음):
  α += 0.2 (weak soft — fold 받아내는 것의 upper bound 만 시사)

파일 포맷
---------
```
{
  "schema_version": 1,
  "updated_at": 1745000000.0,
  "buckets": {
    "{player}|{street}|{sizing}|{action}": {"alpha": 3.2, "beta": 5.1, "n": 8},
    ...
  }
}
```
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from holdem_core.debug.store import DebugStore

_SCHEMA_VERSION = 1

# 글로벌 prior: 데이터 없을 때 반환할 기본값.
# v5.4: 1.0/3.0 (mean 0.25) → 1.0/4.0 (mean 0.20).
# 실측 bluff 빈도는 통상 10~15% 수준이라 0.25 는 over-bluff 인식.
# soft label 1:3 비율과 함께 long-run mean 이 0.20~0.25 수렴하게 보정.
_GLOBAL_PRIOR_ALPHA = 1.0
_GLOBAL_PRIOR_BETA = 4.0
_CONFIDENCE_K = 20.0  # n/(n+K) shrinkage. n>=20 정도부터 prior 보다 observation 우세.

Street = Literal["preflop", "flop", "turn", "river"]
SizingBucket = Literal["small", "medium", "large", "overbet"]
ActionType = Literal["bet", "raise", "3bet", "4bet", "allin"]


def sizing_bucket(amount: int, pot: int, to_call: int = 0) -> SizingBucket:
    """베팅/레이즈 사이즈 → bucket.

    raise 의 경우 amount 는 "이번 라운드 총 베팅 목표액" (BOT_REFERENCE §6.2).
    증분은 amount - to_call. bucket 기준은 pot 대비 증분.
    """
    pot_ref = max(int(pot), 1)
    raise_add = max(0, int(amount) - int(to_call))
    ratio = raise_add / pot_ref
    if ratio < 0.4:
        return "small"
    if ratio < 0.85:
        return "medium"
    if ratio < 1.3:
        return "large"
    return "overbet"


def action_type(action: str, raise_cnt_before: int, is_preflop: bool) -> ActionType | None:
    """action_performed → ActionType (bet/raise/3bet/4bet/allin) 중 aggressive 만.

    raise_cnt_before = 이 라운드에서 이 action 직전까지의 raise 수.
    """
    if action not in ("raise", "allin"):
        return None
    if action == "allin":
        return "allin"
    if is_preflop:
        # 프리플롭 raise_cnt_before: 0 → open(=raise), 1 → 3bet, 2+ → 4bet+
        if raise_cnt_before == 0:
            return "raise"
        if raise_cnt_before == 1:
            return "3bet"
        return "4bet"
    # 포스트플롭: raise_cnt_before 0 → bet (첫 자금), 1+ → raise
    if raise_cnt_before == 0:
        return "bet"
    return "raise"


def make_key(player: str, street: Street, sizing: SizingBucket, atype: ActionType) -> str:
    return f"{player}|{street}|{sizing}|{atype}"


@dataclass
class Bucket:
    alpha: float = _GLOBAL_PRIOR_ALPHA
    beta: float = _GLOBAL_PRIOR_BETA
    n: float = 0.0  # 가중치 합 (소프트 포함). 신뢰도 계산용.

    def prob_bluff(self) -> float:
        return self.alpha / max(self.alpha + self.beta, 1e-9)

    def confidence(self) -> float:
        """0(무정보) ~ 1(확정). n/(n+K)."""
        return self.n / (self.n + _CONFIDENCE_K)


@dataclass
class BluffPriorStore:
    buckets: dict[str, Bucket] = field(default_factory=dict)
    path: Path | None = None
    _dirty: bool = False
    _store: DebugStore | None = field(default=None, repr=False, compare=False)

    # ── I/O ────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> BluffPriorStore:
        p = Path(path)
        store = cls(path=p)
        if not p.exists():
            return store
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return store
        if not isinstance(raw, dict):
            return store
        buckets_raw = raw.get("buckets")
        if isinstance(buckets_raw, dict):
            for k, v in buckets_raw.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                store.buckets[k] = Bucket(
                    alpha=float(v.get("alpha", _GLOBAL_PRIOR_ALPHA)),
                    beta=float(v.get("beta", _GLOBAL_PRIOR_BETA)),
                    n=float(v.get("n", 0.0)),
                )
        return store

    @classmethod
    def open_db(cls, base_dir: str | Path) -> BluffPriorStore:
        """SQLite DebugStore 백엔드로 BluffPriorStore 를 연다.

        `{base_dir}/holdem.db` 가 없으면 새로 만들고 빈 store 를 반환.
        있으면 기존 bluff_priors 테이블에서 모든 bucket 을 lazy-load.
        JSON path 는 비활성 (호출자가 별도로 `bind_store` 후 path 를 지정하면 dual-write).
        """
        from holdem_core.debug.store import DebugStore

        store_inst = cls()
        ds = DebugStore.open(base_dir)
        store_inst._store = ds
        store_inst._rehydrate_from_store()
        return store_inst

    def bind_store(self, store: DebugStore) -> None:
        """이미 JSON 으로 로드된 instance 에 DebugStore 를 붙여 dual-write 를 활성화."""
        self._store = store
        self._rehydrate_from_store()

    def _rehydrate_from_store(self) -> None:
        """DB 로부터 buckets 를 다시 채운다 (in-memory 상태 reset)."""
        if self._store is None:
            return
        rows = self._store.all_bluff_priors()
        self.buckets = {}
        for key, b in rows.items():
            self.buckets[key] = Bucket(
                alpha=float(b.get("alpha", _GLOBAL_PRIOR_ALPHA)),
                beta=float(b.get("beta", _GLOBAL_PRIOR_BETA)),
                n=float(b.get("n", 0.0)),
            )

    def reload_from_db(self) -> int:
        """외부에서 DB 가 변경된 경우 in-memory buckets 를 강제 재동기화.

        SQLite 백엔드가 없으면 JSON 파일에서 다시 로드.
        반환: 재로드 후 bucket 수.
        """
        self._dirty = False
        if self._store is not None:
            self._rehydrate_from_store()
            return len(self.buckets)
        if self.path is None or not self.path.exists():
            self.buckets = {}
            return 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return len(self.buckets)
        if not isinstance(raw, dict):
            return len(self.buckets)
        buckets_raw = raw.get("buckets")
        new_buckets: dict[str, Bucket] = {}
        if isinstance(buckets_raw, dict):
            for k, v in buckets_raw.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                new_buckets[k] = Bucket(
                    alpha=float(v.get("alpha", _GLOBAL_PRIOR_ALPHA)),
                    beta=float(v.get("beta", _GLOBAL_PRIOR_BETA)),
                    n=float(v.get("n", 0.0)),
                )
        self.buckets = new_buckets
        return len(self.buckets)

    def save(self) -> None:
        # SQLite 우선: bound store 가 있으면 모든 bucket upsert.
        if self._store is not None:
            for key, b in self.buckets.items():
                try:
                    player, street, sizing, atype = key.split("|", 3)
                except ValueError:
                    continue
                self._store.upsert_bluff_prior(
                    player, street, sizing, atype, b.alpha, b.beta, b.n
                )
        # JSON 도 함께 쓸지 결정 — path 가 있고, JSONL 토글이 켜져 있을 때.
        write_json = self.path is not None
        if self._store is not None:
            try:
                from holdem_core.debug.store import jsonl_writes_enabled

                write_json = write_json and jsonl_writes_enabled()
            except ImportError:
                pass
        if write_json and self.path is not None:
            out: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "updated_at": time.time(),
                "buckets": {
                    k: {"alpha": round(b.alpha, 4), "beta": round(b.beta, 4), "n": round(b.n, 4)}
                    for k, b in self.buckets.items()
                },
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            text = json.dumps(out, ensure_ascii=False, indent=2)
            with tmp.open("w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, self.path)
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    # ── 조회 ───────────────────────────────────────────────────────────────

    def get(self, key: str) -> Bucket:
        return self.buckets.get(key) or Bucket()

    def lookup(
        self,
        player: str,
        street: Street,
        sizing: SizingBucket,
        atype: ActionType,
    ) -> tuple[float, float]:
        """(prob_bluff, confidence) 반환. 미존재시 global prior."""
        b = self.buckets.get(make_key(player, street, sizing, atype))
        if b is None:
            return (_GLOBAL_PRIOR_ALPHA / (_GLOBAL_PRIOR_ALPHA + _GLOBAL_PRIOR_BETA), 0.0)
        return (b.prob_bluff(), b.confidence())

    # ── 업데이트 ───────────────────────────────────────────────────────────

    def _bucket_mut(self, key: str) -> Bucket:
        b = self.buckets.get(key)
        if b is None:
            b = Bucket()
            self.buckets[key] = b
        return b

    def update_hard(
        self,
        player: str,
        street: Street,
        sizing: SizingBucket,
        atype: ActionType,
        equity: float,
    ) -> None:
        """쇼다운 공개 핸드. equity 로 hard label."""
        b = self._bucket_mut(make_key(player, street, sizing, atype))
        if equity < 0.40:
            b.alpha += 1.0
            b.n += 1.0
        elif equity < 0.65:
            b.alpha += 0.3
            b.beta += 0.3
            b.n += 0.6
        else:
            b.beta += 1.0
            b.n += 1.0
        self._dirty = True

    def update_soft_fold_win(
        self,
        player: str,
        street: Street,
        sizing: SizingBucket,
        atype: ActionType,
    ) -> None:
        """fold 로 이긴 aggressive action — weak soft label (총 weight 0.2).

        v5.4: alpha:beta 0.1:0.1 (50/50) → 0.05:0.15 (1:3, ~0.25 mean).
        이전 1:1 split 은 fold-win 마다 posterior 를 0.5 로 끌어당겨, 84% 가 soft 인
        실데이터에서 bluff 확률이 인공적으로 부풀려졌음. 1:3 split 은 "fold-win 의
        대부분은 value bet 이 fold 받아낸 것" 이라는 prior 를 반영.
        """
        b = self._bucket_mut(make_key(player, street, sizing, atype))
        b.alpha += 0.05
        b.beta += 0.15
        b.n += 0.2
        self._dirty = True

    def summary_stats(self) -> dict[str, Any]:
        """대시보드/디버그용."""
        n_players: dict[str, int] = {}
        total_n = 0.0
        for k, b in self.buckets.items():
            player = k.split("|", 1)[0]
            n_players[player] = n_players.get(player, 0) + 1
            total_n += b.n
        return {
            "n_buckets": len(self.buckets),
            "n_players": len(n_players),
            "total_weight": round(total_n, 1),
            "players": sorted(n_players.keys()),
        }
