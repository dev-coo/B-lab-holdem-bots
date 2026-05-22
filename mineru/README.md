# mineru — B-lab 홀덤 봇

> 전략 구현은 대부분 Codex에서 GPT-5.5로 진행했다.
> Claude Code 쪽 자료는 구현 도구라기보다 작업 방식과 행동 지침을 잡는 데 참고했다.
> 아래 내용은 코드, 커밋, 남아 있는 프롬프트 파일을 기준으로 정리했다.

---

## 1. 봇 소개

**한 줄**: 포커 AI 논문에서 얻은 아이디어를 Codex로 여러 전략 후보로 만들고, 실서버와 로컬 벤치마크에서 돌려 보며 골라낸 홀덤 봇.

현재 패키지는 `holdem-agent`라는 CLI로 실행된다. 출전/검증에 사용된 핵심 축은 `stage-safe-field-counter`, `dominance-wet-board-protector`, `omni`, `hybrid-gto`, `gto-baseline` 같은 등록 전략을 같은 서버·같은 봇 슬롯에서 갈아 끼우며 비교하는 방식이다. 특히 마지막 운영 프롬프트(`docs/prompt-04.txt`, 공유본에서는 토큰 노출 때문에 제외)는 `stage-safe-field-counter`를 실전 실행 대상으로 지정하고, 다른 후보군을 비교군으로 둔다.

코드 구조상 봇의 본체는 `src/holdem_agent/strategy/` 아래 전략 레지스트리와 built-in 전략군이다. CLI는 `holdem-agent play ... --strategy <name>` 형태로 전략을 선택한다.

처음부터 "내가 포커를 잘 아니까 정답 전략을 직접 적자"는 방향은 아니었다. Bayesian opponent modelling, CFR/Deep CFR, DeepStack/Libratus/Pluribus 같은 포커 AI 연구를 Codex GPT-5.5에게 조사시키고, 거기서 쓸 만한 아이디어를 작은 전략 후보로 나눠 구현했다. 그런 다음 후보끼리 돌려 보고, 살아남은 성질을 다음 전략에 다시 섞는 식으로 갔다. 그래서 결과물도 거대한 solver 하나라기보다는, 논문 아이디어를 실전 휴리스틱으로 옮긴 전략 묶음에 가깝다.

## 2. 핵심 전략

이 프로젝트의 핵심은 **하나의 포커 직관을 코드에 박는 것보다, 여러 전략 가설을 같은 방식으로 돌려 볼 수 있게 만든 것**이다. `src/holdem_agent/strategy/registry.py`가 built-in 전략을 자동 등록하고, `src/holdem_agent/__main__.py`의 `play`, `evaluate`, `analyze`, `evolve` 명령이 실서버 실행과 로컬 평가를 담당한다.

전략군은 네 묶음으로 나뉜다. 기본형은 `calling-station`, `tight-aggressive`, `aggressive`, `adaptive`, `gto-baseline`, `hybrid-gto`, `omni`처럼 기준선과 종합형을 제공한다. Practical 전략은 포지션 압박, 숏스택 푸시/폴드, 스퀴즈, 팟오즈, 드로우 세미블러프, 매니악 트랩 등 특정 상황 대응을 분리한다. Dominance 전략은 실전 약점을 더 공격적으로 찌르는 후보군이고, Statistical/Arena 전략은 실전 결과와 보수적 카운터를 반영한다.

autoresearch는 논문을 읽고 끝내는 용도가 아니라, "이걸 지금 대회 코드로 만들면 어떤 전략이 되나?"를 뽑는 데 썼다. `Bayes' Bluff: Opponent Modelling in Poker`에서 가져온 베이지안 상대 모델링은 `bayesian-exploit`로 이어졌고, CFR/Deep CFR와 DeepStack/Libratus/Pluribus 쪽에서 얻은 균형 기준, 국소 재평가, 상대 약점 exploit 관점은 `gto-baseline`, `hybrid-gto`, `omni`, `statistical-lcb-fusion`, `arena-*` 후보로 나뉘었다. `src/holdem_agent/strategy/builtins/arena.py`에도 "10 autoresearch arena candidates"라는 베이스 클래스가 남아 있다.

최종 후보였던 `stage-safe-field-counter` 계열은 커밋 이력상 2026-05-01에 별도 회귀 테스트와 함께 추가됐다. 이름 그대로 거리별(stage) 안정성과 필드 카운터 성격을 강조한다. 같은 날 `통계 익스플로잇 전략`, `신규 전략과 기록 옵션`, `전략 평가와 HUD`가 추가되어, "전략을 만들고 바로 실서버/벤치마크로 비교한다"는 흐름이 강화됐다.

