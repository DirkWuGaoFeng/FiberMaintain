"""
回归测试门禁 — 检测 prompts/ 或 skills/ 变更时自动运行回归。

用法:
    python scripts/regression_gate.py

退出码:
    0 = 通过（或无相关文件变更）
    1 = 回归测试失败，阻止 commit
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows 控制台/ git 钩子环境默认用 GBK 编码 stdout，本脚本的 emoji 日志
# （🔍/❌/✅/ℹ️）会触发 UnicodeEncodeError 导致门禁误报失败。强制 UTF-8，
# errors="replace" 兜底，保证门禁逻辑本身不受终端编码影响。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

PROJECT_ROOT = Path(__file__).parent.parent

# 触发回归的目录/文件
WATCHED_PREFIXES = ("prompts/", "skills/", "config/thresholds")

# 回归测试命令
REGRESSION_CMD = [
    sys.executable, "-m", "pytest",
    "tests/unit/", "-v", "--tb=short", "-q",
]


def _repo_prefix() -> str:
    """项目目录相对 git 仓库根的前缀（monorepo 兼容）。

    git diff --cached 输出为仓库根相对路径（如
    Agent/LangGraph-agent/prompts/...），需剥离前缀后再匹配。
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    top = result.stdout.strip()
    if not top:
        return ""
    try:
        rel = PROJECT_ROOT.resolve().relative_to(Path(top).resolve())
    except ValueError:
        return ""
    return "" if str(rel) == "." else rel.as_posix() + "/"


def get_changed_files() -> list[str]:
    """获取 git staged 文件列表（归一化为项目相对路径）。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    prefix = _repo_prefix()
    files = []
    for line in result.stdout.splitlines():
        f = line.strip()
        if not f:
            continue
        if prefix and f.startswith(prefix):
            f = f[len(prefix):]
        files.append(f)
    return files


def needs_regression(files: list[str]) -> bool:
    """判断是否需要跑回归。"""
    for f in files:
        for prefix in WATCHED_PREFIXES:
            if f.startswith(prefix):
                return True
    return False


def run_regression() -> int:
    """运行回归测试，返回退出码。"""
    print("🔍 [Regression Gate] prompts/skills/thresholds changed, running regression...")
    result = subprocess.run(REGRESSION_CMD, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("❌ [Regression Gate] FAILED — commit blocked.")
        print("   Fix failing tests or revert prompt/skill changes.")
    else:
        print("✅ [Regression Gate] All regression tests passed.")
    return result.returncode


def main():
    files = get_changed_files()
    if not needs_regression(files):
        print("ℹ️  [Regression Gate] No prompt/skill/threshold changes, skipping.")
        sys.exit(0)
    sys.exit(run_regression())


if __name__ == "__main__":
    main()
