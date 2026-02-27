#!/usr/bin/env python3

from utils.email_utils import send_email

if __name__=="__main__":
    send_email("pi-logger test email", "this is a test email, sent by pi-logger")
