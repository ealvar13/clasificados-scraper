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
from sqlalchemy.orm import Session, sessionmaker
from models import CarListing

load_dotenv()

GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
MY_EMAIL = os.environ.get("MY_EMAIL")
DB_URL = os.environ.get("DB_URL", "sqlite:///mavericks.db")
PRICE_CAP_DEFAULT = 30000
AGED_DAYS_DEFAULT = 14

def get_total_in_db(db_url: str, only_available: bool = False) -> int:
    engine = create_engine(db_url)
    with Session(engine) as session:
        stmt = select(func.count()).select_from(CarListing)
        if only_available:
            stmt = stmt.where(CarListing.still_available.is_(True))
        return session.scalar(stmt) or 0


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


def build_hybrid_tables(db_url, price_cap, aged_days, limit=12, only_available=False):
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        from sqlalchemy import func
        
        base = select(CarListing).where(CarListing.is_hybrid.is_(True))
        if only_available:
            base = base.where(CarListing.still_available.is_(True))

        cheapest = base.order_by(CarListing.price.asc()).limit(limit)
        
        # Calculate days using SQL date functions
        days_sql = func.julianday('now') - func.julianday(CarListing.date_found)
        aged = base.where(
            CarListing.price <= price_cap,
            days_sql >= aged_days
        ).order_by(days_sql.desc()).limit(limit)

        cheapest_rows = session.scalars(cheapest).all()
        aged_rows = session.scalars(aged).all()

        # counts aligned to availability
        counts = {
            "hybrids_total": session.scalar(
                select(func.count()).select_from(CarListing).where(
                    CarListing.is_hybrid.is_(True),
                    *( [CarListing.still_available.is_(True)] if only_available else [] )
                )
            ) or 0,
            "aged_hybrids": session.scalar(
                select(func.count()).select_from(CarListing).where(
                    CarListing.is_hybrid.is_(True),
                    days_sql >= aged_days,
                    *( [CarListing.still_available.is_(True)] if only_available else [] )
                )
            ) or 0,
            "aged_under_cap": session.scalar(
                select(func.count()).select_from(CarListing).where(
                    CarListing.is_hybrid.is_(True),
                    days_sql >= aged_days,
                    CarListing.price <= price_cap,
                    *( [CarListing.still_available.is_(True)] if only_available else [] )
                )
            ) or 0,
        }

        # render your HTML rows (example)
        def row_html(c: CarListing) -> str:
            return (
                f"<tr><td>{c.listing}</td><td>{c.year}</td><td>{c.price}</td>"
                f"<td>{c.mileage}</td><td>{c.days_listed}</td>"
                f"<td><a href='{c.link}'>link</a></td></tr>"
            )

        hybrids_rows_html = "".join(row_html(c) for c in cheapest_rows)
        aged_rows_html = "".join(row_html(c) for c in aged_rows)
        return hybrids_rows_html, aged_rows_html, counts


def summarize_today(
    car_list,
    inactive_listings,
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
       💸 Aged hybrids ≤ ${price_cap:,}: <b>{counts['aged_under_cap']}</b>
        Listings removed today: {inactive_listings}</p>
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
