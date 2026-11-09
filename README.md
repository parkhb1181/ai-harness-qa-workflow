# AI Harness & QA Workflow

AI 코딩 에이전트(Claude Code, Codex, Copilot 등)를 실제 프로젝트에 투입할 때의
하네스 설계와 QA 워크플로우 가이드.

- 규칙 파일(CLAUDE.md / AGENTS.md) 설계
- 실패 로그 → 규칙 → 스크립트 승격
- 완료 판정(Definition of Done)
- 리뷰 트리거, 서브에이전트 리뷰어
- PR 크기 상한, 테스트 오염 감시, 보안/샌드박스

전체 내용: [AI_HARNESS_QA_WORKFLOW.txt](./AI_HARNESS_QA_WORKFLOW.txt)

## 구현체

- [hobin-workflow](./hobin-workflow/): 이 가이드의 원칙(서브에이전트 리뷰어, 완료 판정, 범위 경계, 실패 기록)을 Claude Code 라우터-워커 실행기로 구현한 실험 버전
