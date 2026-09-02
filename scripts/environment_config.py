"""Environment policy, provisioning, and live-validation command line."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.environments import (
    VALID_ENVIRONMENTS,
    validate_environment_profile,
)

CONTRACT_PATH = Path("config/environment-contract.yaml")
POLICY_DIR = Path("config/environments")

ENV_ASSIGNMENT = re.compile(
    r"^(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$"
)
CODE_SOURCE_PATTERNS = (
    re.compile(r"\bos\.getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
    re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b"),
    re.compile(r"\bimport\.meta\.env\.([A-Z][A-Z0-9_]*)\b"),
)
COMPOSE_INTERPOLATION = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::[-+?][^}]*)?\}")
SHELL_DEFAULT_INTERPOLATION = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-[^}]*\}")
RUNTIME_TEMPLATE_SKIP_DIRS = {
    ".agents",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".venv",
    "Experiments",
    "archive",
    "build",
    "dist",
    "node_modules",
    "outputs",
}

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "dev": {
        "schema_version": 1,
        "name": "dev",
        "description": "Local and shared developer integration environment.",
        "runtime": {"log_level": "TRACE", "debug": True, "reload": True},
        "governance": {"strict_atp": True, "trust_default_level": 2},
        "deploy": {"branch": "dev", "github_environment": "dev"},
    },
    "staging": {
        "schema_version": 1,
        "name": "staging",
        "description": (
            "Pre-production environment mirroring production policy with "
            "synthetic data."
        ),
        "runtime": {"log_level": "INFO", "debug": False, "reload": False},
        "governance": {"strict_atp": True, "trust_default_level": 1},
        "deploy": {"branch": "staging", "github_environment": "staging"},
    },
    "prod": {
        "schema_version": 1,
        "name": "prod",
        "description": (
            "Production environment reached only through the reviewed "
            "promotion cascade."
        ),
        "runtime": {"log_level": "WARN", "debug": False, "reload": False},
        "governance": {"strict_atp": True, "trust_default_level": 1},
        "deploy": {"branch": "prod", "github_environment": "prod"},
    },
}

AUTHSTRUCTURE_KEYS = (
    "ARTEMIS_AUTHSTRUCTURE_URL",
    "ARTEMIS_AUTHSTRUCTURE_AUDIENCE",
    "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE",
    "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID",
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


@dataclass(frozen=True)
class Target:
    """One generated environment view declared by the contract."""

    name: str
    template: Path
    output: Path


@dataclass(frozen=True)
class EnvDocument:
    """Parsed active declarations from one dotenv document."""

    text: str
    declarations: dict[str, tuple[str, ...]]

    @classmethod
    def from_text(cls, text: str) -> EnvDocument:
        found: dict[str, list[str]] = {}
        for line in text.splitlines():
            match = ENV_ASSIGNMENT.match(line.lstrip())
            if match is None:
                continue
            found.setdefault(match.group("name"), []).append(
                _unquote(match.group("value"))
            )
        return cls(
            text=text,
            declarations={key: tuple(value) for key, value in found.items()},
        )

    @classmethod
    def load(cls, path: Path) -> EnvDocument:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return cls.from_text(text)

    def count(self, key: str) -> int:
        return len(self.declarations.get(key, ()))

    def value(self, key: str) -> str | None:
        values = self.declarations.get(key, ())
        return values[0] if values else None

    def values(self) -> dict[str, str]:
        return {key: values[0] for key, values in self.declarations.items() if values}


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _load_contract(repo_root: Path) -> Mapping[str, Any]:
    path = repo_root / CONTRACT_PATH
    if not path.is_file():
        raise ValueError(f"missing environment contract: {CONTRACT_PATH}")
    data = _load_yaml(path)
    if not isinstance(data, Mapping):
        raise TypeError(f"{CONTRACT_PATH} must contain a mapping")
    if data.get("schema_version") != 1:
        raise ValueError(f"{CONTRACT_PATH} schema_version must be integer 1")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError(f"{CONTRACT_PATH} targets must be a non-empty list")
    return data


def _parse_template(path: Path) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    duplicates: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match is None:
            continue
        name = match.group("name")
        if name in names and name not in duplicates:
            duplicates.append(name)
        names.add(name)
    return names, sorted(duplicates)


def _iter_source_paths(repo_root: Path, contract: Mapping[str, Any]) -> Iterable[Path]:
    excluded = tuple(str(item) for item in contract.get("source_excludes", []))
    found: set[Path] = set()
    for glob in contract.get("source_globs", []):
        if not isinstance(glob, str):
            continue
        for path in repo_root.glob(glob):
            if not path.is_file():
                continue
            relative = path.relative_to(repo_root).as_posix()
            if any(
                relative == item or relative.startswith(f"{item}/") for item in excluded
            ):
                continue
            found.add(path)
    return sorted(found)


def _discover_source_variables(
    repo_root: Path, contract: Mapping[str, Any]
) -> set[str]:
    variables: set[str] = set()
    for path in _iter_source_paths(repo_root, contract):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in CODE_SOURCE_PATTERNS:
            variables.update(pattern.findall(text))
        if path.name.startswith("docker-compose") and path.suffix in {".yaml", ".yml"}:
            variables.update(COMPOSE_INTERPOLATION.findall(text))
        if path.suffix == ".sh":
            variables.update(SHELL_DEFAULT_INTERPOLATION.findall(text))
    return variables


def _discover_runtime_templates(repo_root: Path) -> set[str]:
    templates: set[str] = set()
    for directory, child_dirs, filenames in os.walk(repo_root):
        relative_directory = Path(directory).relative_to(repo_root)
        child_dirs[:] = [
            name
            for name in child_dirs
            if name not in RUNTIME_TEMPLATE_SKIP_DIRS
            and (relative_directory / name).as_posix() != "app/web/api"
        ]
        if ".env.example" in filenames:
            path = Path(directory) / ".env.example"
            templates.add(path.relative_to(repo_root).as_posix())
    return templates


def check_repository(repo_root: Path) -> list[str]:
    """Return deterministic environment contract violations."""
    root = repo_root.resolve()
    errors: list[str] = []
    try:
        contract = _load_contract(root)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]

    for name in VALID_ENVIRONMENTS:
        relative = POLICY_DIR / f"{name}.yaml"
        path = root / relative
        if not path.is_file():
            errors.append(f"missing environment profile {relative}")
            continue
        try:
            validate_environment_profile(_load_yaml(path), name)
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{relative}: {exc}")

    inventories: dict[str, set[str]] = {}
    declared_templates: set[str] = set()
    for target in contract["targets"]:
        if not isinstance(target, Mapping):
            errors.append("environment contract target must be a mapping")
            continue
        name = target.get("name")
        template_value = target.get("template")
        output_value = target.get("output")
        values = (name, template_value, output_value)
        if not all(isinstance(value, str) and value for value in values):
            errors.append(
                "environment contract target requires name, template, and output"
            )
            continue
        template = Path(str(template_value))
        declared_templates.add(template.as_posix())
        path = root / template
        if not path.is_file():
            errors.append(f"missing environment template {template}")
            continue
        variables, duplicates = _parse_template(path)
        inventories[str(name)] = variables
        errors.extend(
            f"{template.as_posix()} declares {variable} more than once"
            for variable in duplicates
        )

    for template in sorted(_discover_runtime_templates(root) - declared_templates):
        errors.append(f"runtime template {template} is not declared in {CONTRACT_PATH}")

    root_variables = inventories.get("root", set())
    for target_name in sorted(inventories):
        if target_name == "root":
            continue
        for variable in sorted(inventories[target_name] - root_variables):
            errors.append(
                f"{target_name} template variable {variable} "
                "is missing from .env.example"
            )

    ignored = {str(item) for item in contract.get("ignored_source_variables", [])}
    discovered = _discover_source_variables(root, contract) - ignored
    for variable in sorted(discovered - root_variables):
        errors.append(
            f"code-discovered variable {variable} is missing from .env.example"
        )
    return sorted(errors)


def fix_profiles(repo_root: Path) -> list[Path]:
    """Repair deterministic environment-profile drift and return changed paths."""
    changed: list[Path] = []
    profile_dir = repo_root.resolve() / POLICY_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)
    for name in VALID_ENVIRONMENTS:
        path = profile_dir / f"{name}.yaml"
        rendered = yaml.safe_dump(
            PROFILE_DEFAULTS[name], sort_keys=False, allow_unicode=True
        )
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != rendered:
            path.write_text(rendered, encoding="utf-8")
            changed.append(path)
    return changed


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _targets(repo_root: Path, contract: Mapping[str, Any]) -> list[Target]:
    targets: list[Target] = []
    for item in contract["targets"]:
        if not isinstance(item, Mapping):
            raise TypeError("environment contract target must be a mapping")
        try:
            name = str(item["name"])
            template = repo_root / str(item["template"])
            output = repo_root / str(item["output"])
        except KeyError as exc:
            raise ValueError(
                "environment contract target requires name, template, and output"
            ) from exc
        targets.append(Target(name=name, template=template, output=output))
    if targets[0].name != "root":
        raise ValueError("the first environment target must be named root")
    return targets


def _template_entries(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match is not None:
            entries.append((match.group("name"), _unquote(match.group("value"))))
    return entries


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip()
    lowered = normalized.lower()
    return (
        not normalized
        or normalized == "__MISSING__"
        or (lowered.startswith("your_") and lowered.endswith("_here"))
        or (normalized.startswith("<") and normalized.endswith(">"))
        or (normalized.startswith("${") and normalized.endswith("}"))
        or lowered in {"change_me", "changeme", "replace_me"}
    )


def _valid_hostname(hostname: str) -> bool:
    if (
        not hostname
        or len(hostname) > 253
        or hostname.startswith(".")
        or hostname.endswith(".")
    ):
        return False
    labels = hostname.split(".")
    if re.fullmatch(r"[0-9.]+", hostname):
        return (
            len(labels) == 4
            and all(labels)
            and all(len(part) == 1 or not part.startswith("0") for part in labels)
            and all(int(part) <= 255 for part in labels)
        )
    return all(
        bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label))
        and len(label) <= 63
        for label in labels
    )


def _valid_authstructure_value(key: str, value: str) -> bool:
    if key != "ARTEMIS_AUTHSTRUCTURE_URL":
        return bool(IDENTIFIER.fullmatch(value))
    if not value or any(character.isspace() for character in value):
        return False
    if value.startswith("https://"):
        expected_scheme = "https"
    elif value.startswith("http://"):
        expected_scheme = "http"
    else:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if (
        parsed.scheme != expected_scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    authority = parsed.netloc
    if (
        not authority
        or "[" in authority
        or "]" in authority
        or authority.count(":") > 1
    ):
        return False
    if ":" in authority:
        hostname, port_text = authority.rsplit(":", 1)
        if re.fullmatch(r"[0-9]{1,5}", port_text) is None:
            return False
        port = int(port_text)
        if not 1 <= port <= 65535:
            return False
    else:
        hostname = authority
    if not _valid_hostname(hostname):
        return False
    return expected_scheme == "https" or hostname in {"localhost", "127.0.0.1"}


def _authstructure_errors(root_document: EnvDocument, root_output: Path) -> list[str]:
    errors: list[str] = []
    relative = root_output.name
    if not root_output.is_file():
        return [f"missing target {relative}; Authstructure operator action required"]
    for key in AUTHSTRUCTURE_KEYS:
        count = root_document.count(key)
        if count == 0:
            errors.append(f"{relative} — missing {key}; operator action required")
        elif count > 1:
            errors.append(f"{relative} — {key} duplicate; operator action required")
        else:
            value = root_document.value(key) or ""
            if not value:
                errors.append(f"{relative} — {key} blank; operator action required")
            elif not _valid_authstructure_value(key, value):
                errors.append(f"{relative} — {key} malformed; operator action required")
    return errors


def _generated_secret(key: str) -> str:
    value = secrets.token_hex(32)
    if key == "ARTEMIS_API_KEY_DEFAULT":
        return f"{value}:admin:read,write,delete,admin"
    return value


def _resolve_root_values(
    template_entries: list[tuple[str, str]],
    root_document: EnvDocument,
    contract: Mapping[str, Any],
    mode: str,
) -> dict[str, str]:
    values = root_document.values()
    generated = {str(item) for item in contract.get("generated_secrets", [])}
    for key, template_value in template_entries:
        current = root_document.value(key)
        if key in generated:
            if mode == "regenerate" or _is_placeholder(current):
                values[key] = (
                    "__MISSING__" if mode == "check" else _generated_secret(key)
                )
            else:
                values[key] = current or ""
        elif current is None:
            values[key] = template_value

    for target, source in contract.get("derived_values", {}).items():
        values[str(target)] = values.get(str(source), "")
    return values


def _render_root(
    current_text: str,
    template_entries: list[tuple[str, str]],
    values: Mapping[str, str],
) -> str:
    managed = {key for key, _value in template_entries}
    seen: set[str] = set()
    rendered: list[str] = []
    for line in current_text.splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match is None or match.group("name") not in managed:
            rendered.append(line)
            continue
        key = match.group("name")
        if key not in seen:
            rendered.append(f"{key}={values[key]}")
            seen.add(key)
    missing = [key for key, _value in template_entries if key not in seen]
    if missing and rendered and rendered[-1]:
        rendered.append("")
    rendered.extend(f"{key}={values[key]}" for key in missing)
    return "\n".join(rendered).rstrip("\n") + "\n"


def _render_service(
    target: Target,
    root_values: Mapping[str, str],
) -> str:
    rendered: list[str] = []
    declared: set[str] = set()
    for line in target.template.read_text(encoding="utf-8").splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match is None:
            rendered.append(line)
            continue
        key = match.group("name")
        declared.add(key)
        default = _unquote(match.group("value"))
        rendered.append(f"{key}={root_values.get(key, default)}")

    if target.name == "express_api":
        additional = sorted(
            key
            for key in root_values
            if key.startswith("ARTEMIS_API_KEY_") and key not in declared
        )
        if additional:
            rendered.extend(["", "# Additional root-managed Express API identities"])
            rendered.extend(f"{key}={root_values[key]}" for key in additional)
    return "\n".join(rendered).rstrip("\n") + "\n"


def _permission_error(path: Path) -> str | None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        return f"{path} permissions are {mode:04o}; expected 0600"
    return None


def _check_values(
    path: Path, expected: Mapping[str, str], keys: Iterable[str]
) -> list[str]:
    document = EnvDocument.load(path)
    errors: list[str] = []
    for key in keys:
        count = document.count(key)
        if count == 0:
            errors.append(f"{path} — missing {key}")
        elif count > 1:
            errors.append(f"{path} — {key} duplicate")
        elif document.value(key) != expected[key]:
            errors.append(f"{path} — {key} out of sync")
    return errors


def provision_environment(repo_root: Path, mode: str = "sync") -> list[str]:
    """Reconcile root-owned values into every declared service view."""
    if mode not in {"sync", "check", "regenerate"}:
        raise ValueError(f"unknown setup mode: {mode}")
    root = repo_root.resolve()
    contract = _load_contract(root)
    targets = _targets(root, contract)
    root_target = targets[0]
    if not root_target.template.is_file():
        return [f"missing environment template {root_target.template}"]

    root_document = EnvDocument.load(root_target.output)
    auth_errors = _authstructure_errors(root_document, root_target.output)
    if auth_errors:
        return auth_errors

    template_entries = _template_entries(root_target.template)
    root_values = _resolve_root_values(template_entries, root_document, contract, mode)
    root_keys = [key for key, _value in template_entries]

    if mode == "check":
        errors = _check_values(root_target.output, root_values, root_keys)
        permission = _permission_error(root_target.output)
        if permission:
            errors.append(permission)
        for target in targets[1:]:
            if not target.output.is_file():
                errors.append(f"{target.output} missing")
                continue
            expected_values = {
                key: root_values[key]
                for key, _value in _template_entries(target.template)
            }
            target_errors = _check_values(
                target.output, expected_values, expected_values.keys()
            )
            expected_text = _render_service(target, root_values)
            if (
                not target_errors
                and target.output.read_text(encoding="utf-8") != expected_text
            ):
                target_errors.append(
                    f"{target.output} — generated view has structural drift"
                )
            errors.extend(target_errors)
            permission = _permission_error(target.output)
            if permission:
                errors.append(permission)
        return errors

    root_text = _render_root(root_document.text, template_entries, root_values)
    if root_text != root_document.text:
        root_target.output.write_text(root_text, encoding="utf-8")
    root_target.output.chmod(0o600)
    final_values = EnvDocument.load(root_target.output).values()

    errors: list[str] = []
    for target in targets[1:]:
        if not target.template.is_file():
            errors.append(f"missing environment template {target.template}")
            continue
        if not target.output.exists():
            try:
                reply = input(f"Create {target.output.relative_to(root)}? (Y/n): ")
            except EOFError:
                reply = ""
            if reply.strip().lower().startswith("n"):
                errors.append(f"{target.output} missing; creation declined")
                continue
        target.output.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render_service(target, final_values)
        current = (
            target.output.read_text(encoding="utf-8")
            if target.output.is_file()
            else None
        )
        if current != rendered:
            target.output.write_text(rendered, encoding="utf-8")
        target.output.chmod(0o600)
    return errors


def _fetch_http_status(url: str, timeout: float) -> int:
    request = Request(url, method="GET")
    with urlopen(request, timeout=timeout) as response:  # nosec B310
        return int(response.status)


def live_check_environment(
    repo_root: Path,
    values: Mapping[str, str],
    *,
    fetch_status: Callable[[str, float], int] = _fetch_http_status,
) -> list[str]:
    """Check manifest-declared live endpoints without printing credentials."""
    contract = _load_contract(repo_root.resolve())
    checks = contract.get("live_checks", [])
    if not isinstance(checks, list):
        return ["environment contract live_checks must be a list"]

    errors: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping):
            errors.append("environment contract live check must be a mapping")
            continue
        name = str(check.get("name", "unnamed"))
        variable = str(check.get("url_variable", ""))
        path = str(check.get("path", "/"))
        required = check.get("required", True) is True
        try:
            timeout = float(check.get("timeout_seconds", 5.0))
        except (TypeError, ValueError):
            errors.append(f"{name} live check has an invalid timeout")
            continue

        base_url = values.get(variable, "").strip()
        if not base_url:
            if required:
                errors.append(f"{name} live check requires {variable}")
            continue
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{name} live check has invalid {variable}")
            continue

        endpoint = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            status = fetch_status(endpoint, timeout)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{name} live check failed ({type(exc).__name__})")
            continue
        if not 200 <= status < 300:
            errors.append(f"{name} live check returned HTTP {status}")
    return errors


def _print_errors(errors: Iterable[str], label: str) -> int:
    items = list(errors)
    for error in items:
        print(f"{label}: {error}")
    return 1 if items else 0


def main(argv: list[str] | None = None) -> int:
    """Run source checks, deterministic fixes, or local env provisioning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "fix", "setup", "live"))
    parser.add_argument("--check", action="store_true", dest="setup_check")
    parser.add_argument("--regenerate", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.command != "setup" and (arguments.setup_check or arguments.regenerate):
        parser.error("--check and --regenerate apply only to setup")
    if arguments.setup_check and arguments.regenerate:
        parser.error("--check and --regenerate are mutually exclusive")

    if arguments.command == "check":
        errors = check_repository(REPO_ROOT)
        if not errors:
            print("environment source contract is valid")
        return _print_errors(errors, "drift")
    if arguments.command == "fix":
        changed = fix_profiles(REPO_ROOT)
        for path in changed:
            print(f"fixed: {path.relative_to(REPO_ROOT)}")
        errors = check_repository(REPO_ROOT)
        return _print_errors(errors, "drift")
    if arguments.command == "live":
        values = EnvDocument.load(REPO_ROOT / ".env").values()
        values.update(os.environ)
        errors = live_check_environment(REPO_ROOT, values)
        if not errors:
            print("declared live environment checks passed")
        return _print_errors(errors, "unavailable")

    mode = (
        "regenerate"
        if arguments.regenerate
        else "check" if arguments.setup_check else "sync"
    )
    print(f"Artemis City — secure environment setup ({mode})")
    errors = provision_environment(REPO_ROOT, mode)
    if errors:
        label = "drift" if mode == "check" else "incomplete"
        return _print_errors(errors, label)
    if mode == "check":
        print("all runtime env files match the root source and service templates")
    else:
        print(
            "setup complete; operator values preserved and generated views synchronized"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
