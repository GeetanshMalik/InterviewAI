from pydantic import BaseModel


class BotMessageRequest(BaseModel):
    message: str
    context: dict | None = None
