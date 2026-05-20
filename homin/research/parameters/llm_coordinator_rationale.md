# LLM Coordinator — 수치·정책 근거 (llm.yaml)

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Updated**: 2026-04-19 (v0.2 — OpenAI-호환 프록시 전환)
- **Owner**: holdem-agent
- **Version**: 0.2
- **Maps to**: `configs/llm.yaml` v0.2
- **Sources**:
  - plan Section M (LLM 통합 표준 — v0.2 에서 프록시 기반으로 개정)
  - plan Section D7 (LLM Coordinator 구현)
  - plan Section D.2, G.7, I.6.c (escalation 정책)
- **BOT_GUIDE refs**: §6.3 (30s 타임아웃 하드 제약)

---

## 1. 결정 요약 (v0.2)

모든 LLM 호출은 **OpenAI-호환 로컬 프록시** (`http://localhost:8317/v1`) 경유.
클라이언트는 `openai>=1.50` 의 `AsyncOpenAI` (base_url override).

**v0.1 → v0.2 변경 핵심**:
- ❌ `claude-agent-sdk` 제거 (tool-use / hooks / sessions 미사용 — 봇 결정에 불필요).
- ✅ OpenAI-compat 엔드포인트 + Bearer token 으로 단순화.
- ✅ 모델 티어 3단화: haiku (default) / sonnet (standard) / opus (critical).
- ✅ `temperature=0.0` 고정, timeout 모델별 차등 (haiku 1.0s, sonnet 1.5s, opus 3.0s).
- ✅ Fallback 5 경로 유지 (timeout/api_error/auth_missing/budget/schema).

---

## 2. 왜 Agent SDK 가 아닌 OpenAI-compat 프록시인가

### 2.1 봇 런타임의 실제 요구

봇 결정용 LLM 호출은 다음만 필요:
- chat completions (messages → text 응답).
- temperature 0 + max_tokens 제한.
- timeout.
- 응답 텍스트 → 허용 액션 집합의 discrete choice 로 파싱.

**Agent SDK 의 추가 기능**은 봇 런타임에서 모두 비활성화 대상:
- Tool-use loop: `allowed_tools=[]` 로 봉쇄.
- Session resume/fork: 의사결정은 핸드 단위 stateless.
- Hooks: 비용 감사는 응답 후 1줄 JSONL 로 충분.
- Skills / MCP / Subagents: Phase 2 이후.

→ 엄격 모드에서 Agent SDK 는 **chat completions 래퍼** 와 기능적으로 동일. 한 레이어 제거.

### 2.2 프록시 선택의 이점

- **단일 토큰 관리**: `sk-cliproxy-*` 하나로 3 모델 전부 접근.
- **로컬 우선**: 지연 ↓ (프록시가 동일 머신), 장애 시 fallback 확정적.
- **OpenAI SDK 생태**: AsyncOpenAI 는 표준. 다른 OpenAI-compat 도구(예: instructor, guidance) 접목 가능.
- **비용·사용량 한 곳에서 집계**: 프록시가 모델별 토큰 과금을 통합 기록.

### 2.3 Trade-off

| 잃은 것 | 영향 | 대응 |
|---|---|---|
| Agent SDK hooks | 호출 감사 자동 | 응답 후 `data/logs/llm_calls.jsonl` 1 줄 기록으로 대체 (audit 섹션) |
| Session 컨텍스트 캐시 | 프롬프트 재사용 | OpenAI prompt caching 은 프록시 정책에 의존. 일단 캐시 무가정 |
| Extended thinking (opus 4.7) | — | chat completions API 도 thinking 지원 (향후 옵션) |

**결론**: 잃는 기능은 모두 Phase 2 이후 필요. 지금은 단순한 chat completions 가 최적.

---

## 3. 모델 선택 정책

### 3.1 3-Tier: haiku / sonnet / opus

```yaml
models:
  default:  "claude-haiku-4-5-20251001"    # 대부분 escalation
  standard: "claude-sonnet-4-6"            # borderline + 재확인
  critical: "claude-opus-4-7"              # 결승/버블
```

**v0.1 (sonnet default) → v0.2 (haiku default) 전환 근거**:
- Escalation 조건 충족 판단 자체가 이미 필터링 → 대부분의 escalation 은 "명확한 답이 있는 borderline".
- Haiku 로 충분히 해결 가능 (통계 argmax 재확인 수준).
- sonnet 호출 비용의 1/3 수준 → 더 많은 케이스에서 LLM 참고 가능 (per_hand_max=1 유지하되 per_game_max=20 여유).
- Haiku 실패 / 분기점 급상승 시 sonnet/opus 로 승격.

### 3.2 Escalation gate

```yaml
default_triggers:   # → haiku
  - top1_top2_ev_within_5pct
  - variance_high

standard_triggers:  # → sonnet
  - multiway_3plus_borderline
  - fold_equity_uncertain

critical_triggers:  # → opus
  - M_lt_6
  - near_bubble
  - stack_gt_100bb_pot_gt_50bb
```

**설계**: triggers 는 배타적. critical → standard → default 의 순서로 우선 매칭.

