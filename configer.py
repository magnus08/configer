#!/usr/bin/env python3
"""Deploy Jinja2-templated dotfiles from this repo into a home directory.

Layout
------
    templates/config/<subdir>/<file>   ->  ~/.config/<subdir>/<file>
    templates/root/<file>              ->  ~/.<file>   (a dot prefix is added
                                                      unless the file already
                                                      starts with one)

Every regular file under templates/, except backup files ending in ~, is
rendered through Jinja2 and then either written to its target (default) or
diffed against it (--diff).
The template context is built from the machine hostname and the repo's
.env file (host, tags and arbitrary variables).

Usage
-----
    uv run python configer.py --diff     # show diffs, write nothing
    uv run python configer.py            # render and copy into $HOME
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATES_DIR = REPO_ROOT / "templates"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

_TRUE_VALUES = {"true", "yes", "on", "1"}
_FALSE_VALUES = {"false", "no", "off", "0"}
_INT_RE = re.compile(r"[+-]?\d+$")
_FLOAT_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")

# Jinja2's default delimiters ({{ }}, {% %}, {# #}) do not collide with any
# of the current template files.  If that ever changes, the delimiters can be
# changed here via Environment(block_start_string=..., ...).
BLOCK_START = "{%"
BLOCK_END = "%}"
VARIABLE_START = "{{"
VARIABLE_END = "}}"
COMMENT_START = "{#"
COMMENT_END = "#}"


def parse_value(raw: str) -> Any:
    """Parse a .env value into bool/int/float/str, stripping surrounding quotes."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    low = raw.lower()
    if low in _TRUE_VALUES:
        return True
    if low in _FALSE_VALUES:
        return False
    if _INT_RE.match(raw):
        return int(raw)
    if _FLOAT_RE.match(raw):
        return float(raw)
    return raw


def load_env_file(path: Path) -> dict[str, Any]:
    """Parse a simple KEY=VALUE env file into a template context.

    Special keys:
        HOST / HOSTNAME   hostname override (template variable ``host``)
        TAGS              comma-separated tags; each tag also becomes a
                          boolean flag (e.g. ``headless`` == True)

    All other keys become template variables, with a lowercase alias added
    for convenience (HEADLESS=true is usable as both ``HEADLESS`` and
    ``headless``).
    """
    env: dict[str, Any] = {}
    tags: set[str] = set()
    host_override: str | None = None

    if path.is_file():
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                print(
                    f"  ! {path}:{lineno}: ignoring line without '=': {line!r}",
                    file=sys.stderr,
                )
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            upper = key.upper()
            if upper in ("HOST", "HOSTNAME"):
                host_override = str(parse_value(value))
            elif upper == "TAGS":
                tags.update(t for t in (part.strip() for part in value.split(",")) if t)
            else:
                env[key] = parse_value(value)

    env["tags"] = sorted(tags)
    for tag in sorted(tags):
        env.setdefault(tag, True)  # every tag doubles as a boolean flag
    if host_override is not None:
        env["host"] = host_override

    for key in list(env):
        lower = key.lower()
        if lower != key and lower not in env:
            env[lower] = env[key]
    return env


def detect_host() -> str:
    """Return the machine hostname without any domain part."""
    return socket.gethostname().split(".", 1)[0]


def map_targets(templates_dir: Path) -> list[tuple[Path, Path]]:
    """Map template files to home-relative destinations, skipping ~ backups."""
    targets: list[tuple[Path, Path]] = []

    config_dir = templates_dir / "config"
    if config_dir.is_dir():
        for src in sorted(config_dir.rglob("*")):
            if src.is_file() and not src.name.endswith("~"):
                targets.append((src, Path(".config") / src.relative_to(config_dir)))

    root_dir = templates_dir / "root"
    if root_dir.is_dir():
        for src in sorted(root_dir.rglob("*")):
            if src.is_file() and not src.name.endswith("~"):
                rel = src.relative_to(root_dir)
                parts = list(rel.parts)
                parts[0] = parts[0] if parts[0].startswith(".") else "." + parts[0]
                targets.append((src, Path(*parts)))

    return targets


def build_environment() -> Environment:
    """A strict Jinja2 environment tuned for line-oriented config files."""
    return Environment(
        undefined=StrictUndefined,  # typos in templates raise instead of silently passing
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,  # block tags don't leave blank lines behind
        lstrip_blocks=True,  # indented block tags keep the surrounding indent tidy
        block_start_string=BLOCK_START,
        block_end_string=BLOCK_END,
        variable_start_string=VARIABLE_START,
        variable_end_string=VARIABLE_END,
        comment_start_string=COMMENT_START,
        comment_end_string=COMMENT_END,
    )


