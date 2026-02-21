from pathlib import Path
import subprocess
import re


def _run_hwp5txt(path: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["hwp5txt", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def extract_hwp_text(path: Path, *, timeout_s: int = 60) -> str:
    try:
        result = _run_hwp5txt(path, timeout_s)
    except FileNotFoundError as exc:  # pragma: no cover
        reason = "hwp5txt not found on PATH"
        print(f"HWP5TXT FAIL | {path} | {reason}")
        raise ImportError(reason) from exc
    except subprocess.TimeoutExpired as exc:
        reason = f"timeout after {timeout_s}s"
        print(f"HWP5TXT FAIL | {path} | {reason}")
        raise RuntimeError(reason) from exc

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()

    if result.returncode != 0:
        reason = f"nonzero exit (code={result.returncode})"
        if stderr:
            reason = f"{reason} | stderr={stderr[:200]}"
        print(f"HWP5TXT FAIL | {path} | {reason}")
        raise RuntimeError(reason)

    if stderr:
        # stderr는 경고로만 취급하고 진행한다. (정상 종료 + stdout 기준)
        for line in stderr.splitlines():
            if not line.strip():
                continue
            if _is_benign_hwp5txt_warning(line):
                continue
            print(f"HWP5TXT WARN | {path} | stderr={line[:200]}")
        if _is_benign_hwp5txt_warning(stderr):
            print(f"HWP5TXT WARN | {path} | benign stderr suppressed")

    if not stdout:
        reason = "empty stdout"
        print(f"HWP5TXT FAIL | {path} | {reason}")
        raise RuntimeError(reason)

    print(f"HWP5TXT OK | {path} | chars={len(stdout)}")
    return stdout


_BENIGN_HWP5TXT_RE = re.compile(
    r"pkg_resources is deprecated as an API|setuptools\.pypa\.io/en/latest/pkg_resources\.html|importhelper\.py",
    re.IGNORECASE,
)


def _is_benign_hwp5txt_warning(line: str) -> bool:
    return bool(_BENIGN_HWP5TXT_RE.search(line))
