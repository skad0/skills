#!/usr/bin/env python3
"""Validate Agent Skills frontmatter under skills/.

Spec: https://agentskills.io/specification
An empty skills/ directory is success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("pyyaml is required: python3 -m pip install pyyaml\n")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500


def main() -> int:
    if not SKILLS.is_dir():
        print("skills/ directory is missing", file=sys.stderr)
        return 1

    errors = layout_errors()
    skill_files = sorted(path for path in SKILLS.rglob("SKILL.md") if path.is_file())
    for path in skill_files:
        errors.extend(validate_skill(path))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"ok ({len(skill_files)} skills)")
    return 0


def layout_errors() -> list[str]:
    errors: list[str] = []
    for child in sorted(SKILLS.iterdir()):
        if child.name == ".gitkeep":
            continue
        if not child.is_dir():
            errors.append(f"{rel(child)}: move this into skills/<name>/")
            continue
        if not any(child.rglob("SKILL.md")):
            errors.append(f"{rel(child)}: missing SKILL.md")
    return errors


def validate_skill(path: Path) -> list[str]:
    location = rel(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        return [f"{location}: SKILL.md must be UTF-8"]

    try:
        frontmatter = parse_frontmatter(text)
    except ValueError as exc:
        return [f"{location}: {exc}"]

    errors: list[str] = []
    name = frontmatter.get("name")
    if not isinstance(name, str):
        errors.append(f"{location}: name must be a string")
    else:
        if len(name) > MAX_NAME or NAME_RE.fullmatch(name) is None:
            errors.append(
                f"{location}: name must be 1-{MAX_NAME} lowercase letters, digits, "
                "and single hyphens"
            )
        if name != path.parent.name:
            errors.append(
                f"{location}: name {name!r} must match directory {path.parent.name!r}"
            )

    description = frontmatter.get("description")
    if not isinstance(description, str) or description.strip() == "":
        errors.append(f"{location}: description must be a non-empty string")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(
            f"{location}: description is {len(description)} characters "
            f"(maximum {MAX_DESCRIPTION})"
        )

    if "license" in frontmatter:
        license_name = frontmatter["license"]
        if not isinstance(license_name, str) or license_name.strip() == "":
            errors.append(f"{location}: license must be a non-empty string")

    if "compatibility" in frontmatter:
        compatibility = frontmatter["compatibility"]
        if (
            not isinstance(compatibility, str)
            or not 1 <= len(compatibility) <= MAX_COMPATIBILITY
        ):
            errors.append(
                f"{location}: compatibility must be a string of "
                f"1-{MAX_COMPATIBILITY} characters"
            )

    if "metadata" in frontmatter:
        metadata = frontmatter["metadata"]
        if not isinstance(metadata, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in metadata.items()
        ):
            errors.append(f"{location}: metadata must be a map of strings to strings")

    if "allowed-tools" in frontmatter and not isinstance(frontmatter["allowed-tools"], str):
        errors.append(f"{location}: allowed-tools must be a space-separated string")

    # Unknown keys are left alone: the spec lists its fields and does not
    # ban client extensions such as paths or disable-model-invocation.
    return errors


def parse_frontmatter(text: str) -> dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            break
    else:
        raise ValueError("frontmatter is missing a closing ---")

    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid frontmatter YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return loaded


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
