"""Fixed existing pytest acceptance for one isolated Python source repair."""
import hashlib
import re
import subprocess
from pathlib import Path

def validate_contract(c):
    required={"recipe","base","base_sha","target","test","test_sha256","instruction"}
    model=c.get("model","m1") if type(c) is dict else None
    # Historical approved Issue recipes stay M1-pinned. Public Strata use
    # requires a new exact owner-reviewed source/instruction contract.
    if model not in ("m1","auto"):
        raise ValueError("PYTHON_TASK_MODEL_INVALID")
    extra=({"model"} if "model" in c else set())
    if model=="auto":
        extra.update({"source_sha256","public_source_sha256",
                      "public_instruction_sha256"})
    if set(c)!=required | extra:
        raise ValueError("PYTHON_TASK_FIELDS_INVALID")
    if c["recipe"] != "python-fixed-test":
        raise ValueError("PYTHON_TASK_RECIPE_INVALID")
    for key,pattern in [("base_sha",r"[a-f0-9]{40}"),("test_sha256",r"[a-f0-9]{64}"),
                        ("target",r"src/ai_foundation/[A-Za-z0-9_]+\.py"),
                        ("test",r"tests/test_[A-Za-z0-9_]+\.py")]:
        if type(c[key]) is not str or not re.fullmatch(pattern,c[key]):
            raise ValueError("PYTHON_TASK_PIN_INVALID")
    if type(c["instruction"]) is not str or not 1<=len(c["instruction"])<=4000:
        raise ValueError("PYTHON_TASK_INSTRUCTION_INVALID")
    if model=="auto":
        for key in ("source_sha256","public_source_sha256","public_instruction_sha256"):
            if type(c[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}",c[key]):
                raise ValueError("PUBLIC_REVIEW_HASH_INVALID")
        if (c["source_sha256"]!=c["public_source_sha256"]
                or c["public_instruction_sha256"]!=hashlib.sha256(
                    c["instruction"].encode("utf-8")).hexdigest()):
            raise ValueError("PUBLIC_REVIEW_HASH_MISMATCH")

class FixedPytest:
    def _reviewed_regular_file(self, path):
        # Refuse an alias at any path component below the reviewed checkout.
        # A symlinked src/ai_foundation folder can evade path.is_symlink().
        current = self.repo
        for segment in path.relative_to(self.repo).parts:
            current = current / segment
            if current.is_symlink():
                return False
        try:
            return path.is_file() and path.resolve(strict=True).is_relative_to(self.repo)
        except OSError:
            return False

    def __init__(self,task,repo,work):
        validate_contract({k:task[k] for k in
            ("recipe","base","base_sha","target","test","test_sha256","instruction")})
        self.task,self.repo=task,Path(repo).resolve(strict=True)
        head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo,text=True,timeout=10).strip()
        if head!=task["base_sha"]:raise ValueError("TASK_BASE_MOVED")
        self.test=self.repo/task["test"]
        self.source=self.repo/task["target"]
        if not all(self._reviewed_regular_file(item)
                   for item in (self.test, self.source)):
            raise ValueError("FIXED_SOURCE_OR_TEST_MISSING")
        self.policy=Path(work)/"pytest.sb"
        self.tmp=(Path(work)/"tmp").resolve()
        self.tmp.mkdir(parents=True,exist_ok=True)
        # The original blanket home-read denial also covered the test's cwd
        # when an Actions runner checked out source under the owner's home.
        # Reopen only this reviewed checkout's source/tests and fixed pytest
        # config. Metadata access to exact ancestors permits cwd resolution;
        # it does not expose owner files or .git contents.
        owner=Path.home().resolve(strict=True)
        self._sandbox_args=["-D","OWNER_HOME="+str(owner),
                            "-D","REVIEWED_REPO="+str(self.repo),
                            "-D","REVIEWED_SRC="+str(self.repo/"src"),
                            "-D","REVIEWED_TESTS="+str(self.repo/"tests"),
                            "-D","REVIEWED_TMP="+str(self.tmp)]
        for i,name in enumerate(("pyproject.toml","pytest.ini","setup.cfg","tox.ini")):
            self._sandbox_args.extend(["-D",f"REVIEWED_CONFIG_{i}="+str(self.repo/name)])
        profile=["(version 1)","(allow default)",
                 "(deny file-write*)","(deny network-outbound)",
                 '(deny file-read* (subpath (param "OWNER_HOME")))',
                 '(allow file-read-metadata (subpath (param "REVIEWED_REPO")))',
                 # getcwd() needs directory read on the exact cwd inode;
                 # metadata alone does not cover it on owner M1 sandbox.
                 # literal does NOT allow reading arbitrary descendants (.git etc).
                 '(allow file-read* (literal (param "REVIEWED_REPO")))']
        for i,ancestor in enumerate(reversed(self.repo.parents)):
            if ancestor==owner or ancestor.is_relative_to(owner):
                key=f"REVIEWED_ANCESTOR_{i}"
                self._sandbox_args.extend(["-D",key+"="+str(ancestor)])
                profile.append(f'(allow file-read-metadata (literal (param "{key}")))')
        # The scratch tmp lives under the same denied home tree. Its own
        # subpath is writable/readable below, but sqlite's realpath() also
        # stats every intermediate directory; without metadata on the tmp
        # ancestors the sandboxed tests cannot open any database file.
        for i,ancestor in enumerate(reversed(self.tmp.parents)):
            if ancestor==owner or ancestor.is_relative_to(owner):
                key=f"REVIEWED_TMP_ANCESTOR_{i}"
                self._sandbox_args.extend(["-D",key+"="+str(ancestor)])
                profile.append(f'(allow file-read-metadata (literal (param "{key}")))')
        profile.extend([
            '(allow file-read* (subpath (param "REVIEWED_SRC")))',
            '(allow file-read* (subpath (param "REVIEWED_TESTS")))',
            *(f'(allow file-read-data (literal (param "REVIEWED_CONFIG_{i}")))'
              for i in range(4)),
            '(allow file-write* (literal "/dev/null"))',
            '(allow file-write* (subpath (param "REVIEWED_TMP")))',
            '(allow file-read* (subpath (param "REVIEWED_TMP")))',
        ])
        self.policy.write_text("\n".join(profile)+"\n")
        self.verify()
    def verify(self):
        # Recheck both trusted paths before and after the sandbox subprocess.
        # A source symlink could otherwise redirect Guard's reviewed edit into
        # another file while fixed tests still appear to pass.
        if not all(self._reviewed_regular_file(item)
                   for item in (self.test, self.source)):
            raise ValueError("FIXED_SOURCE_OR_TEST_ALIAS_CHANGED")
        if hashlib.sha256(self.test.read_bytes()).hexdigest()!=self.task["test_sha256"]:
            raise ValueError("FIXED_TEST_BYTES_CHANGED")
    def run_tests(self,target):
        self.verify()
        source=self.repo/self.task["target"]
        try:
            compile(source.read_text(),str(source),"exec")
        except SyntaxError as error:
            raise RuntimeError("GENERATED_SOURCE_SYNTAX_ERROR: "+str(error)) from error
        cp=subprocess.run(["/usr/bin/sandbox-exec","-f",str(self.policy),
            *self._sandbox_args,"/opt/homebrew/bin/python3","-B","-m","pytest","-q","-s","-p","no:cacheprovider",
            "--override-ini","addopts=",str(self.test)],cwd=self.repo,
            env={"PATH":"/opt/homebrew/bin:/usr/bin:/bin","HOME":"/nonexistent","TMPDIR":str(self.tmp),
                 "PYTHONDONTWRITEBYTECODE":"1","PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1",
                 "PYTHONPATH":str(self.repo/"src")},
            capture_output=True,text=True,timeout=60)
        self.verify()
        tail=(cp.stdout+"\n"+cp.stderr)[-8000:]
        if cp.returncode==1 and re.search(r"\b[0-9]+ failed\b",tail):raise RuntimeError(tail)
        if cp.returncode!=0:raise ValueError("FIXED_TEST_INFRASTRUCTURE_FAILED:"+tail)
        return tail

    def run_acceptance(self, target):
        """Bridge the existing fixed runner to the host-owned typed receipt.

        run_tests already checks the signed fixed-test bytes and the trusted
        subprocess exit code. Only test failures become repair feedback;
        infrastructure/permission errors still abort the one-shot job.
        """
        from ai_foundation.development_loop import TestAcceptanceReceipt
        try:
            details = self.run_tests(target)
        except RuntimeError as error:
            return TestAcceptanceReceipt(False, str(error)[-8000:] or "FIXED_TEST_FAILURE")
        return TestAcceptanceReceipt(True, details)
