# configer

Templated dotfiles for Linux hosts. The plain config files live in
`templates/` and are deployed to your home directory with host- and
tag-aware [Jinja2](https://jinja2.palletsprojects.com/) templating.

## Layout

| in this repo                | deployed to             |
|-----------------------------|-------------------------|
| `templates/config/foo/bar`  | `~/.config/foo/bar`     |
| `templates/root/tmux.conf`  | `~/.tmux.conf`          |
| `templates/root/.profile`   | `~/.profile`            |
| `templates/root/local/share/applications/*.desktop` | `~/.local/share/applications/*.desktop` |

Files under `templates/root/` get a `.` prefix added unless they already
have one. Emacs backup files with names ending in `~` are ignored when
deploying and showing diffs. Every other regular file under `templates/`
is deployed — if you don't want e.g. `templates/config/sway/config.old`
installed, remove it from the repo. Files that exist in your home but not
in `templates/` are left alone.

## Requirements

- [uv](https://docs.astral.sh/uv/) (handles Python and the one dependency,
  Jinja2; nothing is installed on the host OS)

## Usage

Run from the repo root:

```sh
# Show a diff of generated vs installed files (writes nothing):
uv run python configer.py --diff

# Render and copy into your home directory:
uv run python configer.py
```

First run creates a `.venv` (ignored by git) and a `uv.lock` (commit it).
The `.env` file is ignored by git, so it can differ per machine.

## Hyprland wallpaper

`templates/config/hypr/hyprpaper.conf` uses Hyprpaper's 0.8+ `wallpaper { ... }`
syntax (tested with 0.8.4). The old `preload = ...` and `wallpaper = ...`
syntax is no longer supported. See the
[Hyprpaper configuration reference](https://wiki.hypr.land/Hypr-Ecosystem/hyprpaper/).
An empty `monitor` selects the image for all outputs without a specific wallpaper.

To use a different image on a host, set its path in that host's `.env`:

```sh
WALLPAPER_PATH=/home/magnus/Pictures/wallpaper.jpg
```

The image must already exist on each host; configer deploys the configuration,
not the image. Without an override, the template uses
`/home/magnus/testdata/images/VNLNEWOR003_front-scaled.jpg`.

After deploying with `uv run python configer.py`, log out and back in, or
restart Hyprpaper from a terminal in the running Hyprland session:

```sh
pkill -x hyprpaper
hyprpaper > /tmp/hyprpaper.log 2>&1 &
hyprctl hyprpaper listactive
```

Hyprland starts Hyprpaper on `hyprland.start`; reloading Hyprland does not
rerun that startup hook. Its built-in wallpaper is disabled separately with
`misc.disable_hyprland_logo`.

## .env

`.env` lives in the repo root and controls the template context:

```sh
# Optional hostname override (default: the machine's hostname)
HOST=arch-desktop

# Comma-separated tags; each tag becomes a boolean template flag
TAGS=headless,server

# Any other key is a template variable
MONITOR=DP-1
FONT_SIZE=11
```

Values are parsed as bool (`true/yes/on/1`), int, float, or string; quotes
are stripped. Keys are available as written plus a lowercase alias
(`HEADLESS=true` → both `HEADLESS` and `headless`).

## Templating

Each file is a Jinja2 template. The default delimiters (`{{ }}`, `{% %}`,
`{# #}`) do not collide with the current configs; `[[ ]]` is *not* used
because zshrc already contains it.

Context:

- `host` — hostname (`HOST=` in `.env`, or `--host`, or machine hostname)
- `tags` — list of tags from `TAGS=` (and `--tag`)
- each tag as a boolean flag (e.g. `headless`)
- every other `.env` key

Examples:

```jinja
# Only on the desktop machine
{% if host == 'arch-desktop' %}
exec --no-startup-id picom -b
{% endif %}

# Skip GUI bits on headless hosts
{% if not headless %}
bindsym $mod+Return exec kitty
{% endif %}

# Multiple hosts
{% if host in ['arch-desktop', 'work-laptop'] %}
output DP-1 pos 0 0 res 3840x2160 scale 2
{% endif %}

# Variable substitution
set $font_size {{ font_size }}
```

Notes:

- Block tags are trimmed (no stray blank lines), so line-oriented
  conditionals drop out cleanly.
- Undefined variables raise an error instead of silently rendering empty
  text — good for catching typos.
- For structured files (e.g. the JSONC waybar config), keep each conditional
  block on whole lines so the rendered file stays valid.

## Options

| flag            | meaning                                                     |
|-----------------|-------------------------------------------------------------|
| `--diff`        | show a unified diff of generated vs target, write nothing   |
| `--host NAME`   | override the hostname for templating                        |
| `--tag TAG`     | add a tag (repeatable), e.g. `--tag headless`               |
| `--env-file P`  | path to the .env file (default: `<repo>/.env`)              |
| `--templates P` | path to the templates directory (default: `<repo>/templates`) |
| `--home P`      | target home directory (default: `$HOME`)                    |

## Testing without touching your real home

```sh
uv run python configer.py --diff --home /tmp/fakehome
uv run python configer.py --home /tmp/fakehome
```