def render_template(env: Environment, src: Path, context: dict[str, Any]) -> str:
    return env.from_string(src.read_text(encoding="utf-8")).render(**context)


def _colorize(line: str) -> str:
    if not sys.stdout.isatty():
        return line
    if line.startswith("@@"):
        return "\x1b[36m" + line + "\x1b[0m"
    if line.startswith("+") and not line.startswith("+++"):
        return "\x1b[32m" + line + "\x1b[0m"
    if line.startswith("-") and not line.startswith("---"):
        return "\x1b[31m" + line + "\x1b[0m"
    return line


def show_diff(generated: str, dest: Path) -> bool:
    """Print a unified diff (generated -> installed); True if they differ."""
    gen = generated.splitlines(keepends=True)
    if dest.exists():
        try:
            tgt = dest.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            tgt = []
    else:
        tgt = []
    lines = list(
        difflib.unified_diff(gen, tgt, fromfile="<generated>", tofile=str(dest))
    )
    if not lines:
        return False
    for line in lines:
        print(_colorize(line), end="")
    return True


def write_if_needed(dest: Path, content: str, mode: int) -> str:
    """Atomically write content to dest unless it already matches.

    Returns one of: "new", "updated", "unchanged".
    """
    if dest.is_symlink():
        dest = dest.resolve()  # write through symlinks instead of replacing them
    dest.parent.mkdir(parents=True, exist_ok=True)
    exists = dest.exists()
    if exists and dest.is_dir():
        raise OSError(f"{dest} is a directory, refusing to overwrite")
    if exists:
        try:
            same = (
                dest.read_text(encoding="utf-8") == content
                and (dest.stat().st_mode & 0o777) == mode
            )
        except OSError:
            same = False
        if same:
            return "unchanged"
    tmp = dest.with_name(f".{dest.name}.tmp{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, dest)
    return "updated" if exists else "new"


def fmt(path: Path, home: Path) -> str:
    """Format a path as ~/... when it lives under the target home."""
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="configer",
        description="Deploy Jinja2-templated dotfiles from templates/ into a home directory.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="show a diff of the generated file vs the target file instead of writing",
    )
    parser.add_argument(
        "--host",
        help="override the hostname used for templating (default: HOST= in .env, "
        "then the machine hostname)",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="add a tag (repeatable); same as putting it in TAGS in .env",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="path to the .env file",
    )
    parser.add_argument(
        "--templates",
        default=str(DEFAULT_TEMPLATES_DIR),
        help="path to the templates directory",
    )
    parser.add_argument(
        "--home",
        default=str(Path.home()),
        help="target home directory (useful for dry-run style testing)",
    )
    args = parser.parse_args(argv)

    templates_dir = Path(args.templates).expanduser()
    env_path = Path(args.env_file).expanduser()
    home = Path(args.home).expanduser()

    env = load_env_file(env_path)
    for tag in args.tag:
        env.setdefault(tag, True)
        if tag not in env["tags"]:
            env["tags"] = sorted([*env["tags"], tag])

    host = args.host or env.get("host") or detect_host()
    # env may carry a "host" key from HOST=; merge it first so the resolved
    # host (--host > .env > detected) always wins.
    context: dict[str, Any] = {**env, "host": host}

    targets = map_targets(templates_dir)
    if not targets:
        print(
            f"error: no files found under {templates_dir}/config or {templates_dir}/root",
            file=sys.stderr,
        )
        return 1

    print(
        f"host: {host}  tags: {', '.join(context['tags']) or '(none)'}  "
        f"env: {env_path if env_path.is_file() else '(missing, defaults only)'}"
    )

    env_obj = build_environment()
    differing = 0
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for src, rel in targets:
        dest = home / rel
        try:
            generated = render_template(env_obj, src, context)
            mode = src.stat().st_mode & 0o777
            if args.diff:
                if show_diff(generated, dest):
                    differing += 1
            else:
                status = write_if_needed(dest, generated, mode)
                stats[status] += 1
                print(f"  [{status:9}] {fmt(dest, home)}")
        except Exception as exc:  # jinja2 errors, unwritable targets, ...
            print(f"error: {src}: {exc}", file=sys.stderr)
            return 1

    if args.diff:
        print(f"{differing} of {len(targets)} file(s) differ (nothing was written)")
    else:
        total = len(targets)
        print(
            f"{stats['new']} new, {stats['updated']} updated, "
            f"{stats['unchanged']} unchanged ({total} total)"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # e.g. `configer.py --diff | head`
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