의사결정 시그널은 전략마다 조금씩 다르지만, 대체로 카드/보드 평가(`core`, `strategy/analysts`), 포지션, 팟오즈, SPR, 상대 성향, 보드 텍스처, 블로커, 스택 상황을 본다. 논문에서 말하는 equilibrium solver를 그대로 만든 것은 아니다. 대신 상대 모델링, regret/equilibrium 관점, exploit 안정성을 대회 시간 안에 돌릴 수 있는 작은 규칙으로 낮췄다. `docs/STRATEGY_GUIDE.md`는 현재 등록 전략 31개를 쉬운 설명으로 정리하고 있어, 실제 운용도 "하나의 완성 전략"보다 "상황별 후보군의 실험과 선택"에 가깝다.

평가 루프도 따로 만들었다. `src/holdem_agent/benchmark.py`는 `.omc/autoresearch/holdem-practical-strategy-search/.../evaluations` 아래 평가 산출물을 남기고, 각 전략을 최소 100개 이상의 결정 시나리오에서 반복 평가한다. 실서버에서는 `--hud`, `--record-jsonl`, curl deploy/test 흐름을 붙여 후보 전략을 실제 게임에 넣었다. 요약하면 "논문 조사 → 후보 전략 생성 → 다른 전략과 대결 → 성적이 괜찮은 성질을 다음 후보에 반영"하는 식이었다.

### 논문 근거와 전략 매핑

아래 표는 "논문을 그대로 구현했다"는 뜻은 아니다. Codex GPT-5.5가 논문에서 뽑은 원리를 대회 시간 안에 실행 가능한 휴리스틱으로 바꾼 흔적이다.

