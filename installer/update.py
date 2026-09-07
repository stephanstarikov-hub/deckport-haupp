"""Update policy helpers kept separate from privileged CLI plumbing."""
import errno


def install_with_low_space_fallback(
    state,
    make_transaction,
    payload,
    expected,
    account,
    decky,
    had_installation,
    emit_progress,
):
    """Install normally, then replace program files on ENOSPC without purging data."""
    transaction = state["transaction"]

    try:
        return transaction.install(
            payload,
            expected,
            account,
            decky=decky,
        )
    except OSError as exc:
        if exc.errno != errno.ENOSPC or not had_installation:
            raise

    state["replace_started"] = True
    transaction.stage = "low-space-replace"
    emit_progress(
        15,
        "Low disk space detected; replacing old program files while preserving settings",
    )

    transaction.uninstall(purge=False)

    emit_progress(
        15,
        "Old program files removed; settings preserved; installing the new version",
    )

    retry = make_transaction()
    state["transaction"] = retry
    result = retry.install(
        payload,
        expected,
        account,
        decky=decky,
    )

    if isinstance(result, dict):
        result["update"] = "low-space-replace"

    return result
