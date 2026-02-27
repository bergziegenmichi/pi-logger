import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

import loggers
from config import configuration, credentials


def send_email(subject: str, content: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = configuration.SENDER_EMAIL
    msg["To"] = configuration.RECEIVER_EMAIL
    msg.set_content(content)

    loggers.EMAIL.info(f"Trying to send report email: {subject}")

    try:
        context = ssl.create_default_context()

        with smtplib.SMTP_SSL(configuration.SMTP_SERVER, configuration.SMTP_PORT, context=context, timeout=30) as server:
            loggers.EMAIL.info("Connection established")
            server.login(credentials.EMAIL_USERNAME, credentials.EMAIL_PASSWORD)
            loggers.EMAIL.info("Logged in successfully")
            server.send_message(msg)
            loggers.EMAIL.info("Message sent successfully")
    except Exception as e:
        loggers.EMAIL.error(f"Error: {e}")


def log_critical_with_email(logger: logging.Logger, message: str, alternate_email_message: str = ""):
    logger.critical(message)

    subject = f"CRITICAL ERROR {datetime.now().strftime(configuration.HUMAN_READABLE_DATETIME_FORMAT)}"

    email_message = alternate_email_message if alternate_email_message != "" else message

    send_email(subject, email_message)
