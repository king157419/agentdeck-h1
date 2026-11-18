"""Extract the installed VIA-C archive into this research directory, read-only."""
import json
from pathlib import Path
import struct


def extract(source, destination):
    source = Path(source)
    destination = Path(destination).resolve()
    with source.open("rb") as archive:
        prefix = archive.read(16)
        size_size, header_size, payload_size, json_size = struct.unpack("<4I", prefix)
        if size_size != 4 or not 0 < json_size <= payload_size <= header_size:
            raise ValueError("Invalid ASAR header")
        header = json.loads(archive.read(json_size).decode("utf-8"))
        data_start = 8 + header_size
        count = 0
        skipped = []

        def visit(entries, parts=()):
            nonlocal count
            for name, entry in entries.items():
                if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
                    raise ValueError("Unsafe archive member: %r" % name)
                path = destination.joinpath(*parts, name)
                if "files" in entry:
                    visit(entry["files"], (*parts, name))
                elif "link" in entry:
                    continue
                else:
                    size = entry["size"]
                    offset = int(entry.get("offset", 0))
                    if type(size) is not int or size < 0 or offset < 0 or (not entry.get("unpacked") and data_start + offset + size > source.stat().st_size):
                        skipped.append(str(path.relative_to(destination)))
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if entry.get("unpacked"):
                        data = Path(str(source) + ".unpacked").joinpath(*parts, name).read_bytes()
                    else:
                        archive.seek(data_start + offset)
                        data = archive.read(size)
                    if len(data) != entry["size"]:
                        raise ValueError("Truncated archive member: %s" % path)
                    path.write_bytes(data)
                    count += 1

        visit(header["files"])
    print("Extracted %d files from %s to %s" % (count, source, destination))
    print("Skipped invalid decoy members: %s" % ", ".join(skipped))


if __name__ == "__main__":
    extract(r"D:\VIA-C\resources\app.asar", Path(__file__).parent / "via-c-src")
