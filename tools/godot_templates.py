#!/usr/bin/env python3
"""Point a Godot project's export presets at our Godot fork's export templates, for one release build.

Every Android preset gets the fork's Mono APK templates and Gradle source template; every Linux and
macOS preset gets the fork's desktop template. The templates sit beside the fork's editor in its
bin/ (pass --godot, normally $GODOT_BIN) unless --templates names another directory. A preset whose
template file is missing stops the run, so a build never falls back to stock Godot.

The file is edited in place: release scripts restore it from git when they finish.

  godot_templates.py stamp export_presets.cfg --godot "$GODOT_BIN"
  godot_templates.py stamp export_presets.cfg --templates ~/repo/shared/godot/bin

Prints one line per stamped preset; exits 1 if a template is missing or nothing was stamped.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ANDROID = {
    "custom_template/release": "android_monoRelease.apk",
    "custom_template/debug": "android_monoDebug.apk",
    "gradle_build/android_source_template": "android_source.zip",
}
DESKTOP = {
    "Linux": "godot.linuxbsd.template_release.x86_64.llvm.mono",
    "macOS": "macos.zip",
}
PRESET = re.compile(r"^\[preset\.(\d+)\]$")
OPTIONS = re.compile(r"^\[preset\.(\d+)\.options\]$")


def templates_dir(args: argparse.Namespace) -> Path:
    if args.templates:
        return Path(args.templates).expanduser().resolve()
    found = shutil.which(args.godot) if args.godot else None
    if not found:
        sys.exit("godot_templates.py: give --templates, or --godot naming the fork's editor")
    return Path(found).resolve().parent


def wanted(platform: str) -> dict[str, str]:
    """The template keys a preset of this platform takes, each with its file name."""
    if platform == "Android":
        return ANDROID
    if platform in DESKTOP:
        return {"custom_template/debug": DESKTOP[platform], "custom_template/release": DESKTOP[platform]}
    return {}


def stamp(presets: Path, templates: Path) -> list[str]:
    lines = presets.read_text().splitlines()
    platforms: dict[str, str] = {}
    names: dict[str, str] = {}
    current = None
    for line in lines:
        if m := PRESET.match(line):
            current = m.group(1)
        elif current is not None and line.startswith("platform="):
            platforms[current] = line.split("=", 1)[1].strip('"')
        elif current is not None and line.startswith("name="):
            names[current] = line.split("=", 1)[1].strip('"')
    out: list[str] = []
    done: list[str] = []
    keys: dict[str, str] = {}
    for line in lines:
        if m := OPTIONS.match(line):
            keys = dict(wanted(platforms.get(m.group(1), "")))
            out.append(line)
            for key, file in list(keys.items()):
                path = templates / file
                if not path.is_file():
                    sys.exit(f"godot_templates.py: {path} missing; build the fork's templates or pass --templates")
                # Each key is written here, and the preset's own line for it is dropped below.
                out.append(f'{key}="{path}"')
            if keys:
                preset = m.group(1)
                done.append(f"{names.get(preset, preset)} ({platforms[preset]}): {', '.join(sorted(set(keys.values())))}")
            continue
        if PRESET.match(line):
            keys = {}
        if keys and line.split("=", 1)[0] in keys:
            continue
        out.append(line)
    if not done:
        sys.exit(f"godot_templates.py: no Android, Linux or macOS preset in {presets}")
    presets.write_text("\n".join(out) + "\n")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    stamper = commands.add_parser("stamp", help="write the fork's template paths into every export preset")
    stamper.add_argument("presets", type=Path, help="the project's export_presets.cfg, edited in place")
    stamper.add_argument("--godot", help="the fork's editor binary; its directory holds the templates")
    stamper.add_argument("--templates", help="the directory holding the templates, instead of --godot's")
    args = parser.parse_args(argv)
    templates = templates_dir(args)
    for line in stamp(args.presets, templates):
        print(f"godot_templates.py: {line} from {templates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
