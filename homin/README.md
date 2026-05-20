# holdem-agent

Texas Hold'em No-Limit 토너먼트 봇 — 3-계층 Bayesian 상대 모델 + Conservatism 프로파일 + LLM 메타 코디네이터.

## 전략 — 1000+ 핸드 대회를 푸는 접근

### 문제 정의 (왜 일반 포커 전략이 아닌가)

이 대회는 사람들끼리 두는 한두 판의 게임이 아니라 **최소 1000+ 핸드가 자동으로 수행**된다. 이 조건이 전략 자체를 다르게 만든다.

- 시행 수가 충분 → **중심극한정리(CLT) 유효** → 단발의 운보다 **장기 EV · variance 관리**가 결정적
- 그래서 프레임 자체를 **"매 핸드의 평균 EV 와 효용을 최대화하는 의사결정 모델"** 로 잡음
- 구체적으로 **베이즈 정리 기반 상대 반응 모델** + **켈리 공식 유사 log-utility 사이징** 의 결합

### 1. Bayesian 의사결정 + Kelly 유사 사이징

- **Dirichlet 응답 모델** — `src/holdem/estimate/bayes.py:21` `DirichletResponse`
  - (상대, phase) 별로 fold / call / raise 사후분포를 누적
  - Thompson sampling 으로 의사결정 호출당 1회 샘플 → 한 결정 안에서는 일관된 확률 사용 (`bayes.py:90` `thompson_action_rates`)
- **EV Tree (1-ply)** — `src/holdem/decide/ev.py:113` `ev_raise()`
  - `p_fold · pot + p_call · (eq · villain_pot − Δ) + p_raise · ev_vs_reraise`
  - Reraise 경로는 range-narrowing penalty (`eq_vs_reraise = equity − 0.15`) 로 비관 평가
- **Log-utility (켈리 공식 유사)** — `src/holdem/decide/ev.py:79` `_log_utility()`
  - `U(s) = eq · log(win+ε) + (1−eq) · log(lose+ε)`
  - chip-EV 가 양수여도 log-util 이 음수면 자동 기각 → **올인·저equity 시나리오 자동 차단**, 토너먼트 stack 보호
- **Sizing optimizer** — `src/holdem/decide/sizing.py:96` `optimize()`
  - `ConservatismProfile` 의 사이즈 grid 위에서 `argmax(log_util)`

### 2. Cold Start 문제 ↔ Kaggle LLM 1:1 데이터로 사전 주입

**문제**: 모든 봇이 동시에 시작 → 누구에게도 사전 데이터가 없음 → 초반에 좋은 성능을 내기 어려움. 게다가 참여 봇이 6개이기 때문에 한 봇이 경향을 바꾸면 **환경 자체가 흔들릴** 가능성도 있음. cold start 가 풀려야 점진 적응도 의미가 있음.

