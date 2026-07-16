import os
import secrets

import chainlit as cl

CHAINLIT_USERNAME = os.getenv("CHAINLIT_USERNAME", "")
CHAINLIT_PASSWORD = os.getenv("CHAINLIT_PASSWORD", "")


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    if not CHAINLIT_USERNAME or not CHAINLIT_PASSWORD:
        return None

    valid_username = secrets.compare_digest(username, CHAINLIT_USERNAME)
    valid_password = secrets.compare_digest(password, CHAINLIT_PASSWORD)

    if valid_username and valid_password:
        return cl.User(identifier=username, metadata={"provider": "credentials"})

    return None
