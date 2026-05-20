# <문서 제목>

## Status
- **Stage**: Draft
- **Created**: YYYY-MM-DD
- **Last updated**: YYYY-MM-DD
- **Owner**: <이름>
- **Version**: 0.1
- **Related configs**: `configs/<path>.yaml`
- **Related code**: `src/holdem/<path>.py`
- **Related BOT_GUIDE sections**: §X.Y, §X.Y

---

## 1. Objective

이 문서가 답하는 단일 질문:
>

---

## 2. BOT_GUIDE Compliance

이 연구가 준수하는 룰 (`research/bot_guide_extracts.md` 에서 인용):

- [§x.y] <룰 요약>
- [§x.y] <룰 요약>

**위배 위험과 방어**:
- <만약 이 연구의 해석이 룰과 어긋나면 어떻게 감지하는가>

---

## 3. Method

### 3.1 데이터
- **원천**: <경로, 라이선스, 샘플 수>
- **필터**:
- **전처리**:

### 3.2 절차
재현 가능한 명령어 시퀀스:
```bash
uv run python scripts/<xxx>.py --input <…> --output <…>
```

### 3.3 도구·버전
- `pandas==X.Y.Z`, `numpy==X.Y.Z`, `treys==X.Y.Z`

---

## 4. Results

수치·표·그림. 외부 이미지는 `research/_assets/<filename>.png` 에 보관.

---

## 5. Interpretation

### 5.1 핵심 발견

### 5.2 우리 서버로의 전이 가능성
BOT_GUIDE §8 (우리 서버 규칙) 대비 해석:

### 5.3 전이 불가능 영역
(예: HU 전용 파라미터이므로 full-ring 에 사용 금지)

---

## 6. Parameter Output

이 연구가 산출한 config 값:

```yaml
# configs/<path>.yaml 에 반영
<key>: <value>   # 근거: §4 Results
```

---

## 7. Limitations & Caveats

- <샘플 편향, 측정 오차, 전이 리스크>
- <>
- <>

---

## 8. Next Steps

- <이 결과로 촉발된 추가 연구>

---

## 9. References

- [1] `guide/BOT_GUIDE.md`
- [2] <논문·데이터셋·링크>

---

## Changelog

- YYYY-MM-DD (v0.1): 초안 작성