**해결**: Kaggle 의 [`kaggle/poker-heads-up`](https://www.kaggle.com/datasets/kaggle/poker-heads-up) 데이터셋 (15 LLM 모델 페어, **2,059,400 핸드**, CC BY 4.0) 을 population prior 로 사전 주입. 데이터셋 자체는 용량(~1.8 GB) 때문에 repo 에 없음 — 아래 [데이터 재현](#데이터-재현-kaggle-데이터셋) 섹션 참조.

구현 경로:
- `data/kaggle/` — 원본 데이터
- `research/dataset_analysis/inspection_report.md` — 데이터 호환성 검증 (카드 표기 100%, 액션 어휘 매핑)
- `research/dataset_analysis/eda_01_distributions.md` — Population prior 산출 (HU→9max 전이 후: CBET 71% / 3BET 14% / FOLD_TO_CBET 32.6%)
- `configs/priors.yaml` + `configs/transfer_coefficients.yaml` — Beta(α, β) 형태로 봇에 주입 + HU→{4, 6, 9}max 전이 계수
- `src/holdem/estimate/priors.py:54` `load_population_priors()` — 로드
- `src/holdem/estimate/shrinkage.py` — **3-layer Empirical Bayes** (개인 → 4-class → population 혼합)

수렴 곡선: `n_effective ∈ {10, 30, 80, 150, 400}` 경계로 **hard_conservative → exploit_ready** 6 단계 (`research/dataset_analysis/eda_03_convergence.md`).

**HU↔토너먼트 차이 인정**: Kaggle 은 HU cash, 본 대회는 토너먼트 → 전이 계수로 보정. 수학 기반 지표 (CBET / BARREL / FOLD_TO_CBET) 는 신뢰도 HIGH 로, 스타일 지표 (VPIP / 3BET) 는 MID 로 차등 적용.

### 3. Showdown 의 의사결정 가치 + 상대 경향성 카테고리화

의사결정의 목적을 **"이 핸드의 승리"** 만 두지 않고 **"showdown 으로 상대 패를 보아 상대 경향성을 파악하는 것의 기대 가치"** 까지 포함시킴.

- **Showdown 의 정보 가치 (Information Gain)** — `research/dev_log/d5_week9_bayes_ig.md`
  - `IG = γ · exp(−n / τ)` — 관측 수가 적은 상대일수록 가치 ↑
  - action 별 multiplier: fold = 0, call = 0.3, raise = 1.0
  - `src/holdem/decide/ev.py` 의 reraise 경로에서 range-narrowing 으로 showdown equity 의 정보를 반영
- **4-class opponent typing** — `src/holdem/estimate/class_typer.py:37` `soft_assign()`
  - VPIP / PFR / AF 평면에서 K-Means / GMM (k=4) → **NIT / TAG / LAG / Fish**
  - `configs/class_priors.yaml` — centroid + per-class Beta prior
  - **soft assign** 으로 한 상대가 여러 카테고리에 확률 분포를 가지게 함 → 개인 데이터가 적은 단계의 cold start 완화
- **개별 상대 특화 override** — `configs/opponent_overrides.yaml`, `research/dev_log/r_opponent_편경장_eda.md`
- **C-bet 시나리오 실 데이터 보정** — `src/holdem/decide/cbet.py:132` `cbet_response_adjustment()`
  - `FOLD_TO_CBET` 실 데이터로 target_fold 확률을 동적 업데이트 → bluff EV 보정

### 4. 환경 변화 적응 (P-Decay + Conservatism)

6봇 환경의 메타 drift 에 대응:
- **P-Decay** — 100 핸드마다 모든 누적치 × 0.999 (`src/holdem/state/profile_store.py:33`) → 옛 경향성이 자연스럽게 늙어감
- **ConservatismProfile** 이 `n_effective` 에 따라 sizing grid 를 **hard_conservative ↔ exploit_ready** 로 동적 승급/강등 (`src/holdem/decide/conservatism.py`)

### 5. 개발 방식 — `research/` 폴더 축적형

이 봇의 특징은 코드를 먼저 짜는 것이 아니라, **`research/` 폴더에 가설·실험·매개변수 근거를 먼저 문서로 축적하고 그 위에서 코드를 짜는** 방식이라는 점이다.

| 폴더 | 역할 |
|------|------|
| `research/theory_notes.md` | 포커 수학 (Bayes, MDF, equity, Kelly 유사 log-utility 등) 정의 |
| `research/dataset_analysis/eda_01~05` | Kaggle 데이터로 population prior, opponent typing, convergence 경계, sizing, bluff threshold 산출 |
| `research/parameters/*_rationale.md` | `configs/*.yaml` 각 수치의 근거 (예: θ_bluff=0.35, θ_value=0.65) |
| `research/dev_log/d1~d7 + phase2` | 컴포넌트별 설계·구현 로그 |

효과: AI(Claude Code) 와의 협업에서 **"이 매개변수가 왜 이 값인지"** 가 항상 문서로 존재 → 가설을 잃지 않고 점진적 개선 가능. 새 실험은 `research/` 에 한 문서를 추가하는 것에서 시작.

## 구성

- `src/holdem/transport` — WebSocket 클라이언트 + pydantic 이벤트 스키마 (BOT_GUIDE §5).
- `src/holdem/state` — GameState (룸 단위 휘발성) + ProfileStore / ResponseStore (영속).
- `src/holdem/persist` — SQLite 프로필·반응 영속 (`profiles.db`), JSONL 이벤트 로그.
- `src/holdem/decide` — PushFold 차트 / Opening 차트 / ConservatismProfile / EV tree / Sizing optimizer.
- `src/holdem/estimate` — Equity (treys MC) / priors (shrinkage) / class typing / Dirichlet response / IG / board texture / range inference.
- `src/holdem/meta` — LLMClient (OpenAI-compat) + Coordinator + EscalationTriggers + Budget.
- `configs/` — priors / class_priors / sizing / conservatism_schedule / nash_charts / open_ranges / llm.
- `research/` — BOT_GUIDE 추출, EDA, parameter rationale, dev log.

## 설정

```bash
# 의존성
uv sync
uv sync --extra llm           # LLM coordinator 사용 시

# .env 설정 (.env.example 참고)
HOLDEM_WS_URL=ws://<server>:<port>/ws
HOLDEM_API_TOKEN=<발급된 토큰>
HOLDEM_BOT_NAME=<대시보드에 등록한 이름>
HOLDEM_LLM_API_KEY=<proxy API key>
HOLDEM_LLM_BASE_URL=http://localhost:8317/v1
```

## 실행

```bash
# 기본 (Nash chart + pot-odds) — 가장 안전
uv run holdem --profile-db data/profiles.db

# EV tree 경로 opt-in
uv run holdem --use-ev-tree --profile-db data/profiles.db

# + LLM coordinator (border-line escalation)
uv run holdem --use-ev-tree --use-coordinator --profile-db data/profiles.db

# 단일 세션 (재접속 루프 비활성)
uv run holdem --once
```

대시보드에서 "실행" 버튼 눌러 deploy 해야 게임 배정됨 (BOT_GUIDE §2.2). CLI 는 재접속 루프를 포함하므로 deploy 상태 유지 시 24/7 가동.

## 개발

```bash
# 전체 회귀 (297 tests)
uv run pytest -q

# 단일 모듈
uv run pytest tests/test_ev.py -v

# 타입 체크는 pyright/mypy 미연동, ruff 사용
uv run ruff check src tests
```

## 데이터 재현 (Kaggle 데이터셋)

`research/dataset_analysis/eda_01~05` 와 `configs/priors.yaml` 의 population prior 는 Kaggle 의 LLM vs LLM 1:1 핸드 히스토리 데이터셋에서 산출되었다. **저장소 용량 제약 (압축 해제 시 ~1.8 GB) 으로 원본 데이터는 push 에 포함되지 않음** — EDA 를 직접 재현하려면 아래 절차로 받을 것. (봇 실서버 구동에는 데이터 불필요 — `configs/priors.yaml` 만 있으면 됨.)

- **Kaggle 데이터셋**: <https://www.kaggle.com/datasets/kaggle/poker-heads-up>
- **라이선스**: CC BY 4.0
- **크기**: 101 MB (zip) → ~1.8 GB (압축 해제), 105 matchup 파일, **2,059,400 핸드**
- **SHA256 (zip)**: `2708a34b43cddb72dacefe877feeb2b9c7ad51121ba25f9873cea2b8cd6b9599`
- **상세 provenance**: `research/LICENSE_NOTE.md`

```bash
# Kaggle API 설치 + 인증 (~/.kaggle/kaggle.json 필요)
pip install kaggle

# 데이터셋 받기 (PokerStars-style hand history *.txt 105개)
mkdir -p data/raw
kaggle datasets download -d kaggle/poker-heads-up -p data/raw --unzip

# 파싱·검증 (≈92초, 2M 핸드)
uv run python scripts/dataset_inspect.py
# → data/dataset_report.json 생성, eda_01~05 의 입력
```

## 문서

- `guide/BOT_GUIDE.md` — 서버 프로토콜 원문 (운영자 제공).
- `research/README.md` — 연구 문서 인덱스.
- `research/theory_notes.md` — 포커 수학 기반.
- `research/dev_log/` — D1–D7 + Phase 2 통합 작업 기록.

## 상태

- D1–D7 모든 주요 컴포넌트 + Phase 2 통합 #1–#5 완료.
- 287 → 297 tests passing (설계 섹션 H/I/J/K/L/M 전반 커버).
- 실서버 smoke: room 359 에서 첫 가동 (2026-04-21), 테스트 룸에서 장시간 자동 순환 확인.
- 블로커: Deploy REST API 스펙 미문서화 — 현재는 대시보드 수동 "실행" 경유.
