#!/usr/bin/env python3
"""테스트용 가짜 `claude -p`. 실제 CLI와 같은 stream-json 형식으로 응답한다.

티켓별 시나리오를 회차마다 하나씩 소비한다. 상태는 FAKE_STATE 폴더에 남긴다.
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

STATE = Path(os.environ["FAKE_STATE"])
STATE.mkdir(parents=True, exist_ok=True)


def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else default


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(msg):
    """실제 워커는 git을 쓸 수 없다 (막혀 있음). 커밋은 hobin이 한다."""


def report(**kw):
    base = {"summary": "", "verified": [], "risks": [], "decisions": [], "learnings": []}
    base.update(kw)
    return "작업 결과입니다.\n\n```json\n" + json.dumps(base, ensure_ascii=False) + "\n```"


def verdict(v, items=None):
    return "검증 결과\n```json\n" + json.dumps({"verdict": v, "items": items or [{"item": "기준", "result": v, "evidence": "fake"}],
                                                 "other_issues": []}, ensure_ascii=False) + "\n```"


INTEG = "hobin/integration"
LOSE_SESSION = []

# 티켓별 워커 회차 시나리오 (함수 목록). 반환값은 마지막 메시지 텍스트.
def t001_1(prompt):
    write("src/a.txt", "hello\n")  # 커밋은 hobin이 한다
    write("src/__pycache__/a.cpython-313.pyc", "bytecode")  # 실행 부산물: 변경으로 치면 안 됨
    return report(status="ready", summary="a 추가", learnings=["a.txt는 줄 단위로 읽는다"])

def t002_1(prompt):
    write("src/b/x.txt", "x\n"); write("README.md", "touched\n"); commit("b + 경로 밖"); return report(status="ready")

def t002_2(prompt):
    assert "되돌렸습니다" in prompt and "README.md" in prompt, prompt
    return report(status="ready")

def t002_3(prompt):
    assert "독립 검증" in prompt, prompt
    write("src/b/x.txt", "x fixed\n"); commit("검증 지적 수정"); return report(status="ready", decisions=["b 모듈은 UTF-8만 받는다"])

def t003_1(prompt):
    return report(status="blocked", question="파일 이름을 c.txt로 할까요? (추천: 예)")

def t003_2(prompt):
    assert "[사람]" in prompt, prompt
    write("src/c.txt", "c\n"); commit("c"); return report(status="ready")

def t004_1(prompt):
    # T-001이 병합된 통합 브랜치에서 시작했는지 확인
    assert Path("src/a.txt").read_text() == "hello\n", "선행 티켓 결과가 없음"
    write("src/a.txt", "hello\nworld\n"); commit("a 확장"); return report(status="ready")

def t005_1(prompt):
    LOSE_SESSION.append(True)  # 이 세션이 사라진 상황도 함께 시험한다
    return "보고 블록을 깜빡했습니다."

def t005_2(prompt):
    assert "보고 블록" in prompt, prompt
    write("docs/guide.md", "guide\n"); commit("guide"); return report(status="ready")

def t006_1(prompt):
    write("docs/extra.md", "extra\n"); commit("extra"); return report(status="ready")

def t007_1(prompt):
    write("lib/z.txt", "A\n"); commit("z by worker")
    # 다른 누군가가 통합 브랜치에 같은 파일을 먼저 넣은 상황을 흉내 낸다
    cfg = json.loads((Path(os.environ["FAKE_REPO"]) / ".hobin" / "config.json").read_text())
    integ_wt = Path(cfg["worktree_root"]) / "_integration"
    import fcntl
    with open(Path(os.environ["FAKE_REPO"]) / ".hobin" / "locks" / "merge.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)  # hobin의 병합과 겹치지 않게
        write(integ_wt / "lib/z.txt", "B\n")
        subprocess.run(["git", "add", "-A"], cwd=integ_wt, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.email=h@x", "-c", "user.name=human", "commit", "-q", "-m", "human z"], cwd=integ_wt, check=True)
    return report(status="ready")

def t007_2(prompt):
    assert "충돌" in prompt and "lib/z.txt" in prompt, prompt
    assert "<<<<<<<" in Path("lib/z.txt").read_text(), "충돌 표시가 있어야 함"
    write("lib/z.txt", "A+B\n")  # 충돌 표시만 해결, git 명령 없음
    return report(status="ready")

def t008_1(prompt):
    write(".github/workflows/ci.yml", "on: push\n")           # 점으로 시작하는 경로
    write("docs/한글 문서/가이드 1.md", "한글 파일, 공백 포함\n")  # 비ASCII, 공백
    return report(status="ready")

def t009_1(prompt):
    write("pkg/core.py", "x = 1\n")
    write("dist/bundle.js", "build output\n")  # 경로 밖 새 파일(빌드 출력): 조용히 지워져야 함
    return report(status="ready")

def t011_1(prompt):
    write("bin2/data.bin", "\0\1worker")  # 바이너리
    cfg = json.loads((Path(os.environ["FAKE_REPO"]) / ".hobin" / "config.json").read_text())
    integ_wt = Path(cfg["worktree_root"]) / "_integration"
    import fcntl
    with open(Path(os.environ["FAKE_REPO"]) / ".hobin" / "locks" / "merge.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        write(integ_wt / "bin2/data.bin", "\0\2human")
        subprocess.run(["git", "add", "-A"], cwd=integ_wt, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.email=h@x", "-c", "user.name=human", "commit", "-q", "-m", "human bin"], cwd=integ_wt, check=True)
    return report(status="ready")

def t010_1(prompt):
    write("ui/page.html", "<h1>hi</h1>\n")
    return report(status="ready")

WORKER = {
    "T-001": [t001_1], "T-002": [t002_1, t002_2, t002_3], "T-003": [t003_1, t003_2],
    "T-004": [t004_1], "T-005": [t005_1, t005_2], "T-006": [t006_1], "T-007": [t007_1, t007_2],
    "T-008": [t008_1], "T-009": [t009_1], "T-010": [t010_1, t010_1], "T-011": [t011_1],
}

# 견고성 시험용 (FAKE_MODE=robust)
def r_silent(prompt):
    time.sleep(float(os.environ.get("FAKE_SILENT", "8")))  # 아무것도 출력하지 않고 멈춤
    return report(status="ready")

def r_quick(prompt):
    if os.environ.get("FAKE_DROP_AFTER") and CUR["n"] >= int(os.environ["FAKE_DROP_AFTER"]):
        return report(status="dropped", summary="바꿀 것 없음")
    if os.environ.get("FAKE_EVIL"):
        # 워커가 실행한 (테스트) 코드가 공유 .git/config에 명령을 심는 상황
        subprocess.run(["git", "config", "--file", os.path.join(os.environ["FAKE_REPO"], ".git", "config"),
                        "core.fsmonitor", "/tmp/evil.sh"], check=True)
    write(f"r/{CUR['tid']}.txt", f"ok {CUR['n']}\n")
    if os.environ.get("FAKE_DAEMON"):
        # 워커가 백그라운드 데몬(개발 서버 등)을 띄운 상황. 부모의 파일 서술자를 그대로 물려받는다.
        subprocess.Popen(["sleep", "30"], start_new_session=True, close_fds=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return report(status="ready")

CUR = {}
VERIFIER = {  # 회차별 판정
    "T-002": ["fail", "pass"],
}


def main():
    prompt = sys.stdin.read()
    system = arg("--append-system-prompt", "")
    role = "verifier" if "HOBIN_ROLE: verifier" in system else "worker"
    sid = arg("--session-id") or arg("--resume") or str(uuid.uuid4())
    sdir = STATE / "sessions"  # 세션마다 파일 하나 (동시 실행에도 안전)
    sdir.mkdir(exist_ok=True)
    sfile = sdir / sid
    if os.environ.get("FAKE_ALWAYS_LOST"):
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": sid,
             "errors": ["No conversation found with session ID: " + sid]})
        with open(STATE / "calls.log", "a") as fh:
            fh.write("x\n")
        return
    if arg("--resume") and not sfile.exists():
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": sid,
             "errors": ["No conversation found with session ID: " + sid]})
        return
    m = re.search(r"T-\d{3}", prompt)
    tid = sfile.read_text() if sfile.exists() else (m.group(0) if m else "?")
    if role == "worker":
        sfile.write_text(tid)
    counter = STATE / f"{tid}.{role}.count"
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    with open(STATE / "timeline.log", "a") as fh:
        fh.write(f"{time.time():.3f} start {tid} {role}\n")
    out({"type": "system", "subtype": "init", "session_id": sid, "cwd": os.getcwd()})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "ticket.md"}}]}})
    time.sleep(0.6)
    CUR["tid"], CUR["n"] = tid, n
    if role == "worker":
        if os.environ.get("FAKE_MODE") == "robust":
            text = (r_silent if os.environ.get("FAKE_SILENT") else r_quick)(prompt)
        else:
            text = WORKER[tid][min(n, len(WORKER[tid]) - 1)](prompt)
    else:
        if tid == "T-001":
            write("verifier-junk.txt", "should be removed\n")  # 검증자가 파일을 건드리는 상황
        plan = VERIFIER.get(tid, ["pass"])
        if tid == "T-010" and os.environ.get("FAKE_MODE") != "robust":
            text = verdict("pass", [{"item": "화면 확인", "result": "unverified", "evidence": "브라우저 없음"},
                                    {"item": "파일 존재", "result": "pass", "evidence": "ls ui/page.html"}])
        else:
            text = verdict(plan[min(n, len(plan) - 1)])
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}]}})
    with open(STATE / "timeline.log", "a") as fh:
        fh.write(f"{time.time():.3f} end {tid} {role}\n")
    if LOSE_SESSION:
        sfile.unlink()
    out({"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": sid,
         "total_cost_usd": 0.01, "num_turns": 3, "permission_denials": []})


def out(ev):
    print(json.dumps(ev, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
