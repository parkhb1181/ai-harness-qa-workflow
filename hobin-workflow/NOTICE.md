# 참고한 설계

hobin의 코드는 새로 작성했습니다. 아래 프로젝트와 글의 코드를 복사하지 않았고, 설계 아이디어를 참고했습니다.

| 출처 | 가져온 생각 |
|---|---|
| [deepseek-ai/dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype) (MIT) | 사람의 주의력을 최소로 쓰는 원칙, 라우터는 구현하지 않고 원문을 그대로 넘김, 티켓당 세션 하나와 후속 요청의 같은 세션 재개, 워커 자리 수 제한, 보고 상태(ready/blocked/failed/dropped), 감시를 코드로 처리 |
| [yingpengma/cc-super-agent](https://github.com/yingpengma/cc-super-agent) (MIT) | Claude Code 기본 기능(`claude -p`, `--session-id`, `--resume`, `--append-system-prompt`)만으로 구성, 상태를 디스크에 두기, 사람의 수정 이력을 기록으로 남기기 |
| [Kevin-Pal/cc-codex-super-agent](https://github.com/Kevin-Pal/cc-codex-super-agent) (MIT) | 검토자는 구현자의 맥락을 물려받지 않은 깨끗한 세션, 다른 세션에 영향을 주는 결정은 공유 문서에 한 곳만 기록 |
| [Claude Code 문서: Agent teams](https://code.claude.com/docs/en/agent-teams) | 팀원마다 다른 파일 묶음을 맡겨 덮어쓰기 방지, 작업 가져가기에 파일 잠금 |
| [Cognition: Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) | 서로 모르는 에이전트에게 연결된 일을 나누면 결정이 충돌한다는 경고 → 경로 겹침 직렬화, 계약 먼저 |
| 멀티 에이전트 충돌 연구 정리 ([글](https://codex.danielvaughan.com/2026/06/06/multi-agent-coordination-problem-concurrent-agents-semantic-conflicts-codex-cli/)) | 파일 소유권, 계약 먼저, 먼저 끝난 것부터 병합, 위계 조정이 대등 협상보다 나음 |
