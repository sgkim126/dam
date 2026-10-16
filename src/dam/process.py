"""Execute argument arrays without shell interpolation."""

import subprocess

from .errors import DamError


def run(argv, *, check=True, capture=False, interactive=False, **kwargs):
    if isinstance(argv, (str, bytes)):
        raise TypeError("Commands must be argument sequences")
    try:
        result = subprocess.run(
            [str(arg) for arg in argv],
            text=True,
            capture_output=capture,
            check=False,
            **kwargs,
        )
    except FileNotFoundError as error:
        raise DamError(f"Required executable not found: {argv[0]}", 127) from error
    if check and result.returncode:
        detail = (result.stderr or "").strip() if capture else ""
        code = result.returncode if result.returncode > 0 else 128 - result.returncode
        raise DamError(detail or f"{argv[0]} failed (exit {code})", code)
    return result