| 연구 흐름 | 확인한 근거 | README/코드에 반영된 전략 아이디어 |
|---|---|---|
| Bayesian opponent modelling | [`Bayes' Bluff: Opponent Modelling in Poker`](https://arxiv.org/abs/1207.1411)은 포커의 불확실성을 게임 동역학과 상대 전략 불확실성으로 나누고, 관측으로 상대 전략 posterior를 추론한 뒤 대응하는 접근을 제시한다. | `bayesian-exploit`는 상대별 VPIP/PFR/aggression/fold/call을 smoothing하고, 표본과 confidence가 충분할 때만 overfolder/nit/station/maniac leak을 공격한다. |
| CFR / MCCFR | [`Monte Carlo Sampling for Regret Minimization in Extensive Games`](https://papers.neurips.cc/paper/3713-monte-carlo-sampling-for-regret-minimization-in-extensive-games)는 큰 extensive-form game에서 sample-based CFR 계열을 설명한다. | 전체 game-tree solver는 만들지 않았지만, `gto-baseline`, `hybrid-gto`, `omni`는 균형 기준선을 먼저 두고 이후 opponent/read 기반 exploit을 얹는 구조로 설계됐다. |
| Deep CFR | [`Deep Counterfactual Regret Minimization`](https://arxiv.org/abs/1811.00164)은 deep neural network로 CFR 동작을 근사해 큰 포커 게임에서 성능을 보이는 방향을 제시한다. | neural solver 대신 `StrategyGenome`과 benchmark를 사용해 c-bet, bluff, raise size, threshold를 전략 후보별 파라미터로 분리했다. |
| DeepStack | [`DeepStack: Expert-level artificial intelligence in heads-up no-limit poker`](https://pubmed.ncbi.nlm.nih.gov/28254783/)는 매 decision마다 continual re-solving을 수행하는 방향의 heads-up no-limit poker AI다. | `omni`, `arena-*`는 한 번 만든 고정 룰보다 현재 보드 텍스처, blocker, SPR, self-image, short-stack 상태를 매 decision에서 재평가한다. |
| Libratus | [`Libratus: The Superhuman AI for No-Limit Poker`](https://www.ijcai.org/Proceedings/2017/772) 및 Science 논문 요약은 blueprint strategy, subgame solving, self-improvement 흐름을 보여준다. | `arena-*` 후보군은 하나의 skeleton에서 profile 값만 바꿔 여러 후보를 만들고, benchmark/live 결과로 다음 후보 설계를 조정하는 방식에 영향을 줬다. |
| Pluribus | [`Superhuman AI for multiplayer poker`](https://pubmed.ncbi.nlm.nih.gov/31296650/)는 6-player no-limit Texas hold'em에서 top human professionals보다 강한 AI를 제시한다. | 이 대회가 multi-player 환경이라는 점 때문에 HU solver를 그대로 따라가지 않고, 필드 전체의 leak을 겨냥하는 `dominance-*`, `statistical-*`, `stage-safe-field-counter` 쪽으로 확장했다. |
| Bandit / confidence-bound selection | [`A Tutorial on Thompson Sampling`](https://arxiv.org/abs/1707.02038), [`lil' UCB`](https://proceedings.mlr.press/v35/jamieson14.html)는 불확실한 후보 중 좋은 arm을 찾는 exploration/exploitation 관점을 제공한다. | `statistical-lcb-fusion`과 benchmark report의 lower-confidence-bound 점수화는 운 좋은 후보보다 표본이 작아도 안정적인 후보를 고르는 방향으로 쓰였다. |
| Small-sample confidence intervals | [`Approximate is Better than "Exact" for Interval Estimation of Binomial Proportions`](https://www.tandfonline.com/doi/abs/10.1080/00031305.1998.10480550)는 Wilson score interval이 작은 표본에서도 nominal coverage에 가까운 결과를 준다고 설명한다. | `BayesianOpponentProfile`의 Wilson lower bound와 `statistical-lcb-fusion`의 보수 평가 철학은 "초반에 좋아 보이는 전략/상대 read를 과신하지 않기" 위한 장치로 연결된다. |

## 3. 사용한 AI 도구 · 개발 과정

- **주요 도구**: 전략 구현과 리팩터링은 전반적으로 **Codex GPT-5.5** 기반으로 진행했다. Claude Code 계열 흔적은 주로 `/oh-my-claudecode:autoresearch` 같은 워크플로 이름과 `CLAUDE.md` 행동 지침 참고로 남아 있다.
- **개발 방식**: 논문/레퍼런스 조사 → 초기 스캐폴딩 → 테스트 추가 → 서버 프로토콜 보정 → 실서버 실행 프롬프트 축적 → 전략 후보 확장 → 후보 간 대결 평가 → 실전 후보 좁히기.
- **근거**: 2026-04-18에 core/client/engine/model/strategy 계층이 연속 커밋으로 만들어졌고, 2026-05-01에는 전략 평가, HUD, 신규 전략, 통계 전략, stage-safe-field-counter가 집중적으로 추가됐다.

AI에게 일을 맡기는 방식도 따로 정했다. 프로젝트 루트의 `CLAUDE.md`는 [`multica-ai/andrej-karpathy-skills`의 `CLAUDE.md`](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md)를 참고했다. 핵심은 **Think Before Coding**, **Simplicity First**, **Surgical Changes**, **Goal-Driven Execution** 네 가지였다. 일단 많이 만들기보다, 가정과 tradeoff를 먼저 드러내고, 요청 범위 밖의 추상화를 줄이고, 변경한 줄이 목표와 연결되게 하고, 마지막은 테스트나 벤치마크로 닫게 하려는 목적이었다.

이 규칙은 포커 전략 생성에도 영향을 줬다. autoresearch가 논문 아이디어를 많이 가져오더라도, 바로 큰 solver나 프레임워크로 가지 않고 `bayesian-exploit`, `arena-*`, `stage-safe-field-counter`처럼 작게 검증 가능한 전략 후보로 나누게 했다. "논문 기반"이라는 말을 붙이기 위해 복잡도를 늘린 것이 아니라, 논문에서 얻은 가설을 최소 구현으로 만들고 실제 게임/benchmark 결과를 보는 쪽에 가까웠다.

참고한 연구 흐름은 대략 여섯 가지였다.

1. **Bayesian opponent modelling** — `Bayes' Bluff: Opponent Modelling in Poker`(arXiv:1207.1411). 상대의 전략 불확실성과 게임 상태 불확실성을 분리해 모델링한다는 발상은 `bayesian-exploit`의 "표본이 충분할 때만 overfolder/station/maniac leak을 exploit"하는 설계로 번역됐다.
2. **CFR / Deep CFR 계열** — 불완전정보 게임에서 regret minimization으로 균형에 가까운 전략을 찾는 흐름. 전체 CFR solver를 구현하진 않았지만, `gto-baseline`/`hybrid-gto`의 균형 기준선과 `arena-*` 후보의 국소 휴리스틱 비교 프레임에 영향을 줬다.
3. **DeepStack / Libratus 계열 포커 AI** — 거대한 사전 전략 하나보다, 현재 public state에서 재평가하고 취약점을 보완하는 접근. 이 프로젝트에서는 그것을 실서버 후보 대결과 로컬 decision-quality benchmark로 낮춰 구현했다.
4. **Pluribus 계열 multi-player poker** — heads-up 전용 전략을 그대로 쓰지 않고 6명 필드의 leak과 table dynamic을 보는 `dominance-*`, `statistical-*`, `stage-safe-field-counter` 후보군으로 확장하는 근거가 됐다.
5. **Thompson sampling / UCB류 bandit 선택** — 여러 후보 전략을 arm처럼 보고, 불확실성이 큰 전략보다 lower-confidence-bound가 안정적인 후보를 남기는 평가 철학에 영향을 줬다.
6. **Wilson/LCB식 보수 평가** — 적은 표본에서 승률이 좋아 보이는 후보를 과신하지 않기 위해 `statistical-lcb-fusion`처럼 보수적 하한을 쓰는 방향으로 반영했다.

### 라운드별 봇 교체 이력

라운드 번호가 커밋이나 문서에 명시되어 있지는 않다. 현재 자료로 확실히 말할 수 있는 것은 "봇 파일 단위 교체"가 아니라 **`--strategy` 선택값을 바꾸며 후보를 교체한 운영**이었다는 점이다.

| 구간 | 실행/검증 후보 | 근거 |
|---|---|---|
| 초기 | `calling-station`, `tight-aggressive`, `gto-baseline`, `aggressive`, `adaptive`, `hybrid-gto` | `docs/prompt.txt`에 여러 봇 슬롯으로 기본 전략을 비교하는 실행 예시가 남아 있음. |
| 중기 | `omni`, `hybrid-gto`, `gto-baseline`, `anti-maniac-trapper`, `dominance-wet-board-protector` | 전략 평가/HUD 도입 이후 실전 실행 후보가 넓어짐. |
| 후기/최종 후보 | `stage-safe-field-counter`, `learning-field-exploit`, `robust-field-exploit`, `bayesian-exploit`, `omni`, `hybrid-gto`, `gto-baseline`, `anti-maniac-trapper`, `dominance-wet-board-protector` | `docs/prompt-04.txt`에 final-like 실행 묶음이 남아 있음. 공유본에서는 실토큰 때문에 해당 파일은 제외했다. |

### 3-A. 도구·에이전트 사용 양상

**슬래시 커맨드 사용 빈도**

정확한 세션 로그 원본 전체는 이 공유 폴더에 포함하지 않았다. 다만 보존 문서 기준으로 `/oh-my-claudecode:deep-interview`와 `/oh-my-claudecode:autoresearch`가 명시적으로 등장한다. 실제 전략 구현과 코드화는 Codex GPT-5.5에서 진행했고, 의도는 "기존 전략을 모두 이길 새 전략 10개를 만들고 충분히 게임을 돌려 압도적 전략을 고른다"였다.

여기서 autoresearch는 단순 검색보다는 "논문에서 본 아이디어를 이 대회용 후보 전략으로 바꾸기"에 가까웠다. 논문에서 얻은 아이디어를 `bayesian-exploit`, `statistical-lcb-fusion`, `arena-*`, `stage-safe-field-counter` 같은 전략 이름으로 구체화하고, 다시 `evaluate`/실서버 대결에서 성능을 확인한 뒤 다음 후보군을 만드는 식으로 사용했다.

**MCP 도구 호출 양상**

공유 가능한 코드/문서에는 MCP 호출 로그가 직접 남아 있지 않다. 현재 자료상 확인 가능한 것은 외부 서버 WebSocket 실행, curl 기반 deploy/test 호출, 로컬 pytest/benchmark 검증 흐름이다.

**서브에이전트·역할 사용**

`docs/prompt.txt`에는 "각각 서브 에이전트 형식으로 실행을 하고 로그들을 감시 분석을 하고 도중에 계속 레포트를 작성"하라는 운영 지시가 남아 있다. 이후 코드에는 HUD(`--hud`), record JSONL(`--record-jsonl`), benchmark/evaluate 명령이 추가되어 다중 후보 감시·평가를 코드 레벨로 흡수했다.

**자동화 vs 대화 비중**

큰 방향은 자동화 쪽이었다. 전략 후보를 여러 개 만들고, 같은 서버에서 장시간 게임을 돌리고, 로그·HUD·벤치마크로 비교하는 요청이 반복된다. 반면 세부 실패 대응은 짧은 대화형 지시("이거 실행 테스트 해줘. 안되네")로 들어온 흔적이 있다.

## 4. 프롬프트 스타일

### (a) 메타 규칙

1. **실전 평가 우선**: "최소한 500판", "충분히 진행", "누가 가장 우수한지 평가"처럼 단발 테스트보다 많은 게임 수를 요구한다.
2. **동시 후보 비교**: 한 전략을 고집하기보다 같은 봇 슬롯/서버에서 여러 전략을 나열해 비교한다.
3. **자동 실행 + 로그 감시**: 실행, deploy/test, 로그 감시, 중간 레포트를 한 묶음으로 요청한다.
4. **실패 기반 반복**: 실행 예시 뒤에 "안되네"처럼 실패를 바로 다음 수정 루프로 넘긴다.
5. **CLAUDE.md 행동 규칙**: `andrej-karpathy-skills`의 `CLAUDE.md`를 참고해 "생각 먼저, 단순하게, 필요한 부분만 바꾸고, 검증 기준을 세우고 반복"하는 규칙을 프로젝트 지침으로 깔았다. 그래서 새 전략을 만들 때도 큰 구조 변경보다 작은 후보 전략 + 회귀 테스트 + benchmark 결과를 선호했다.

### (b) 자주 쓰는 표현 패턴

- "실행하고 각 bot_id를 실행해서 실제 게임 진행을 해서 누가 가장 우수한지 평가해보자."
- "전략을 10개를 만들고 ... 압도적인 승리를 하는 전략을 선정"
- "이거 실행 테스트 해줘. 안되네"

### (c) 결정적이었던 프롬프트

토큰이 포함된 원문은 공유 폴더에서 제외했으므로 민감값은 `<BOT_API_TOKEN>`으로 대체한다.

```text
기존 전략들을 모두 이길 수 있는 새로운 전략을 10개를 만들고자 합니다.
하나씩 새로운 전략을 만들고 게임을 충분히 진행해서 압도적인 승리를 하는 전략을 선정을 해야 합니다.
@docs/prompt-02.txt 에 있는 내용을 참고해서 계속 실전에서도 유용하게 동작하는 전략을 만들어내도록 하세요.
```

```text
실행하고 각 bot_id를 실행해서 실제 게임 진행을 해서 누가 가장 우수한지 평가해보자.
그런데 게임을 최소한 500판은 진행하고 종료하세요.
```

```text
이들은 각각 서브 에이전트 형식으로 실행을 하고 로그들을 감시 분석을 하고 도중에 계속 레포트를 작성하세요.
```

프로젝트 운영 지침 쪽에서는 `CLAUDE.md`가 꽤 중요했다. 외부 참고 문서의 핵심 구조를 가져와 "가정 명시 → 단순 구현 → 변경 범위 제한 → 검증 루프"를 AI 협업의 기본값으로 만든 것이, 이후 전략 후보 생성 방식에도 영향을 줬다.

### (d) 자주 등장한 키워드

전략, 실행, 테스트, 실제 게임, 평가, bot_id, deploy, 로그, 서브 에이전트, autoresearch, 논문, Bayesian, CFR, CLAUDE.md, 단순성, surgical change, 500판, 압도적인 승리, 실전, 후보, HUD, benchmark.

도메인 어휘보다 **운영·검증·자동화 어휘** 비중이 높다. 다만 전략 후보를 만들 때는 Bayesian opponent modelling, CFR류 균형 탐색, LCB, exploit 같은 논문/알고리즘 어휘가 섞인다. 포커 이론을 길게 손으로 설명하기보다 "논문 조사로 후보를 만들고, 충분히 돌려서 이기는 전략을 고르자"는 쪽에 가까웠다.

### (e) 초기 가설 + 프롬프트 톤

초기 가설은 "기본 전략 여러 개를 같은 서버에서 돌려 우수 전략을 찾자"였다. 이후 autoresearch로 논문 기반 전략 후보를 만들고, "새 전략 10개 생성", "stage-safe-field-counter", "dominance", "statistical exploit"로 확장되면서 가설이 단일 전략 개선에서 **논문 기반 후보군 탐색 + 대결 기반 선택**으로 넓어졌다.

프롬프트 톤은 명령형 70%, 위임·질문형 30% 정도로 보인다. 목표와 검증 조건은 사용자가 강하게 잡고, 구체 구현과 전략 생성은 AI에게 맡기는 형태다.

## 5. 돌리는 방법

### 설치

```bash
cd B-lab-holdem-bots/mineru
python -m pip install -r requirements.txt
```

이 프로젝트의 `pyproject.toml`은 Python `>=3.14`를 요구한다. `uv`를 쓰는 경우:

```bash
uv sync
```

### 로컬 벤치마크

```bash
./run.sh evaluate
./run.sh evaluate stage-safe-field-counter
uv run holdem-agent evaluate --strategy stage-safe-field-counter --games 100 --no-artifact
```

### 실서버 실행

```bash
export HOLDEM_API_TOKEN="<BOT_API_TOKEN>"
./run.sh play ws://<target_url>/ws "네루" stage-safe-field-counter
```

또는 직접:

```bash
uv run holdem-agent play ws://<target_url>/ws "네루" \
  --strategy stage-safe-field-counter --verbose --hud
```

`HOLDEM_API_TOKEN`이 없으면 토큰을 두 번째 인자로 직접 넘기는 CLI 형태도 지원한다:

```bash
uv run holdem-agent play ws://<target_url>/ws "<BOT_API_TOKEN>" "네루" \
  --strategy stage-safe-field-counter --verbose --hud
```

## 6. 시행착오 · 회고

사용자 회고 입력이 별도로 제공되지 않았다. 아래 항목은 원문 입력이 없는 상태를 그대로 표시한다.

**도메인 지식**

- 홀덤에 대해 아는 정도: `미입력`
- 그 지식이 봇 만들기에 어떻게 작용했나: `미입력`

**시행착오**

- 실패한 접근 또는 폐기한 가설 (그 시점에 무엇을 보고 결정했는지): `미입력`
- 다음에 만든다면 바꿀 점: `미입력`
- 의외였던 깨달음: `미입력`

## 7. 회고 검토

### 회고 ↔ 자료 불일치

회고가 제공되지 않았기 때문에 불일치를 판정할 수 없다.

### 회고가 추측으로 남긴 항목 중 자료가 답을 주는 경우

자료를 보면 이 프로젝트는 처음부터 완성 봇 하나만 만든 흐름은 아니었다. 실행 가능한 전략 레지스트리와 평가 루프를 먼저 만들고, 그 뒤 후보 전략을 계속 추가해 나간 쪽에 가깝다. 커밋 이력에서도 `feat(strategy): 신규 전략과 기록 옵션 추가`, `feat(strategy): 통계 익스플로잇 전략 추가`, `feat(strategy): 아레나 전략군 등록`이 연속으로 확인된다.

논문 조사도 "읽고 끝"은 아니었다. 전략 구현과 코드화는 Codex GPT-5.5가 주도했고, `docs/prompt-03.txt`에는 autoresearch 호출이, `docs/prompt-04.txt`에는 `bayesian-exploit` 옆에 `https://arxiv.org/abs/1207.1411`이 직접 적혀 있다. 코드에는 `BayesianExploit`, `StatisticalLCBFusion`, `ArenaStrategy`가 남아 있어, 논문 기반 상대 모델링/보수적 exploit/후보군 대결이 실제 전략 이름과 테스트로 이어졌음을 보여준다.

### 회고에서 빠진 큰 사건

1. 토큰이 포함된 운영 프롬프트가 문서에 남아 있었고, 공유용 폴더에서는 `docs/prompt*.txt`를 제외했다.
2. 2026-05-01 하루에 HUD, 기록 옵션, 신규 전략군, 통계 전략, stage-safe-field-counter가 집중적으로 추가됐다.
3. 최종 운영은 봇 코드 교체보다 `--strategy` 선택값 교체에 가까웠다.
4. Codex GPT-5.5 기반 autoresearch로 논문 기반 후보를 만들고, 그 후보들을 다른 알고리즘과 반복 대결시켜 다음 전략의 재료로 삼는 루프가 코드 구조에 반영됐다.
5. `CLAUDE.md`로 AI 협업 규칙을 먼저 잡았다. 이 문서는 `multica-ai/andrej-karpathy-skills`의 `CLAUDE.md`를 참고했고, 과잉 구현을 막고 검증 중심으로 닫는 방식이 전략 개발 습관에 영향을 줬다.

섹션 7 검토 결과를 보고 섹션 6 회고를 정정할지 그대로 둘지 결정한 뒤 공유 레포에서 commit & push 하세요.
