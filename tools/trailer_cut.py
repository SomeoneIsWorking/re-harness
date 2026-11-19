#!/usr/bin/env python3
"""Cuts a game's store trailer from recorded footage: whole music beats per shot, a landscape and a portrait cut.

Writes <out>/trailer-landscape.mp4, trailer-portrait.mp4 and a contact sheet of each (one frame a shot).

shots.json: {"music": path, "music_from": s, "bpm": n, "music_db": dB, "sfx_db": dB,
             "shots": [{"name", "src": avi, "frame": first movie frame, "beats": n, framing, "sfx_db"?}],
             "card": {"landscape": avi, "portrait": avi, "frame": n, "beats": n}}
A card filmed in one shape only goes into the other cut framed like a shot. "tall_source": true for a portrait game, whose
frames fill the portrait cut and sit in a window ("laspect") over a blurred fill in the landscape cut.
The mix is limited to a true peak under -1 dBFS; music_db and sfx_db set its loudness (about -14 LUFS for stores).
Each shot lasts whole beats of the music, so every cut falls on a beat. A shot is framed by "zoom" and
its centre "cx", "cy" (0 to 1 of the frame); the portrait cut shows a window of it ("paspect", 4:5 by
default, "pzoom", "px", "py", defaulting to the landscape centre) over a blurred fill.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

FPS = 60
WIDE = (1920, 1080)
TALL = (1080, 1920)
PANEL = (1080, 1350)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def boundaries(beats, bpm):
    """Frame where each shot starts and the end, rounded from beat times so cuts never drift."""
    frames, total = [0], 0.0
    for b in beats:
        total += b
        frames.append(round(total * 60.0 / bpm * FPS))
    return frames


def clip(src, first, count, vf, out, sfx_db):
    """count frames of src from movie frame first, filtered by vf, with its sound faded at both ends."""
    frames = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=nb_frames",
                                 "-of", "csv=p=0", str(src)], check=True, capture_output=True, text=True).stdout)
    if first + count > frames:
        sys.exit(f"{src} has {frames} frames; a shot from {first} needs {count}, which would take its cut off the beat")
    seconds = count / FPS
    fade = 0.012
    ffmpeg("-ss", f"{first / FPS:.6f}", "-i", str(src), "-frames:v", str(count), "-t", f"{seconds:.6f}",
           "-vf", f"{vf},fps={FPS},format=yuv420p", "-af",
           f"aresample=48000,apad,atrim=0:{seconds:.6f},volume={sfx_db}dB,afade=t=in:d={fade},afade=t=out:st={seconds - fade:.6f}:d={fade}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "12", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out))


def window(width, height, zoom, cx, cy):
    """crop of width x height (in units of the frame height over zoom) centred at (cx, cy), kept inside the frame."""
    return (f"crop=w=ih/{zoom}*{width / height:.6f}:h=ih/{zoom}:x='clip({cx}*iw-ow/2,0,iw-ow)':y='clip({cy}*ih-oh/2,0,ih-oh)',"
            f"scale={width}:{height}:flags=lanczos")


def landscape(shot, tall_source=False):
    """The frame placed by zoom, cx, cy; a tall game's frame is a window ("laspect", 9:16 by default) over a blurred fill."""
    if not tall_source:
        return window(*WIDE, shot.get("zoom", 1), shot.get("cx", 0.5), shot.get("cy", 0.5))
    width = round(WIDE[1] * shot.get("laspect", 9 / 16) / 2) * 2
    fg = window(width, WIDE[1], shot.get("zoom", 1), shot.get("cx", 0.5), shot.get("cy", 0.5))
    return (f"split[a][b];[a]scale={WIDE[0]}:-2,crop={WIDE[0]}:{WIDE[1]},boxblur=24:2,eq=brightness=-0.18[bg];"
            f"[b]{fg}[fg];[bg][fg]overlay={(WIDE[0] - width) // 2}:0")


def portrait(shot, tall_source=False):
    """A window of the frame ("paspect" wide over high, 4:5 by default; placed by px, py, pzoom) over a blurred fill of the same footage;
    a tall game's frame fills the cut, placed by pzoom, px, py."""
    px, py = shot.get("px", shot.get("cx", 0.5)), shot.get("py", shot.get("cy", 0.5))
    if tall_source:
        return window(*TALL, shot.get("pzoom", 1), px, py)
    height = round(TALL[0] / shot.get("paspect", PANEL[0] / PANEL[1]) / 2) * 2
    fg = window(TALL[0], height, shot.get("pzoom", 1), px, py)
    return (f"split[a][b];[a]scale=-2:{TALL[1]},crop={TALL[0]}:{TALL[1]},boxblur=24:2,eq=brightness=-0.18[bg];"
            f"[b]{fg}[fg];[bg][fg]overlay=0:{(TALL[1] - height) // 2}")


