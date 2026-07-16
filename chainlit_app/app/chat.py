import os
import uuid

import chainlit as cl
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:6100")
QUERY_URL = f"{BACKEND_URL}/api/query"
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


@cl.on_chat_start
async def start_chat():
    cl.user_session.set("session_id", str(uuid.uuid4()))
    await cl.Message(content="Hello! I'm your assistant. How can I help you today?").send()


@cl.on_message
async def handle_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")

    async with cl.Step(name="Searching documents", type="retrieval") as step:
        step.input = message.content
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    QUERY_URL,
                    json={"question": message.content, "session_id": session_id},
                )
                response.raise_for_status()
        except httpx.ConnectError:
            step.output = "Backend unreachable"
            await cl.Message(
                content=f"I can't reach the backend at {BACKEND_URL}. Please make sure it's running and try again."
            ).send()
            return
        except httpx.TimeoutException:
            step.output = "Timed out"
            await cl.Message(
                content="The backend took too long to respond. Please try again in a moment."
            ).send()
            return
        except httpx.HTTPStatusError as exc:
            step.output = f"HTTP {exc.response.status_code}"
            detail = exc.response.text[:300]
            await cl.Message(
                content=f"The backend returned an error ({exc.response.status_code}): {detail}"
            ).send()
            return
        except httpx.HTTPError as exc:
            step.output = str(exc)
            await cl.Message(content="Something went wrong talking to the backend. Please try again.").send()
            return

        payload = response.json()
        step.output = "Done"

    answer = payload.get("answer", "")
    sources = payload.get("sources", [])

    elements = [
        cl.Text(
            name=f"{source.get('filename')} — page {source.get('page_number')} (score {source.get('score', 0):.2f})",
            content=source.get("content", ""),
            display="side",
        )
        for source in sources
    ]

    await cl.Message(content=answer, elements=elements).send()
