# central/web — 프론트 (React)

Control Tower 웹 UI (멀티 탭: 대시보드·서버·버전빌드·설정·업데이트·CI/CD·작업이력).
PLAN의 "UI — 페이지 구성" 참고.

- 지금은 `placeholder.html` + nginx 로 compose 배선만 확인.
- 추후: Vite + React 스캐폴드 → 빌드 산출물을 nginx 로 서빙(멀티스테이지 Dockerfile).
- API 연동: 같은 compose 네트워크의 `api:8000` (또는 리버스 프록시로 `/api`).

## 디자인 참고

**Apple 스타일 디자인 시스템**을 UI/UX 기준으로 삼는다 → [`../../docs/DESIGN-apple.md`](../../docs/DESIGN-apple.md).

- **가져올 것**: 단일 블루 액센트(`#0066cc`), SF Pro(대체 Inter), 17px 본문, 플랫(장식·그림자 없음), pill CTA·radius 문법, 넉넉한 여백.
- **적용 시 조정**: Apple 원본은 **저밀도 마케팅 사이트**라 그대로 쓰면 대시보드에 안 맞는다. 표·버전 매트릭스·서버 리스트가 많은 Control Tower는 **정보 밀도를 높여** 디자인 '언어'만 차용(전면 타일 갤러리 레이아웃은 지양). 라이트/다크는 그대로 활용.
