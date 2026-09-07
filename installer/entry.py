"""pkexec entry: explicit user consent, local files only, sanitized output."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pwd
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.transaction import Transaction, BASE, checked_directory
from installer.update import install_with_low_space_fallback


def safe_failure(exc):
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return "Not enough free space for the update"
        if exc.errno == errno.EROFS:
            return "The installation filesystem is read-only"
        if exc.errno in (errno.EACCES, errno.EPERM):
            return "The installation filesystem denied access"

        code = errno.errorcode.get(exc.errno)
        return (
            "System file operation failed"
            + (f" ({code})" if code else "")
        )

    if isinstance(exc, ValueError):
        message = str(exc).strip()
        if message and len(message) <= 180:
            return message

    return type(exc).__name__


def emit_progress(percent, message):
    print(
        json.dumps(
            {"progress": percent, "message": message}
        ),
        flush=True,
    )


def make_transaction():
    return Transaction(progress=emit_progress)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("install", "repair", "uninstall"),
    )
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--decky", action="store_true")
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args()

    state = {
        "transaction": None,
        "replace_started": False,
    }

    try:
        if os.geteuid() != 0 or "PKEXEC_UID" not in os.environ:
            raise ValueError("System authorization is required")

        user = pwd.getpwuid(int(os.environ["PKEXEC_UID"]))
        if (
            user.pw_uid < 1000
            or not Path(user.pw_dir).is_absolute()
        ):
            raise ValueError(
                "Run Setup from your normal desktop account"
            )

        account = {
            "uid": user.pw_uid,
            "gid": user.pw_gid,
            "home": user.pw_dir,
            "decky": args.decky,
        }

        checked_directory(BASE)

        fd = os.open(
            BASE / "install.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )

        with os.fdopen(fd, "w") as lock:
            fcntl.flock(
                lock,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )

            installation = BASE / "installation.json"
            had_installation = installation.exists()

            if had_installation:
                previous = json.loads(
                    installation.read_text()
                )
                if previous["uid"] != user.pw_uid:
                    raise ValueError(
                        "DeckPort belongs to another desktop account"
                    )
                account["decky"] = (
                    args.decky
                    or previous.get("decky", False)
                )

            transaction = make_transaction()
            state["transaction"] = transaction

            if args.action == "uninstall":
                result = transaction.uninstall(
                    purge=args.purge
                )
            else:
                if args.payload is None or args.sha256 is None:
                    raise ValueError(
                        "Verified payload is required"
                    )

                if args.action == "install":
                    result = install_with_low_space_fallback(
                        state=state,
                        make_transaction=make_transaction,
                        payload=args.payload,
                        expected=args.sha256,
                        account=account,
                        decky=account["decky"],
                        had_installation=had_installation,
                        emit_progress=emit_progress,
                    )
                else:
                    result = transaction.install(
                        args.payload,
                        args.sha256,
                        account,
                        decky=account["decky"],
                    )

            print(
                json.dumps(
                    {"ok": True, "components": result}
                ),
                flush=True,
            )

    except Exception as exc:
        transaction = state.get("transaction")
        stage = (
            transaction.stage
            if transaction is not None
            else "preflight"
        )

        if state.get("replace_started"):
            error = (
                "Low-space replacement could not finish. "
                "Settings were preserved; run the installer again "
                "after freeing additional space."
            )
        else:
            error = (
                "Installation could not finish. "
                "The previous version was retained."
            )

        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": stage,
                    "reason": safe_failure(exc),
                    "error": error,
                }
            ),
            flush=True,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
