from pathlib import Path
from tempfile import TemporaryDirectory

from diopter.bisector import BisectionCallback, bisect, rev_parse
from diopter.repository import Commit, Repo, Revision
from diopter.utils import run_cmd


class TestBisectionCallback(BisectionCallback):
    def check_impl(self, commit: Commit, repo_dir: Path) -> bool | None:
        filenames = list(f for f in repo_dir.iterdir() if f.name != ".git")
        if len(filenames) == 4:
            # Trigger a bisect skip
            return None
        return len(filenames) > 2


def test_bisection() -> None:
    with TemporaryDirectory() as tmpdir:
        run_cmd(f"git -C {tmpdir} init")
        commits = []
        for f in ("a", "b", "c", "d", "e", "f"):
            fpath = Path(tmpdir) / f
            fpath.touch()
            run_cmd(f"git -C {tmpdir} add {f}")
            run_cmd(f"git -C {tmpdir} commit -m 'Add {f}'")
            commits.append(rev_parse(Path(tmpdir), "HEAD"))

        repo = Repo(Path(tmpdir), Revision("master"))
        bad = commits[-1]
        good = commits[0]
        callback = TestBisectionCallback()
        result = bisect(
            repo,
            good=good,
            bad=bad,
            callback=callback,
            no_checkout=False,
        )
        assert result is not None
        assert result == commits[2]
