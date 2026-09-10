# central/web — 프론트 (React)

Control Tower 웹 UI (멀티 탭: 대시보드·서버·버전빌드·설정·업데이트·CI/CD·작업이력).
PLAN의 "UI — 페이지 구성" 참고.

- 지금은 `placeholder.html` + nginx 로 compose 배선만 확인.
- 추후: Vite + React 스캐폴드 → 빌드 산출물을 nginx 로 서빙(멀티스테이지 Dockerfile).
- API 연동: 같은 compose 네트워크의 `api:8000` (또는 리버스 프록시로 `/api`).
