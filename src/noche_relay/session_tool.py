from __future__ import annotations

import os

from telethon import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    try:
        api_id = int(os.environ["API_ID"])
        api_hash = os.environ["API_HASH"].strip()
    except KeyError as exc:
        raise SystemExit(f"Set {exc.args[0]} before running this command") from exc
    except ValueError as exc:
        raise SystemExit("API_ID must be an integer") from exc

    print("Sign in with the Telegram account that joined the source channel.")
    print("The generated session grants account access. Store it only as a secret.")
    with TelegramClient(StringSession(), api_id, api_hash) as client:
        session = client.session.save()

    print("\nTELEGRAM_SESSION (secret):")
    print(session)


if __name__ == "__main__":
    main()

