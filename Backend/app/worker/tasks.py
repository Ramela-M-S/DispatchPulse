# 👇 ADD THIS COMPATIBILITY FIX AT THE TOP OF tasks.py:
import redis.connection
from redis.maint_notifications import MaintNotificationsConfig

redis.connection.DEFAULT_RESP_VERSION = 2
redis.connection.MaintNotificationsConfig = lambda **kw: MaintNotificationsConfig(enabled=False)
import kombu.transport.redis as kr
kr.REFRESH_BINDING = """
redis.call('SADD', KEYS[1], ARGV[1])
local now = redis.call('TIME')
local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local new_score = ms + tonumber(ARGV[3])
local old_score = redis.call('ZSCORE', KEYS[2], ARGV[2])
if not old_score or new_score > tonumber(old_score) then
    redis.call('ZADD', KEYS[2], new_score, ARGV[2])
end
"""
import asyncio
from asgiref.sync import async_to_sync
from celery import Celery
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import EmailStr
from twilio.rest import Client

from Backend.app.config import db_settings, notification_settings
from Backend.app.utils import TEMPLATE_DIR

fast_mail = FastMail(
    ConnectionConfig(
        **notification_settings.model_dump(
            exclude=["TWILIO_SID", "TWILIO_AUTH_TOKEN", "TWILIO_NUMBER"]
        ),
        TEMPLATE_FOLDER=TEMPLATE_DIR,
    )
)

twilio_client = Client(
    notification_settings.TWILIO_SID,
    notification_settings.TWILIO_AUTH_TOKEN,
)

send_message = async_to_sync(fast_mail.send_message)


app = Celery(
    "api_tasks",
    broker=db_settings.REDIS_URL(9),
    backend=db_settings.REDIS_URL(9),
    broker_connection_retry_on_startup=True,
)


@app.task
def send_mail(
    recipients: list[str],
    subject: str,
    body: str,
):
    send_message(
        message=MessageSchema(
            recipients=recipients,
            subject=subject,
            body=body,
            subtype=MessageType.plain,
        ),
    )
    return "Message Sent!"


@app.task
def send_email_with_template(
        recipients: list[EmailStr],
        subject: str,
        context: dict,
        template_name: str,
):
    # Create the message
    message = MessageSchema(
        recipients=recipients,
        subject=subject,
        template_body=context,
        subtype=MessageType.html,
    )

    # Run the async send_message directly in the task's own event loop
    asyncio.run(fast_mail.send_message(message, template_name=template_name))

    return "Message Sent!"


@app.task
def send_sms(to: str, body: str):
    twilio_client.messages.create(
        from_=notification_settings.TWILIO_NUMBER,
        to=to,
        body=body,
    )