'''
import os
from fastapi import FastAPI, Depends  # type: ignore
from fastapi.responses import StreamingResponse  # type: ignore
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials  # type: ignore
from openai import OpenAI  # type: ignore

app = FastAPI()

clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)

@app.get("/api")
def idea(creds: HTTPAuthorizationCredentials = Depends(clerk_guard)):
    user_id = creds.decoded["sub"]  # User ID from JWT - available for future use
    # We now know which user is making the request! 
    # You could use user_id to:
    # - Track usage per user
    # - Store generated ideas in a database
    # - Apply user-specific limits or customization
    
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    prompt = [{"role": "user", "content": "Tell me what are the current exciting trends happened within the payments industry in the last 6 months formatted with headings, sub-headings and bullet points"}]
    stream = client.chat.completions.create(model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", messages=prompt, stream=True)

    def event_stream():
        for chunk in stream:
            text = chunk.choices[0].delta.content
            if text:
                lines = text.split("\n")
                for line in lines:
                    yield f"data: {line}\n"
                yield "\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

'''

import os
from fastapi import FastAPI, Depends  # type: ignore
from fastapi.responses import StreamingResponse  # type: ignore
from pydantic import BaseModel  # type: ignore
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials  # type: ignore
from openai import OpenAI  # type: ignore

app = FastAPI()
clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)


class Visit(BaseModel):
    sales_name: str
    date_of_input: str
    notes: str


system_prompt = """
You are provided with notes written by sales team back from client visit.
Your job is to summarize the visit for the product manager and provide your views and comments if the sale's suggestions are feasible and provide an email.
Reply with exactly three sections with the headings and insert a breakline after each reply:
### Summary of suggestions:

### Next steps for the product manager:

### Draft of email to sales in friendly language:
"""


def user_prompt_for(visit: Visit) -> str:
    return f"""Create the summary, next steps and draft email for:
Sales Rep: {visit.sales_name}
Date of Input: {visit.date_of_input}
Notes:
{visit.notes}"""


@app.post("/api")
def consultation_summary(
    visit: Visit,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    user_id = creds.decoded["sub"]  # Available for tracking/auditing
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )

    user_prompt = user_prompt_for(visit)

    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    stream = client.chat.completions.create(
        model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        messages=prompt,
        stream=True,
    )

    def event_stream():
        for chunk in stream:
            text = chunk.choices[0].delta.content
            if text:
                lines = text.split("\n")
                for line in lines[:-1]:
                    yield f"data: {line}\n\n"
                    yield "data:  \n"
                yield f"data: {lines[-1]}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")