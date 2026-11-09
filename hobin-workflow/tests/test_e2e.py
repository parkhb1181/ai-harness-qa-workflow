"""가짜 claude로 hobin 전체 흐름을 실제 git 저장소에서 돌려 본다.

python3 -m unittest discover -s tests -v
"""
import json
import os
import signal
import time
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
HOBIN = PKG / "bin" / "hobin"
FAKE = PKG / "tests" / "fake_claude.py"
sys.path.insert(0, str(PKG / "bin"))


def load_hobin_module():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("hobin_mod", str(HOBIN))
    spec = importlib.util.spec_from_loader("hobin_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class PathRules(unittest.TestCase):
    def setUp(self):
        self.t = load_hobin_module()

    def test_allowed(self):
        ok = self.t.path_allowed
        self.assertTrue(ok("src/auth/login.ts", ["src/auth/"]))
        self.assertTrue(ok("src/auth", ["src/auth"]))
        self.assertFalse(ok("src/authx/a.ts", ["src/auth"]))
        self.assertTrue(ok("src/a/b/c.ts", ["src/**/*.ts"]))
        self.assertTrue(ok("src/c.ts", ["src/**/*.ts"]))
        self.assertFalse(ok("src/c.js", ["src/**/*.ts"]))
        self.assertFalse(ok("README.md", ["src/"]))

    def test_overlap(self):
        ov = self.t.paths_overlap
        self.assertTrue(ov(["docs/"], ["docs/guide.md"]))
        self.assertTrue(ov(["src/**"], ["src/a.txt"]))
        self.assertFalse(ov(["src/a/"], ["src/b/"]))
        self.assertFalse(ov(["lib/"], ["docs/"]))

    def test_transitions_closed(self):
        for frm, tos in self.t.TRANSITIONS.items():
            for to in tos:
                self.assertIn(to, self.t.STATUS_LABEL, f"{frm}->{to}")


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "repo"
        cls.fake_state = Path(cls.tmp.name) / "fake"
        cls.repo.mkdir()
        cls.env = dict(os.environ, FAKE_STATE=str(cls.fake_state), FAKE_REPO=str(cls.repo),
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
        g = lambda *a: subprocess.run(["git", *a], cwd=cls.repo, check=True, capture_output=True, env=cls.env)
        g("init", "-q", "-b", "main")
        (cls.repo / "README.md").write_text("project\n")
        g("add", "-A")
        g("commit", "-q", "-m", "init")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tc(self, *args, check=True):
        p = subprocess.run([sys.executable, str(HOBIN), *args], cwd=self.repo, capture_output=True, text=True,
                           env=self.env, timeout=300)
        if check and p.returncode != 0:
            self.fail(f"hobin {' '.join(args)} 실패\n{p.stdout}\n{p.stderr}")
        return p

    def state(self, tid):
        return json.loads((self.repo / ".hobin" / "tickets" / tid / "state.json").read_text())

    def new(self, title, paths, *extra):
        return self.tc("new", title, "--paths", paths, "--eval", "기준을 만족한다", "--request", "원문", *extra).stdout.strip()

    def test_full_flow(self):
        hooks = self.repo / ".git" / "hooks"
        for name in ("pre-commit", "commit-msg", "post-checkout"):
            (hooks / name).write_text("#!/bin/sh\necho 'hook rejects' >&2\nexit 1\n")
            (hooks / name).chmod(0o755)
        self.tc("init", "--test-cmd", "test -f README.md", "--no-claude-files", "--skip-cli-check")
        cfg_path = self.repo / ".hobin" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg.update(claude_bin=f"{sys.executable} {FAKE}", max_workers=2)
        cfg_path.write_text(json.dumps(cfg))
        wtroot = Path(cfg["worktree_root"])
        self.assertFalse(str(wtroot).startswith(str(self.repo) + "/"), "작업 공간은 저장소 밖에 있어야 함")
        integ = wtroot / "_integration"

        t1 = self.new("a 추가", "src/a.txt", "--source", "jira:WEB-1", "--by", "홍길동")
        t2 = self.new("b 모듈", "src/b/")
        t3 = self.new("c 파일", "src/c.txt")
        t4 = self.new("a 확장", "src/a.txt", "--depends", "T-001")
        t5 = self.new("가이드", "docs/guide.md")
        t6 = self.new("추가 문서", "docs/")
        t7 = self.new("z 파일", "lib/")
        t8 = self.new("점 경로와 한글 파일", ".github/,docs/한글 문서/")
        t9 = self.new("pkg 코어", "pkg/")
        t10 = self.new("화면", "ui/")
        t11 = self.new("바이너리 충돌", "bin2/")
        self.assertEqual([t1, t11], ["T-001", "T-011"])

        # 입력값으로 메타데이터를 조작할 수 없다 (리뷰2 M4)
        self.assertEqual(self.tc("new", "제목\npaths: **\n---", "--paths", "x/", check=False).returncode, 2)
        self.assertEqual(self.tc("new", "넓은 경로", "--paths", "**", check=False).returncode, 2)
        self.assertEqual(self.tc("new", "밖", "--paths", "../other/", check=False).returncode, 2)

        # 승인 전에는 배정되지 않는다
        self.assertIn("시작할 티켓이 없습니다", self.tc("run").stdout)
        # 완료 기준 없는 티켓은 승인 불가
        bad = self.tc("new", "기준 없음", "--paths", "x/").stdout.strip()
        self.assertEqual(self.tc("ready", bad, check=False).returncode, 2)
        self.tc("drop", bad)

        self.tc("ready", t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11)
        self.tc("run", "--wait", "--interval", "0.3")

        s = {t: self.state(t)["status"] for t in [t1, t2, t3, t4, t5, t6, t7]}
        self.assertEqual(s[t1], "merged", self.tc("show", t1).stdout)
        self.assertEqual(s[t2], "merged", self.tc("show", t2).stdout)
        self.assertEqual(s[t3], "needs_human")
        self.assertEqual(s[t4], "merged", self.tc("show", t4).stdout)
        self.assertEqual(s[t5], "merged", self.tc("show", t5).stdout)
        self.assertEqual(s[t6], "merged")
        self.assertEqual(s[t7], "merged", self.tc("show", t7).stdout)

        # 편집으로 풀 수 없는 충돌(바이너리)은 워커가 아니라 사람에게 (리뷰2 M3)
        st11 = self.state(t11)
        self.assertEqual(st11["status"], "needs_human", self.tc("show", t11).stdout)
        self.assertIn("바이너리", st11["question"])

        # 실행 부산물(__pycache__)은 경로 위반으로 치지 않고 커밋하지도 않는다
        self.assertEqual(self.state(t1)["rounds"], 1, self.tc("show", t1).stdout)
        self.assertFalse((integ / "src/__pycache__").exists())

        # 점으로 시작하는 경로, 한글·공백 파일 이름 (리뷰 C1, C2)
        self.assertEqual(self.state(t8)["status"], "merged", self.tc("show", t8).stdout)
        self.assertEqual(self.state(t8)["rounds"], 1, self.tc("show", t8).stdout)
        self.assertTrue((integ / ".github/workflows/ci.yml").exists())
        self.assertTrue((integ / "docs/한글 문서/가이드 1.md").exists())

        # 경로 밖 새 파일(빌드 출력)은 회차를 낭비하지 않고 지워진다 (리뷰 M7)
        self.assertEqual(self.state(t9)["status"], "merged", self.tc("show", t9).stdout)
        self.assertEqual(self.state(t9)["rounds"], 1)
        self.assertFalse((integ / "dist").exists())

        # 검증자가 확인 못 한 항목이 있으면 병합하지 않고 사람에게 (리뷰 M2) → 사람 승인 후 병합
        st10 = self.state(t10)
        self.assertEqual(st10["status"], "needs_human", self.tc("show", t10).stdout)
        self.assertIn("화면 확인", st10["question"])
        self.assertEqual(self.tc("approve", t3, check=False).returncode, 2, "질문 대기 티켓은 approve 불가")
        self.tc("approve", t10)  # 사람이 직접 확인했다고 승인

        # T-002: 경로 위반 → 검증 실패 → 통과, 총 3회차, 같은 세션 이어감
        st2 = self.state(t2)
        self.assertEqual(st2["rounds"], 3)
        owners = [f.read_text() for f in (self.fake_state / "sessions").iterdir()]
        self.assertEqual(owners.count(t2), 1, "재작업은 같은 세션을 이어가야 함")

        # T-005: 보고 누락 → 세션 유실 → 새 세션으로 원본부터 다시 → 통과
        ev5 = (self.repo / ".hobin" / "runs" / t5 / "events.log").read_text()
        self.assertIn("새 세션으로 다시 시작", ev5)

        # 검증자가 만든 파일은 되돌려졌고 통합 브랜치에 들어가지 않았다
        self.assertFalse((integ / "verifier-junk.txt").exists())
        # 경로 밖 변경은 통합 브랜치에 들어가지 않았다
        self.assertEqual((integ / "README.md").read_text(), "project\n")
        # 선행 티켓 결과 위에서 작업했다
        self.assertEqual((integ / "src/a.txt").read_text(), "hello\nworld\n")
        # 충돌 후 재작업 결과
        self.assertEqual((integ / "lib/z.txt").read_text(), "A+B\n")
        # main은 건드리지 않았다
        self.assertFalse((self.repo / "src").exists())

        # 동시 실행 제한과 경로 겹침 규칙
        events = []
        for line in (self.fake_state / "timeline.log").read_text().splitlines():
            ts, kind, tid, role = line.split()
            events.append((float(ts), kind, tid))
        events.sort()
        running, peak, live = 0, 0, set()
        for ts, kind, tid in events:
            if kind == "start":
                live.add(tid)
            else:
                live.discard(tid)
            peak = max(peak, len(live))
            self.assertFalse({t5, t6} <= live, "경로가 겹치는 티켓이 동시에 실행됨")
            self.assertFalse({t1, t4} <= live, "선행 관계 무시")
        self.assertLessEqual(peak, 2)

        # 지식 기록 (단일 작성자: 코드)
        learn = (self.repo / ".hobin" / "knowledge" / "LEARNINGS.md").read_text()
        dec = (self.repo / ".hobin" / "knowledge" / "DECISIONS.md").read_text()
        self.assertIn("[T-001", learn)
        self.assertIn("[T-002", dec)

        # 사람 답변 → 같은 세션 재개 → 완료
        self.assertIn("c.txt", self.state(t3)["question"])
        self.tc("reply", t3, "네, c.txt로 해 주세요")
        self.tc("run", "--wait", "--interval", "0.3")
        self.assertEqual(self.state(t3)["status"], "merged")
        self.assertEqual(self.state(t10)["status"], "merged", self.tc("show", t10).stdout)
        self.assertEqual((self.fake_state / "T-010.worker.count").read_text(), "1", "승인 후에는 워커를 다시 돌리지 않음")
        self.assertTrue((integ / "ui/page.html").exists())

        # 보드, 감시, 완료 처리
        board = self.tc("status").stdout
        self.assertIn("jira:WEB-1", board)
        self.assertIn("홍길동", board)
        html_path = Path(self.tc("board").stdout.strip())
        self.assertIn("검토 대기", html_path.read_text())
        self.assertEqual(self.tc("watch", check=False).returncode, 0, (self.repo / ".hobin/ALERTS.md").read_text())
        self.tc("accept", t1)
        self.assertEqual(self.state(t1)["status"], "done")
        self.assertFalse((wtroot / t1).exists())
        branches = subprocess.run(["git", "branch", "--list", "hobin/T-001"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "", "병합된 티켓 브랜치는 정리되어야 함")
        # 잘못된 전이는 거부
        self.assertEqual(self.tc("retry", t1, check=False).returncode, 2)


if __name__ == "__main__":
    unittest.main()


class RepoCase(unittest.TestCase):
    """시험용 저장소 하나를 만드는 공통 도우미."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, FAKE_STATE=str(Path(self.tmp.name) / "fake"), FAKE_REPO=str(self.repo), FAKE_MODE="robust",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
        self.git("init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("p\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True, env=self.env).stdout

    def tc(self, *args, check=True, **extra_env):
        p = subprocess.run([sys.executable, str(HOBIN), *args], cwd=self.repo, capture_output=True, text=True,
                           env=dict(self.env, **extra_env), timeout=120)
        if check and p.returncode != 0:
            self.fail(f"hobin {' '.join(args)} 실패\n{p.stdout}\n{p.stderr}")
        return p

    def setup_crew(self, test_cmd=None, **cfg_over):
        self.tc("init", "--no-claude-files", "--skip-cli-check", *(["--test-cmd", test_cmd] if test_cmd else []))
        p = self.repo / ".hobin" / "config.json"
        cfg = json.loads(p.read_text())
        cfg.update(claude_bin=f"{sys.executable} {FAKE}", **cfg_over)
        p.write_text(json.dumps(cfg))
        return cfg

    def state(self, tid):
        return json.loads((self.repo / ".hobin" / "tickets" / tid / "state.json").read_text())

    def ticket(self, paths="r/"):
        tid = self.tc("new", "t", "--paths", paths, "--eval", "ok", "--request", "x").stdout.strip()
        self.tc("ready", tid)
        return tid

    def wait_for(self, tid, statuses, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if self.state(tid)["status"] in statuses:
                return
            time.sleep(0.1)
        self.fail(f"{tid}가 {statuses}에 도달하지 않음: {self.state(tid)['status']}")


class Robustness(RepoCase):
    """리뷰에서 재현된 중단·장애 상황."""

    def test_timeout_without_output(self):
        self.setup_crew(round_timeout_min=0.03, max_rounds=1)  # 약 2초
        tid = self.ticket()
        start = time.time()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_SILENT="30")
        self.assertLess(time.time() - start, 15, "출력이 없어도 시간 제한이 걸려야 함")
        self.assertEqual(self.state(tid)["status"], "failed")
        self.assertIn("시간 제한", (self.repo / ".hobin/runs" / tid / "events.log").read_text())

    def test_killed_worker_is_reaped(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", FAKE_SILENT="2")
        self.wait_for(tid, {"running"})
        time.sleep(0.5)
        claude_pid = self.state(tid)["procs"]["worker"]["pid"]
        os.kill(self.state(tid)["pid"], signal.SIGKILL)  # 작업 프로세스만 강제 종료
        time.sleep(0.3)
        self.tc("status")  # 감시가 잠금이 풀린 것을 보고 실패 처리 + 남은 claude 정리
        st = self.state(tid)
        self.assertEqual(st["status"], "failed")
        self.assertIn("비정상 종료", st["history"][-1]["note"])
        time.sleep(0.3)
        stat = subprocess.run(["ps", "-o", "stat=", "-p", str(claude_pid)], capture_output=True, text=True).stdout.strip()
        self.assertTrue(stat == "" or stat.startswith("Z"), f"고아가 된 claude 프로세스는 종료돼야 함 (상태: {stat})")
        self.tc("retry", tid)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged")

    def test_stop_during_integration_test_leaves_branch_untouched(self):
        cfg = self.setup_crew(test_cmd="sleep 4")
        before = self.git("rev-parse", cfg["integration_branch"]).strip()
        t1 = self.ticket("r/T-001.txt")
        self.tc("run")
        self.wait_for(t1, {"merging"})
        time.sleep(0.5)
        self.tc("stop", t1)
        self.assertEqual(self.state(t1)["status"], "failed")
        self.assertEqual(self.git("rev-parse", cfg["integration_branch"]).strip(), before,
                         "테스트가 끝나기 전에 통합 브랜치가 앞으로 가면 안 됨")
        # 다음 병합이 남은 흔적을 정리하고 정상 진행
        p = self.repo / ".hobin" / "config.json"
        c = json.loads(p.read_text()); c["test_cmd"] = "true"; p.write_text(json.dumps(c))
        t2 = self.ticket("r/T-002.txt")
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(t2)["status"], "merged", self.tc("show", t2).stdout)
        iw = Path(c["worktree_root"]) / "_integration"
        self.assertTrue((iw / "r/T-002.txt").exists())
        self.assertFalse((iw / "r/T-001.txt").exists())

    def test_sync_from_base_branch(self):
        cfg = self.setup_crew()
        (self.repo / "NEW.md").write_text("from main\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "main moved")
        self.tc("sync")
        self.assertTrue((Path(cfg["worktree_root"]) / "_integration" / "NEW.md").exists())


    def test_daemon_started_by_worker_does_not_hold_ticket(self):
        """워커가 띄운 백그라운드 데몬이 티켓 잠금을 물려받아 후속 작업을 막으면 안 된다 (리뷰2 C3)."""
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_DAEMON="1")
        self.assertEqual(self.state(tid)["status"], "merged")
        self.tc("reply", tid, "하나 더 고쳐 주세요")
        start = time.time()
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged", "후속 요청이 데몬 때문에 막혔음")
        self.assertLess(time.time() - start, 15)
        subprocess.run(["pkill", "-f", "sleep 30"], check=False)

    def test_integration_worktree_is_prepared(self):
        """의존성 설치(prepare_cmd)는 통합 작업 공간에서도 돌아야 통합 테스트가 통과한다 (리뷰2 C2)."""
        (self.repo / ".gitignore").write_text(".deps/\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ignore deps")
        self.tc("init", "--no-claude-files", "--skip-cli-check", "--prepare-cmd", "mkdir -p .deps && touch .deps/ok", "--test-cmd", "test -f .deps/ok")
        p = self.repo / ".hobin" / "config.json"
        c = json.loads(p.read_text()); c["claude_bin"] = f"{sys.executable} {FAKE}"; p.write_text(json.dumps(c))
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged", self.tc("show", tid).stdout)
        self.assertEqual(self.state(tid)["rounds"], 1)

    def test_failed_prepare_is_retried(self):
        """준비 명령이 한 번 실패해도 재시도 때 다시 실행된다 (리뷰2 M2)."""
        flag = Path(self.tmp.name) / "allow-prepare"
        self.setup_crew(prepare_cmd=f"test -f {flag}")
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "failed")
        flag.write_text("ok")
        self.tc("retry", tid)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged", self.tc("show", tid).stdout)


class ThirdReview(RepoCase):
    """3차 리뷰에서 재현된 문제들."""

    def count(self, tid):
        f = Path(self.env["FAKE_STATE"]) / f"{tid}.worker.count"
        return int(f.read_text()) if f.exists() else 0

    def test_followup_with_nothing_to_change_stays_merged(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged")
        self.tc("reply", tid, "혹시 더 고칠 게 있나요?")
        self.tc("run", "--wait", "--interval", "0.2", FAKE_DROP_AFTER="1")
        self.assertEqual(self.state(tid)["status"], "merged", self.tc("show", tid).stdout)
        self.tc("accept", tid)

    def test_crash_after_merge_recovers_without_rework(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        st = self.state(tid)
        st["status"] = "failed"  # 병합 커밋 직후 상태 저장 전에 죽은 상황을 흉내
        (self.repo / ".hobin/tickets" / tid / "state.json").write_text(json.dumps(st))
        n = self.count(tid)
        self.tc("retry", tid)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged")
        self.assertEqual(self.count(tid), n, "이미 반영된 작업으로 워커를 다시 돌리면 안 됨")

    def test_session_errors_do_not_spawn_forever(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_ALWAYS_LOST="1")
        self.assertEqual(self.state(tid)["status"], "failed")
        calls = (Path(self.env["FAKE_STATE"]) / "calls.log").read_text().count("x")
        self.assertLessEqual(calls, 6, f"claude를 {calls}번 실행함")

    def test_guard_restores_git_config_and_pauses(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_EVIL="1")
        st = self.state(tid)
        self.assertEqual(st["status"], "failed", self.tc("show", tid).stdout)
        self.assertIn("보안 점검", st["history"][-1]["note"])
        self.assertNotIn("fsmonitor", (self.repo / ".git/config").read_text(), "설정을 원래대로 되돌려야 함")
        self.assertTrue((self.repo / ".hobin/PAUSED").exists())
        self.assertIn("멈춰", self.tc("status").stdout)

    def test_guard_on_integration_test(self):
        cfg = self.setup_crew(test_cmd=f"git config --file {self.repo}/.git/config core.sshCommand evil")
        before = self.git("rev-parse", cfg["integration_branch"]).strip()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "failed", self.tc("show", tid).stdout)
        self.assertNotIn("sshCommand", (self.repo / ".git/config").read_text())
        self.assertEqual(self.git("rev-parse", cfg["integration_branch"]).strip(), before)

    def test_red_integration_is_not_blamed_on_worker(self):
        self.setup_crew(test_cmd="false")
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2")
        st = self.state(tid)
        self.assertEqual(st["status"], "needs_human", self.tc("show", tid).stdout)
        self.assertIn("통합 브랜치 자체", st["question"])
        self.assertEqual(self.count(tid), 1, "통합 브랜치 문제로 워커 회차를 쓰면 안 됨")

    def test_sync_refuses_rewritten_base(self):
        cfg = self.setup_crew()
        (self.repo / "secret.env").write_text("KEY=1\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "oops")
        self.tc("sync")
        self.git("reset", "-q", "--hard", "HEAD~1")  # 비밀 파일 커밋을 지우고 강제 푸시한 상황
        (self.repo / "ok.txt").write_text("ok\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "clean")
        p = self.tc("sync", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("이력이 다시 쓰였습니다", p.stderr)

    def test_input_validation_and_json(self):
        self.setup_crew()
        for bad in ("**/**", "?*/**", ".git/", "../x/", "/etc/"):
            self.assertEqual(self.tc("new", "t", "--paths", bad, "--eval", "e", check=False).returncode, 2, bad)
        pwned = Path(self.tmp.name) / "pwned"
        data = {"title": "제목", "paths": ["r/"], "eval": ["ok"],
                "request": f"$(touch {pwned})\nHOBIN_JSON\nrm -rf /tmp/nothing"}
        p = subprocess.run([sys.executable, str(HOBIN), "new", "--json", "-"], cwd=self.repo, input=json.dumps(data),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        tid = p.stdout.strip()
        body = (self.repo / ".hobin/tickets" / tid / "ticket.md").read_text()
        self.assertIn(f"$(touch {pwned})", body)
        self.assertFalse(pwned.exists())

    def test_submodule_repo_refused(self):
        (self.repo / ".gitmodules").write_text("[submodule \"x\"]\n")
        p = self.tc("init", "--skip-cli-check", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("서브모듈", p.stderr)


class V02(RepoCase):
    """0.2에서 고친 것들: 검증 항목 대조, 테스트 약화 감시, 반려, 감시 오탐, 공유 파일, 비용 상한, 라우터 권한."""

    def events(self, tid):
        return (self.repo / ".hobin/runs" / tid / "events.log").read_text()

    def integ(self, cfg):
        return Path(cfg["worktree_root"]) / "_integration"

    def count(self, tid, role="worker"):
        f = Path(self.env["FAKE_STATE"]) / f"{tid}.{role}.count"
        return int(f.read_text()) if f.exists() else 0

    def test_verifier_must_cover_every_eval_item(self):
        self.setup_crew()
        tid = self.tc("new", "t", "--paths", "r/", "--eval", "첫째 기준", "--eval", "둘째 기준", "--request", "x").stdout.strip()
        self.tc("ready", tid)
        self.tc("run", "--wait", "--interval", "0.2", FAKE_VERIFIER_OMIT_LAST="1")
        st = self.state(tid)
        self.assertEqual(st["status"], "needs_human", self.tc("show", tid).stdout)
        self.assertIn("둘째 기준", st["question"])
        self.assertIn("보고하지 않음", st["question"])
        self.assertEqual(self.count(tid, "verifier"), 2, "빠진 항목이 있으면 한 번 더 검증해야 함")
        # 모두 보고하면 통과
        tid2 = self.tc("new", "t2", "--paths", "r/T-002.txt", "--eval", "첫째", "--eval", "둘째", "--request", "x").stdout.strip()
        self.tc("ready", tid2)
        self.tc("drop", tid)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid2)["status"], "merged", self.tc("show", tid2).stdout)

    def test_test_weakening_goes_to_human(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_x.py").write_text("def test_a():\n    assert 1 + 1 == 2\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "tests")
        cfg = self.setup_crew()
        tid = self.ticket("r/,tests/")
        self.tc("run", "--wait", "--interval", "0.2", FAKE_WEAKEN="1")
        st = self.state(tid)
        self.assertEqual(st["status"], "needs_human", self.tc("show", tid).stdout)
        self.assertIn("건너뛰기", st["question"])
        self.assertIn("단언문 감소", st["question"])
        self.assertFalse((self.integ(cfg) / "r").exists(), "사람 확인 전에는 병합되면 안 됨")
        self.assertIn("test_x.py", self.tc("diff", tid).stdout)
        self.tc("approve", tid)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(tid)["status"], "merged")

    def test_reject_reverts_and_sends_back(self):
        cfg = self.setup_crew()
        t1 = self.ticket("r/T-001.txt")
        self.tc("run", "--wait", "--interval", "0.2")
        iw = self.integ(cfg)
        self.assertEqual((iw / "r/T-001.txt").read_text(), "ok 0\n")
        self.assertIn("r/T-001.txt", self.tc("diff", t1).stdout)
        self.assertEqual(self.tc("reject", t1, check=False).returncode, 2, "사유 없이 반려 불가")
        self.tc("reject", t1, "파일 내용이 요구와 다릅니다")
        self.assertFalse((iw / "r/T-001.txt").exists(), "통합 브랜치에서 되돌려져야 함")
        st = self.state(t1)
        self.assertEqual(st["status"], "ready")
        self.assertIn("반려", st["pending_input"][-1])
        # 워커 작업 공간에는 이전 변경이 다시 살아 있다
        self.assertEqual((Path(cfg["worktree_root"]) / t1 / "r/T-001.txt").read_text(), "ok 0\n")
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(t1)["status"], "merged", self.tc("show", t1).stdout)
        self.assertEqual((iw / "r/T-001.txt").read_text(), "ok 1\n", "고친 결과가 다시 병합돼야 함")
        self.assertEqual(self.count(t1), 2)
        # 취소로 반려
        self.tc("reject", t1, "--drop")
        self.assertEqual(self.state(t1)["status"], "dropped")
        self.assertFalse((iw / "r/T-001.txt").exists())

    def test_reject_refuses_when_others_are_stacked(self):
        self.setup_crew()
        t1 = self.ticket("r/T-001.txt")
        t2 = self.tc("new", "t", "--paths", "r/T-002.txt", "--eval", "ok", "--depends", t1).stdout.strip()
        self.tc("ready", t2)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(t2)["status"], "merged")
        p = self.tc("reject", t1, "이유", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn(t2, p.stderr)

    def test_depends_require_done_waits_for_accept(self):
        self.setup_crew(depends_require="done")
        t1 = self.ticket("r/T-001.txt")
        t2 = self.tc("new", "t", "--paths", "r/T-002.txt", "--eval", "ok", "--depends", t1).stdout.strip()
        self.tc("ready", t2)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(t1)["status"], "merged")
        self.assertEqual(self.state(t2)["status"], "ready", "사람이 확인하기 전 코드 위에 쌓으면 안 됨")
        self.assertIn("accept 필요", self.tc("status").stdout)
        self.tc("accept", t1)
        self.tc("run", "--wait", "--interval", "0.2")
        self.assertEqual(self.state(t2)["status"], "merged")

    def test_guard_ignores_benign_git_config_changes(self):
        """워커가 도는 동안 사람이 한 `git remote add`, `git push -u`를 지우거나 멈추면 안 된다."""
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_BENIGN="1")
        self.assertEqual(self.state(tid)["status"], "merged", self.tc("show", tid).stdout)
        conf = (self.repo / ".git/config").read_text()
        self.assertIn("https://example.com/x.git", conf)
        self.assertIn('[branch "main"]', conf)
        self.assertFalse((self.repo / ".hobin/PAUSED").exists())

    def test_guard_reverts_only_dangerous_keys_and_keeps_backup(self):
        self.setup_crew()
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_BENIGN="1", FAKE_EVIL="1")
        self.assertEqual(self.state(tid)["status"], "failed")
        conf = (self.repo / ".git/config").read_text()
        self.assertNotIn("fsmonitor", conf)
        self.assertIn("https://example.com/x.git", conf, "위험하지 않은 변경은 남겨야 함")
        backups = list((self.repo / ".hobin/guard-backup").glob("*/config"))
        self.assertTrue(backups and "fsmonitor" in backups[0].read_text())

    def test_shared_file_allowed_and_regenerated_on_conflict(self):
        cfg = self.setup_crew(shared_paths=["lock.txt"], regen_on_conflict={"lock.txt": "echo regenerated > lock.txt"})
        t1 = self.ticket("r/T-001.txt")
        t2 = self.ticket("r/T-002.txt")
        self.tc("run", "--wait", "--interval", "0.2", FAKE_SHARED="1")
        for t in (t1, t2):
            self.assertEqual(self.state(t)["status"], "merged", self.tc("show", t).stdout)
        iw = self.integ(cfg)
        self.assertTrue((iw / "lock.txt").exists() and (iw / "r/T-001.txt").exists() and (iw / "r/T-002.txt").exists())
        self.assertIn("다시 만듦", self.events(t1) + self.events(t2))

    def test_ticket_budget_stops_and_resumes(self):
        self.setup_crew(budget_usd_per_ticket=0.015)
        tid = self.ticket()
        self.tc("run", "--wait", "--interval", "0.2", FAKE_VERIFY_FAIL_FIRST="1")
        st = self.state(tid)
        self.assertEqual(st["status"], "needs_human", self.tc("show", tid).stdout)
        self.assertIn("누적 비용", st["question"])
        self.assertEqual(self.count(tid), 1)
        self.tc("reply", tid, "계속")
        self.tc("run", "--wait", "--interval", "0.2", FAKE_VERIFY_FAIL_FIRST="1")
        self.assertEqual(self.state(tid)["status"], "merged", self.tc("show", tid).stdout)

    def test_router_settings_gate_human_approvals(self):
        self.setup_crew()
        self.assertEqual(self.tc("router", "--print", check=False).returncode, 2, "에이전트 파일이 없으면 안내")
        self.tc("install-claude-files")
        out = self.tc("router", "--print").stdout
        self.assertIn("--agent hobin-router", out)
        self.assertIn("router-settings.json", out)
        perms = json.loads((self.repo / ".hobin/router-settings.json").read_text())["permissions"]
        self.assertIn("Bash(hobin *)", perms["allow"])
        for c in ("ready", "approve", "accept", "reject"):
            self.assertIn(f"Bash(hobin {c} *)", perms["ask"])
        self.assertTrue(any(a.startswith("Edit(//") and a.endswith("/.hobin/inbox/**)") for a in perms["allow"]))
        # 파일로 티켓 만들기 (라우터가 쓰는 방식)
        (self.repo / ".hobin/inbox/t.json").write_text(json.dumps({"title": "파일 입력", "paths": ["r/"], "eval": ["ok"], "request": "$(touch x)"}))
        tid = self.tc("new", "--json", ".hobin/inbox/t.json").stdout.strip()
        self.assertEqual(self.state(tid)["status"], "draft")
