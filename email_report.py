import os
import smtplib
import ssl
import re
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from models import CarListing

load_dotenv()

GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
MY_EMAIL = os.environ.get("MY_EMAIL")
DB_URL = os.environ.get("DB_URL", "sqlite:///mavericks.db")
PRICE_CAP_DEFAULT = 30000
AGED_DAYS_DEFAULT = 14

def get_total_in_db(db_url: str = DB_URL) -> int:
    engine = create_engine(db_url)
    with Session(engine) as session:
        return session.execute(
            select(func.count()).select_from(CarListing)
        ).scalar_one()
    

# --- helpers for email sections (put in email_report.py) ---
import re
import pandas as pd
from sqlalchemy import create_engine, text

def _to_int_price(p: str | None):
    if not isinstance(p, str): return pd.NA
    s = p.lower()
    # treat “a negociar / call / preguntar” as NA
    if any(k in s for k in ("negoci", "call", "preguntar", "llamar")):
        return pd.NA
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else pd.NA


def _to_int_miles(m: str | None):
    if not isinstance(m, str): return pd.NA
    digits = re.sub(r"[^\d]", "", m)
    return int(digits) if digits else pd.NA


def _extract_year(text: str | None):
    if not isinstance(text, str): return pd.NA
    m = re.search(r"\b(20[12]\d)\b", text)
    return int(m.group(1)) if m else pd.NA


def _df_to_rows_html(df: pd.DataFrame, cols: list[str], limit: int = 12) -> str:
    rows = []
    for _, r in df[cols].head(limit).iterrows():
        cells = []
        for c in cols:
            val = "" if pd.isna(r[c]) else r[c]
            if c == "link" and val:
                val = f"<a href='{val}'>link</a>"
            cells.append(f"<td>{val}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return "\n".join(rows)


def build_hybrid_tables(db_url: str, price_cap: int = 30000, aged_days: int = 14, limit: int = 12):
    """
    Load full DB, enrich columns, and return:
      - hybrids_rows_html: all hybrids cheapest-first (rows only)
      - aged_rows_html: aged hybrids under cap (rows only)
      - counts: dict with totals for quick summary badges
    """
    engine = create_engine(db_url)
    df = pd.read_sql(text("SELECT * FROM cars"), engine)

    # enrich
    df["date_found"]  = pd.to_datetime(df["date_found"])
    df["price_num"]   = df["price"].map(_to_int_price).astype("Int64")
    df["mileage_num"] = df["mileage"].map(_to_int_miles).astype("Int64")
    df["year"]        = df["listing"].map(_extract_year).astype("Int64")
    df["days_on_market"] = (pd.Timestamp.today().normalize() - df["date_found"]).dt.days
    df["is_hybrid"] = df["is_hybrid"].astype("boolean")

    hybrids = df[df["is_hybrid"] == True].copy()
    hybrids_sorted = hybrids.sort_values(["price_num", "mileage_num"], ascending=[True, True])

    aged_under_cap = hybrids_sorted.query(
        "price_num.notna() and price_num <= @price_cap and days_on_market >= @aged_days"
    )

    cols = ["listing", "year", "price", "mileage_num", "days_on_market", "link"]
    hybrids_rows_html = _df_to_rows_html(hybrids_sorted, cols, limit=limit)
    aged_rows_html    = _df_to_rows_html(aged_under_cap, cols, limit=limit)

    counts = {
        "hybrids_total": int(hybrids.shape[0]),
        "aged_hybrids": int((hybrids_sorted["days_on_market"] >= aged_days).sum()),
        "aged_under_cap": int(aged_under_cap.shape[0]),
    }
    return hybrids_rows_html, aged_rows_html, counts


def summarize_today(
    car_list,
    saved_count: int,
    skipped_count: int,
    db_url: str = DB_URL,
    price_cap: int = PRICE_CAP_DEFAULT,
    aged_days: int = AGED_DAYS_DEFAULT,
    table_limit: int = 12,
) -> str:
    """Compose the daily HTML email with DB-wide hybrid sections and today's highlights."""
    # ---- today's quick stats (from this run only) ----
    def price_to_int(p: str | None):
        return int("".join(ch for ch in p if ch and ch.isdigit())) if p else None

    hybrids_today = [c for c in car_list if c.get("is_hybrid")]
    cheapest_today = min(
        (c for c in hybrids_today if price_to_int(c["price"]) is not None),
        key=lambda c: price_to_int(c["price"]),
        default=None,
    )

    total_db = get_total_in_db(db_url)

    # sample of today's scraped rows
    today_rows = "".join(
        f"<tr><td>{c['listing']}</td><td>{c['price']}</td>"
        f"<td>{c['mileage']}</td><td><a href='{c['link']}'>link</a></td></tr>"
        for c in car_list[:10]
    )

    cheapest_block = (
        f"<p><b>Cheapest Hybrid (today):</b> {cheapest_today['listing']} – "
        f"{cheapest_today['price']} – "
        f"<a href='{cheapest_today['link']}'>link</a></p>"
        if cheapest_today
        else "<p><b>Cheapest Hybrid (today):</b> none</p>"
    )

    # ---- DB-wide hybrid sections (enriched & sorted) ----
    hybrids_rows_html, aged_rows_html, counts = build_hybrid_tables(
        db_url=db_url, price_cap=price_cap, aged_days=aged_days, limit=table_limit
    )

    hybrids_section = f"""
    <h3>All Hybrids – Cheapest First</h3>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>Listing</th><th>Year</th><th>Price</th><th>Mileage</th><th>Days</th><th>Link</th></tr>
      {hybrids_rows_html}
    </table>
    """

    aged_section = f"""
    <h3>⚠️ Aged Hybrids under ${price_cap:,} (≥{aged_days} days)</h3>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>Listing</th><th>Year</th><th>Price</th><th>Mileage</th><th>Days</th><th>Link</th></tr>
      {aged_rows_html}
    </table>
    """

    header_badges = f"""
    <p>🌱 Hybrids total in DB: <b>{counts['hybrids_total']}</b> &nbsp;
       ⏳ Aged hybrids (≥{aged_days}d): <b>{counts['aged_hybrids']}</b> &nbsp;
       💸 Aged hybrids ≤ ${price_cap:,}: <b>{counts['aged_under_cap']}</b></p>
    """

    # ---- final HTML ----
    return f"""
    <h2>Maverick Scraper Daily Report – {date.today().isoformat()}</h2>
    <p>✅ Saved: <b>{saved_count}</b> &nbsp; ↪️ Skipped: <b>{skipped_count}</b> &nbsp; 🚗 Hybrids found today: <b>{len(hybrids_today)}</b></p>
    {cheapest_block}
    <p>Total in database: <b>{total_db}</b></p>

    <h3>Today’s sample (first 10)</h3>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>Listing</th><th>Price</th><th>Mileage</th><th>Link</th></tr>
      {today_rows}
    </table>

    {header_badges}
    {hybrids_section}
    {aged_section}
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
