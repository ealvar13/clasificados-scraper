import os, time
import undetected_chromedriver as uc
from datetime import date
from selenium import webdriver
from selenium.common import ElementNotInteractableException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from models import CarListing, Base
from email_report import summarize_today, send_email_report

SEARCH_TERM = "Maverick"
FUZZ_CUTOFF = 70
HEADLESS = False
DB_URL = os.environ.get("DB_URL", "sqlite:///mavericks.db")

def get_cars_from_page(browser, scraped_cars):
    soup = BeautifulSoup(browser.page_source, "html.parser")
    car_rows = soup.find_all("tr", align="center", valign="middle")
    for row in car_rows:
        try:
            listing_tag = row.select_one("span.Tahoma15blacknound")
            listing = listing_tag.get_text(strip=True).replace("\xa0", " ") if listing_tag else ""
            listing_lower = listing.lower()
            if fuzz.partial_ratio(listing_lower, "maverick") < FUZZ_CUTOFF:
                continue
            is_hybrid = (fuzz.partial_ratio(listing_lower, "hybrid") >= FUZZ_CUTOFF or
                         fuzz.partial_ratio(listing_lower, "híbrido") >= FUZZ_CUTOFF)
            link_tag = row.select_one("a[href^='/UDTransDetail']")
            link = "https://www.clasificadosonline.com" + link_tag["href"] if link_tag else ""
            mileage_tag = row.select_one("span.Tahoma14DbluenoUnd")
            mileage = mileage_tag.get_text(strip=True).replace("Millas", "").strip() if mileage_tag else ""
            price_tag = row.select_one("span.Tahoma14BrownNound")
            price = price_tag.get_text(strip=True) if price_tag else ""
            scraped_cars.append({
                "listing": listing, "link": link, "mileage": mileage,
                "price": price, "is_hybrid": is_hybrid
            })
        except Exception as e:
            print(f"Error parsing row: {e}")
    return scraped_cars


def save_to_db(scraped_cars, db_url=DB_URL):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    saved_count = skipped_count = 0
    for car in scraped_cars:
        listing = CarListing(
            listing=car["listing"],
            link=car["link"],
            mileage=car["mileage"],
            price=car["price"],
            is_hybrid=car["is_hybrid"],
            date_found=date.today()
        )
        try:
            session.add(listing)
            session.commit()
            saved_count += 1
        except IntegrityError:
            session.rollback()
            skipped_count += 1
        except Exception as e:
            session.rollback()
            print(f"❌ Error saving {car['link']}: {e}")
    session.close()
    print(f"✅ Saved {saved_count} new listings.")
    print(f"↪️ Skipped {skipped_count} duplicates.")
    return saved_count, skipped_count


# ---- Selenium setup (same as you had) ----
chrome_options = webdriver.ChromeOptions()
chrome_opts = uc.ChromeOptions()
if HEADLESS:
    chrome_opts.add_argument("--headless=new")

chrome_opts.add_argument("--no-sandbox")
chrome_opts.add_argument("--disable-dev-shm-usage")
chrome_opts.add_argument("--window-size=1920,1080")
chrome_opts.add_argument("--disable-blink-features=AutomationControlled")

driver = uc.Chrome(options=chrome_opts, version_main=138)
driver.set_page_load_timeout(45)
wait = WebDriverWait(driver, 20)

try:
    driver.get("https://www.clasificadosonline.com/Transportation.asp")
    search_field = wait.until(ec.element_to_be_clickable((By.XPATH, '//*[@id="Key"]')))
    search_field.send_keys(SEARCH_TERM)
    time.sleep(1.5)
    search_button = wait.until(ec.element_to_be_clickable((By.NAME, 'Submit2')))
    search_button.click()
    time.sleep(2)
    wait.until(ec.presence_of_element_located((By.CLASS_NAME, "Tahoma15blacknound")))

    car_list = []
    get_cars_from_page(driver, car_list)
    while ec.presence_of_element_located((By.XPATH, '/html/body/table/tbody/tr/td/table[3]/tbody/tr[1]/td[2]/form[2]/div/table[1]/tbody/tr/td[3]/a')):
        get_cars_from_page(driver, car_list)
        try:
            next_button = wait.until(ec.element_to_be_clickable((By.XPATH, '/html/body/table/tbody/tr/td/table[3]/tbody/tr[1]/td[2]/form[2]/div/table[1]/tbody/tr/td[3]/a')))
            next_button.click()
            time.sleep(2)
        except ElementNotInteractableException:
            get_cars_from_page(driver, car_list)
            break

    saved, skipped = save_to_db(car_list, DB_URL)
    html = summarize_today(car_list, saved, skipped, DB_URL)
    send_email_report(f"Maverick Daily Report – {date.today()}", html)

except TimeoutException as e:
    print(f"Page timed out: {e}")

finally:
    try:
        driver.quit()
    except Exception:
        pass
    driver = None