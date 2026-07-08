# 주간 퀀트 리밸런싱 대시보드 (paju-quant-weekly)

김민겸(2025 IQC 우승)의 전략 개념을 축소한 학습용 퀀트 시스템.
3-알파(평균회귀·모멘텀·저PBR) + 거시 국면 스위칭 + 주간 리밸런싱을
단일 HTML 대시보드로 시각화합니다.

> ⚠️ **학습·연구용 도구입니다. 투자 권유가 아니며, 모든 투자 판단과 책임은 본인에게 있습니다.**

## 구성

| 파일 | 역할 | 실행 주기 |
|---|---|---|
| `index.html` | 대시보드 (GitHub Pages로 서빙) | 브라우저로 열람 |
| `collect_data.py` | 시세·PBR·지수 수집 → `market_data.json` | 주 1회 (토요일 권장) |
| `collect_fundamentals.py` | DART 자본총계 수집 → `fundamentals.json` | 분기 1회 |
| `config.example.json` | 키 설정 템플릿 | 최초 1회 복사 |

## 최초 설정

```bash
pip install pykrx requests

# 1) 키 설정 (config.json은 gitignore 처리되어 커밋되지 않음)
cp config.example.json config.json
# → config.json 열어서 DART 키 입력

# 2) KRX 로그인 (data.krx.co.kr 무료 회원가입 후)
export KRX_ID="아이디"
export KRX_PW="비밀번호"
```

## 주간 워크플로우

```bash
python collect_data.py          # 5~15분 소요
git add market_data.json
git commit -m "data: 주간 갱신 $(date +%Y-%m-%d)"
git push
```

푸시하면 GitHub Pages가 자동 갱신 → 스마트폰에서
`https://<계정>.github.io/<저장소>/` 접속으로 확인.

분기마다 한 번 `python collect_fundamentals.py` 추가 실행 (PBR 보조 데이터).

## 데이터 출처

- 시세·PBR: pykrx (KRX/네이버, 참고용)
- 재무: DART 오픈API
- 기준금리: 수동 입력 → 추후 한국은행 ECOS 연동 예정

## 알고리즘 요약

- 유니버스: 코스피200 시총 상위 50
- 알파: α1 단기 평균회귀(-rank 5일수익률) / α2 중기 모멘텀(rank 60일, 최근 5일 제외) / α3 저PBR
- 국면: 기준금리 vs 3년 중앙값 × KOSPI200 200일선 기울기 → 4국면별 알파 가중치 스위칭
- 포트폴리오: 종합점수 상위 10종목 롱온리, 종목당 최대 15%, 주간 리밸런싱
- 백테스트: 거래비용 왕복 0.3% 반영, 샤프·MDD·승률 산출
