import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from models import CarListing

load_dotenv()

GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
MY_EMAIL = os.environ.get("MY_EMAIL")
DB_URL = os.environ.get("DB_URL", "sqlite:///mavericks.db")

def get_total_in_db(db_url: str = DB_URL) -> int:
    engine = create_engine(db_url)
    with Session(engine) as session:
        return session.execute(
            select(func.count()).select_from(CarListing)
        ).scalar_one()

def summarize_today(car_list, saved_count: int, skipped_count: int, db_url: str = DB_URL) -> str:
    hybrids = [c for c in car_list if c.get("is_hybrid")]

    def price_to_int(p):
        return int("".join(ch for ch in p if ch and ch.isdigit())) if p else None

    cheapest_hybrid = min(
        (c for c in hybrids if price_to_int(c["price"]) is not None),
        key=lambda c: price_to_int(c["price"]),
        default=None
    )

    total_db = get_total_in_db(db_url)

    rows = "".join(
        f"<tr><td>{c['listing']}</td><td>{c['price']}</td>"
        f"<td>{c['mileage']}</td><td><a href='{c['link']}'>link</a></td></tr>"
        for c in car_list[:10]
    )

    cheap_block = (
        f"<p><b>Cheapest Hybrid:</b> {cheapest_hybrid['listing']} – "
        f"{cheapest_hybrid['price']} – "
        f"<a href='{cheapest_hybrid['link']}'>link</a></p>"
        if cheapest_hybrid else "<p><b>Cheapest Hybrid:</b> none today</p>"
    )

    return f"""
    <h2>Maverick Scraper Daily Report – {date.today().isoformat()}</h2>
    <p>✅ Saved: <b>{saved_count}</b> &nbsp; ↪️ Skipped: <b>{skipped_count}</b> &nbsp; 🚗 Hybrids today: <b>{len(hybrids)}</b></p>
    {cheap_block}
    <p>Total in database: <b>{total_db}</b></p>
    <h3>Today’s sample (first 10)</h3>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>Listing</th><th>Price</th><th>Mileage</th><th>Link</th></tr>
      {rows}
    </table>
    """

def send_email_report(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MY_EMAIL
    msg["To"] = MY_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(MY_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print("📧 Email sent!")
