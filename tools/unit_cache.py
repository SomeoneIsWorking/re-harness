"""Reuse a translation unit's scan result while its command and every file it read are unchanged.

An entry is keyed by the caller's description of the unit (compile command plus
anything else the result depends on) and validated by the content hash of each
file the parse read, as reported by that parse, and by the file listing of each
directory the caller watches for new files (an include directory, where a new
header can shadow a read one or satisfy a `__has_include`). A file or directory
written after the parse started makes the result unsafe to keep, so it is not
stored.
"""

import hashlib
import json
import os
from pathlib import Path


#: Coarse filesystem clocks round mtimes; a file this close to the parse start may be newer.
TIMESTAMP_SLACK_NS = 2_000_000_000


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


class UnitCache:
    """One JSON file per unit under `directory`, each naming its key and dependency hashes."""

    def __init__(self, directory, salt, walk_into):
        self.directory = Path(directory)
        self.salt = salt
        self.walk_into = walk_into
        self.digests = {}
        self.listings = {}

    def key(self, *parts):
        return fingerprint(self.salt, *parts)

    def entry_path(self, unit):
        return self.directory / f"{fingerprint(unit)}.json"

    def digest(self, path):
        """`(mtime_ns, content hash)` of a file, or None when it cannot be read; once per run."""
        if path not in self.digests:
            try:
                stat = os.stat(path)
                content = Path(path).read_bytes()
            except OSError:
                self.digests[path] = None
            else:
                self.digests[path] = (stat.st_mtime_ns, hashlib.blake2b(content, digest_size=20).hexdigest())
        return self.digests[path]

    def listing(self, directory):
        """`(newest directory mtime_ns, hash of every file path)` below `directory`; once per run.

        Only subdirectories `walk_into` accepts are entered. A missing directory has its own listing.
        """
        if directory not in self.listings:
            newest = 0
            names = []
            for base, subdirectories, files in os.walk(directory):
                subdirectories[:] = sorted(name for name in subdirectories if self.walk_into(Path(base) / name))
                newest = max(newest, os.stat(base).st_mtime_ns)
                relative = os.path.relpath(base, directory)
                names.extend(os.path.join(relative, name) for name in sorted(files))
            self.listings[directory] = (newest, fingerprint(names) if newest else None)
        return self.listings[directory]

    def load(self, unit, key):
        """The stored result when the key matches and no dependency changed, else None."""
        try:
            stored = json.loads(self.entry_path(unit).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if stored.get("key") != key:
            return None
        for path, expected in stored["dependencies"].items():
            current = self.digest(path)
            if current is None or current[1] != expected:
                return None
        for path, expected in stored["directories"].items():
            if self.listing(path)[1] != expected:
                return None
        return stored["result"]

    def store(self, unit, key, result, dependencies, directories, started_ns):
        """Keep `result` unless an input is missing or may postdate the parse; True when kept."""
        hashes = {}
        for path in sorted(str(item) for item in dependencies):
            current = self.digest(path)
            if current is None or current[0] >= started_ns - TIMESTAMP_SLACK_NS:
                return False
            hashes[path] = current[1]
        listings = {}
        for path in sorted(str(item) for item in directories):
            newest, names = self.listing(path)
            if newest >= started_ns - TIMESTAMP_SLACK_NS:
                return False
            listings[path] = names
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.entry_path(unit)
        partial = target.with_suffix(f".{os.getpid()}.tmp")
        partial.write_text(json.dumps({"key": key, "dependencies": hashes, "directories": listings, "result": result}), encoding="utf-8")
        os.replace(partial, target)
        return True