### 3.3 모델별 파라미터

| 모델 | max_tokens | timeout_s | 입력 (1M) | 출력 (1M) |
|---|---:|---:|---:|---:|
| haiku-4-5 | 512 | 1.0 | $1 | $5 |
| sonnet-4-6 | 1024 | 1.5 | $3 | $15 |
| opus-4-7 | 2048 | 3.0 | $15 | $75 |

- **timeout 1.0s (haiku)**: BOT_GUIDE §6.3 의 30s 하드 제약 하에서 safety margin 30배.
- **max_tokens**: haiku 는 의사결정 1개 + 짧은 이유로 충분. opus 는 range 추정 여유.

---

## 4. Runtime 근거

### 4.1 Endpoint 구성

```yaml
endpoint:
  base_url:          "http://localhost:8317/v1"
  env_var_key:       "HOLDEM_LLM_API_KEY"
  env_var_base_url:  "HOLDEM_LLM_BASE_URL"   # 선택적 override
```

- 기본 URL 은 yaml 에 고정, env 로 덮어쓰기 가능.
- 토큰은 **반드시 env** — yaml / git 에 저장 금지.
- 토큰 결손 시: `LLMResult(ok=False, reason="auth_missing")` → 통계 argmax.

### 4.2 `temperature=0.0` 강제

- **재현성**: 동일 prompt → 동일 응답. snapshot test (`tests/snapshots/llm_decisions.jsonl`) 의 전제.
- **감사성**: 프록시 로그와 우리 로그를 hash 로 대조 가능.

### 4.3 예산 상한 (변화 없음)

```yaml
budget:
  per_hand_max_calls:   1
  per_game_max_calls:   20
  per_day_max_calls:    5000
  per_minute_max_calls: 10
```

- 게임 평균 ~100 핸드 → per_game=20 은 20% escalation 상한.
- 실제 목표: ≤5% 핸드 (K.10 [S-3]).

---

## 5. Fallback 정책 (변화 없음)

5 경로 모두 **통계 argmax** 로 수렴:

1. **timeout**: 모델별 timeout 초과.
2. **api_error**: proxy 5xx, rate limit, overload, network.
3. **auth_missing**: `HOLDEM_LLM_API_KEY` 결손.
4. **budget_exceeded**: 3 단 상한 돌파.
5. **schema_violation**: 응답이 허용 액션 집합 밖.

`LLMClient.complete()` 는 **절대 예외를 raise 하지 않는다**. `LLMResult(ok=False, reason=...)` 반환. 봇 가동 연속성 보장.

---

## 6. 구현 위치

| 항목 | 위치 | 상태 |
|---|---|---|
| Client | `src/holdem/meta/llm_client.py` | ✅ D7 이전에 완성 (Day 7) |
| Coordinator | `src/holdem/meta/coordinator.py` | 미구현 (D7, 주 12) |
| Config loader | `src/holdem/meta/llm_client.py::load_config` | ✅ |
| Audit log | `data/logs/llm_calls.jsonl` | D7 에서 |
| Snapshot test | `tests/snapshots/llm_decisions.jsonl` | D7 에서 |

---

## 7. Limitations · Risks

| 리스크 | 완화 |
|---|---|
| 프록시 다운 | `api_error` fallback. 분당 10회 제한으로 재시도 폭주 방지 |
| 프록시 토큰 노출 | 반드시 env, git ignore. yaml 에 저장 금지 |
| 모델 ID 변경 (프록시 정책) | `configs/llm.yaml` 의 `models` 블록 한 곳만 수정 |
| OpenAI SDK breaking change | `openai>=1.50, <3` 범위 제약 (다음 메이저만 허용) |
| 프롬프트 캐시 미사용 | v0.2 는 캐시 무가정. 비용 상한으로 흡수. 필요시 Anthropic prompt caching 복귀 검토 |
| haiku 판단 품질 | snapshot test + 실서버 winrate 로 모니터. 품질 저하 시 default → sonnet 승격 |
| temperature 0 reproducibility 한계 | 프록시 버전 업그레이드 시 응답 drift 가능 → 주간 snapshot diff |

---

## 8. Next Steps

- **Day 7 완료**: `LLMClient` + config loader + 8 개 unit test ✅
- **D7 (주 12)**:
  - `src/holdem/meta/coordinator.py` 구현 — escalation gate + budget counter.
  - Hooks 대체: 응답 후 JSONL 감사 로그.
  - Snapshot test 시드 20개 (haiku 응답 기준).
- **실서버 스모크 (Week 2 M1 이후)**: 토큰 발급되면 `.env` 에 기입 → `/v1/models` 로 모델 목록 확인 → haiku 1회 호출로 엔드포인트 검증.

---

## 9. Changelog

- **2026-04-19 (v0.2)**: OpenAI-호환 프록시 전환. claude-agent-sdk 제거. 3-tier (haiku/sonnet/opus). `LLMClient` 구현 완료.
- 2026-04-19 (v0.1): Claude Agent SDK 기반 단일화 초안. (v0.2 에서 폐기)