def cut(spec, out, tall):
    bpm = spec["bpm"]
    tall_source = spec.get("tall_source", False)
    shots = spec["shots"]
    card = spec["card"]
    frames = boundaries([s["beats"] for s in shots] + [card["beats"]], bpm)
    work = out / ("tall" if tall else "wide")
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, shot in enumerate(shots):
        count = frames[i + 1] - frames[i]
        vf = portrait(shot, tall_source) if tall else landscape(shot, tall_source)
        part = work / f"{i:02d}-{shot['name']}.mkv"
        clip(shot["src"], shot["frame"], count, vf, part, shot.get("sfx_db", spec["sfx_db"]))
        parts.append(part)
    count = frames[-1] - frames[-2]
    seconds = count / FPS
    part = work / "99-card.mkv"
    size = TALL if tall else WIDE
    fades = f"fade=t=in:d=0.25:color=black,fade=t=out:st={seconds - 0.6:.3f}:d=0.6:color=black"
    own = "portrait" if tall else "landscape"
    if own in card:
        clip(card[own], card["frame"], count, f"scale={size[0]}:{size[1]},{fades}", part, -60)
    else:
        framed = portrait(card, tall_source) if tall else landscape(card, tall_source)
        clip(card["landscape" if tall else "portrait"], card["frame"], count, f"{framed},{fades}", part, -60)
    parts.append(part)
    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    joined = work / "joined.mkv"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined))
    total = frames[-1] / FPS
    name = out / f"trailer-{'portrait' if tall else 'landscape'}.mp4"
    music_db = spec["music_db"]
    ffmpeg("-i", str(joined), "-ss", f"{spec['music_from']:.6f}", "-i", spec["music"],
           "-filter_complex",
           f"[1:a]aresample=48000,atrim=0:{total:.6f},volume={music_db}dB,afade=t=out:st={total - 1.2:.6f}:d=1.2[m];"
           # Limited 4x oversampled, auto level off, so the AAC file's true peak stays under -1 dBFS.
           f"[0:a][m]amix=inputs=2:duration=first:normalize=0,aresample=192000,alimiter=limit=0.87:level=false,aresample=48000[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(name))
    sheet(name, frames, [s["name"] for s in shots] + ["card"], out, tall)
    return name


def sheet(video, frames, names, out, tall):
    """One frame from the middle of each shot, labelled with its time, tiled."""
    stills = []
    for i, label in enumerate(names):
        mid = (frames[i] + frames[i + 1]) // 2
        still = out / ("tall" if tall else "wide") / f"still-{i:02d}.png"
        ffmpeg("-ss", f"{mid / FPS:.6f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:360" if tall else "scale=480:-2", str(still))
        caption = f"{i + 1} {label} {frames[i] / FPS:.2f}-{frames[i + 1] / FPS:.2f}s"
        subprocess.run(["magick", str(still), "-background", "#111", "-fill", "white", "-pointsize", "16",
                        f"label:{caption}", "-gravity", "center", "-append", str(still)], check=True)
        stills.append(str(still))
    columns = 7 if tall else 4
    rows = [stills[i:i + columns] for i in range(0, len(stills), columns)]
    row_files = []
    for r, row in enumerate(rows):
        row_file = out / ("tall" if tall else "wide") / f"row-{r}.png"
        subprocess.run(["magick", *row, "-background", "#111", "-splice", "4x4", "+append", str(row_file)], check=True)
        row_files.append(str(row_file))
    target = out / f"sheet-{'portrait' if tall else 'landscape'}.png"
    subprocess.run(["magick", *row_files, "-background", "#111", "-gravity", "west", "-append", str(target)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shots", type=Path, help="shots.json describing the music, shots and end card")
    parser.add_argument("out", type=Path, help="output folder for the cuts and contact sheets")
    parser.add_argument("only", nargs="?", choices=("landscape", "portrait"), help="make only this cut")
    args = parser.parse_args()
    spec = json.loads(args.shots.read_text())
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    only = args.only
    for tall in (False, True):
        if only in (None, "portrait" if tall else "landscape"):
            print(cut(spec, out, tall))


if __name__ == "__main__":
    main()
