"""Contracts for the staged-secret scanner behind the check-secrets-custom hook."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_staged_secrets import (  # noqa: E402
    added_lines,
    mask,
    scan_diff,
    scan_line,
)


def _diff(path: str, *lines: str) -> str:
    added = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{added}\n"
    )


def test_added_lines_preserves_paths_with_spaces() -> None:
    """The old grep pipeline split these names apart; the parser must not."""
    diff = _diff("app/Artemis Agentic Memory Layer/src/index.ts", "const x = 1;")
    (entry,) = list(added_lines(diff))
    assert entry[0] == "app/Artemis Agentic Memory Layer/src/index.ts"
    assert entry[1] == 1
    assert entry[2] == "const x = 1;"


def test_added_lines_ignores_deletions_and_dev_null() -> None:
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-API_KEY = 'abcdefgh1234'\n"  # pragma: allowlist secret
    )
    assert list(added_lines(diff)) == []


def test_scan_line_flags_a_hardcoded_assignment() -> None:
    # Assembled at runtime so no source line pairs a keyword with a literal
    # value for scanners (this one included) to trip over.
    value = "9f8e7d6c" + "5b4a3210"
    finding = scan_line("src/app.py", 3, f'API_KEY = "{value}"')
    assert finding is not None
    assert finding.key == "API_KEY"
    assert value not in finding.masked_value


def test_scan_line_skips_bare_keyword_mentions() -> None:
    """Documentation naming a variable is not a secret — the old hook's defect."""
    assert scan_line("README.md", 1, "| MCP_API_KEY | required |") is None
    assert scan_line("docs/x.md", 1, "Set FASTAPI_API_KEY before boot.") is None


def test_scan_line_skips_env_indirection_and_templates() -> None:
    cases = [
        'api_key = os.environ["MCP_API_KEY"]',  # pragma: allowlist secret
        "const key = process.env.MCP_API_KEY;",
        "MCP_API_KEY: ${MCP_API_KEY:?must be set}",
        "password: {{ vault_password }}",
    ]
    for text in cases:
        assert scan_line("src/config.py", 1, text) is None, text


def test_scan_line_skips_placeholders_and_pragmas() -> None:
    cases = [
        "MCP_API_KEY=your_secure_api_key_here",
        'PASSWORD = "changeme-later"',  # pragma: allowlist secret
        'TOKEN = "unused-in-tests"  # pragma: allowlist secret',
    ]
    for text in cases:
        assert scan_line("src/config.py", 1, text) is None, text


def test_scan_line_skips_lockfiles_and_env_examples() -> None:
    line = 'API_KEY = "' + "9f8e7d6c" + '5b4a3210"'
    for path in (
        "package-lock.json",
        "uv.lock",
        ".secrets.baseline",
        "app/api/.env.example",
        "node_modules/x/index.js",
    ):
        assert scan_line(path, 1, line) is None, path


def test_scan_diff_reports_masked_values_only() -> None:
    value = "hunter2-" + "production"
    diff = _diff("src/settings.py", f'DB_PASSWORD = "{value}"')
    (finding,) = scan_diff(diff)
    assert finding.path == "src/settings.py"
    assert value not in finding.masked_value
    assert finding.masked_value.startswith("hu")


def test_scan_line_still_catches_unquoted_dotenv_secrets() -> None:
    """The identifier filter must not blind the scanner to real .env values."""
    # Assembled at runtime so no source line carries a keyword=value literal
    # for scanners (including this one) to trip over.
    value = "".join(["a1b2", "c3d4", "e5f6", "a7b8"])
    finding = scan_line("src/.env", 1, f"MCP_API_KEY={value}")
    assert finding is not None
    assert value not in finding.masked_value


def test_scan_line_skips_code_identifier_assignments() -> None:
    """`token = get_token(...)` is an expression, not a credential."""
    cases = [
        "token = _refresh_token",
        "token = get_token(scopes)",
        "password = Prompt.ask(prompt)",
        "apiKey = req.headers",
    ]
    for text in cases:
        assert scan_line("src/x.py", 1, text) is None, text


def test_mask_never_returns_the_input() -> None:
    for value in ("abcdefgh", "sk-live-1234567890"):
        assert mask(value) != value
        assert value not in mask(value)
