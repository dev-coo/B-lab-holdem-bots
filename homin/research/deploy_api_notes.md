# Deploy API — 인증 방식 메모 & 우회 절차

## Status
- **Stage**: Draft (blocking)
- **Created**: 2026-04-19 (Day 7)
- **Owner**: holdem-agent
- **Version**: 0.1
- **Maps to**: plan 평가 B4 (블로커), Week 2 D1 Day 7
- **BOT_GUIDE refs**: §1.1, §2.2

---

## 1. Context — 왜 블로커인가

BOT_GUIDE §2.2 발췌:
> 인증 성공 후 **대시보드에서 봇을 "실행"(deploy)** 해야 방에 배정됩니다. WS 접속만으로는 배정되지 않습니다. deploy는 REST API(`POST /bots/{id}/deploy`)로 수행합니다.

**현상**:
- `auth_ok` 이후에도 `hand_start` 이벤트 도착 없음.
- 대시보드 UI 로그인 → 수동 "실행" 필요.
- `/bots/{id}/deploy` 의 **인증 헤더 형식 / id 발급 방식 / 요청 바디 스키마** BOT_GUIDE 에 미기재.

**영향**:
- 멀티룸 자동화 불가 (매번 수동 배포).
- CI/배포 파이프라인 미구성.
- Week 2 M1 마일스톤의 "한 게임 완주" 는 수동 배포로 대체.

---

## 2. 확인이 필요한 항목 (운영자 문의)

다음 7 개를 운영자에게 문의한다:

1. **API base URL**: `http://snn.it.kr:5051/bots/{id}/deploy` 인가 아니면 별도 도메인/포트?
2. **인증 헤더 형식**: `Authorization: Bearer {api_token}` ? 아니면 쿠키/세션 기반?
3. **`{id}` 의 의미**: 봇 이름? 내부 user_id? 대시보드 등록 시 발급되는 별도 ID?
4. **요청 바디**: 빈 body? `{"rooms": N}` 같은 파라미터 있는가?
5. **응답 스키마**: 성공 시 `{"deployed": true, "assigned_rooms": [...]}` ?
6. **idempotency**: 이미 deploy 된 봇에 재호출 시 동작 (reset? no-op?).
7. **recall (회수)**: 하드/소프트 리콜에 대응하는 REST 엔드포인트 존재?

---

## 3. 임시 우회 절차 (수동 deploy)

운영자 답신 전까지:

1. 봇 WS 연결 (auth_bot 성공까지 진행).
2. 브라우저에서 `http://snn.it.kr:5051` 대시보드 로그인.
3. "봇 관리" 에서 해당 봇 이름의 **실행** 버튼 클릭.
4. WS 이벤트 로그에 `joined_room` / `game_start` 도착 확인.
5. 한 게임 종료 후 자동으로 새 방 배정 (또는 수동 재배정).

**수동 우회의 한계**:
- 24/7 가동 불가.
- 재접속 시 다시 수동 deploy 필요할 수 있음 (토큰+이름 유지 시 자동 복원 여부 불명).
- A/B 테스트용 동시 다수 봇 운영 어려움.

---

## 4. 작성 시점 상태

- [ ] 운영자 채널 (Slack/이메일/대시보드 공지) 문의 전송
- [ ] 답신 수신
- [ ] `scripts/deploy_bot.py` 구현 (1~7 답변 반영)
- [ ] `.env` 에 `HOLDEM_DEPLOY_URL` 추가 여부 결정

위 4 항목 체크 완료 시 본 문서 **v0.2 Validated** 승격, Week 2 M1 마일스톤의 자동 배포 경로 확보.

---

## 5. Temporary code stub

`src/holdem/transport/deploy.py` (미구현):

```python
# TODO: 운영자 답신 후 구현
# async def deploy_bot(bot_id_or_name: str, api_token: str) -> dict:
#     headers = {"Authorization": f"Bearer {api_token}"}
#     url = f"{base}/bots/{bot_id_or_name}/deploy"
#     async with httpx.AsyncClient() as c:
#         resp = await c.post(url, headers=headers)
#         resp.raise_for_status()
#         return resp.json()
```

답신 도착 후 위 stub 을 구현하고 `ws_client.connect()` 이전에 호출 배치.

---

## Changelog

- 2026-04-19 (v0.1): Day 7 작성. 운영자 문의 항목 7개 정리, 임시 수동 우회 절차 문서화.
