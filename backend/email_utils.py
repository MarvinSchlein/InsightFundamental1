import os
import smtplib
from email.message import EmailMessage

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 465))
EMAIL_ADDRESS = os.getenv("EMAIL_HOST_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

def send_reset_email(to_email, token):
    reset_link = f"https://insightfundamental.streamlit.app?view=reset_password&token={token}"

    msg = EmailMessage()
    msg["Subject"] = "Password Reset – InsightFundamental"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg.set_content(f"""
Hi,

You requested to reset your password.

Click the link below to set a new password:
{reset_link}

If you did not request this, ignore this email.

Best,
InsightFundamental Team
""")
    try:
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
            return True
    except Exception as e:
        print("Error sending email:", e)
        return False
