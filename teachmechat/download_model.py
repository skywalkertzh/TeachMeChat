"""Explicit optional model download, never invoked during normal startup."""
import hashlib
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from urllib.request import urlopen

from .runtime import configure_runtime


def main():
    runtime = configure_runtime()
    import whisper
    url = whisper._MODELS["turbo"]
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise RuntimeError("Official model URL must use HTTPS")
    expected = parsed.path.split("/")[-2]
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise RuntimeError("Missing official model checksum")
    directory = runtime / "models"
    directory.mkdir(exist_ok=True)
    target = directory / "large-v3-turbo.pt"
    if target.exists():
        with target.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() == expected:
            print(f"Verified existing turbo: {target}")
            return
        raise RuntimeError("Existing model checksum differs; inspect it before replacing")
    if shutil.disk_usage(runtime).free < 4 * 1024 ** 3:
        raise RuntimeError("At least 4 GiB free in the runtime directory is required before optional model download")
    import tempfile
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".download", delete=False) as temporary:
        partial = Path(temporary.name)
        digest = hashlib.sha256()
        total = 0
        try:
            with urlopen(url, timeout=60) as response:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > 4 * 1024 ** 3:
                        raise RuntimeError("Model download exceeds expected size")
                    temporary.write(block)
                    digest.update(block)
        except BaseException:
            temporary.close()
            partial.unlink(missing_ok=True)
            raise
    try:
        if digest.hexdigest() != expected:
            raise RuntimeError("Model checksum verification failed")
        partial.replace(target)
        print(f"Verified turbo downloaded to: {target}")
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
