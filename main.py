import os, time, random
import undetected_chromedriver as uc
from datetime import date
from selenium.common import ElementNotInteractableException, WebDriverException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
from webdriver_manager.chrome import ChromeDriverManager
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from models import CarListing, Base
from email_report import summarize_today, send_email_report

SEARCH_TERM = "Maverick"
FUZZ_CUTOFF = 70
HEADLESS = True
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
            
            # Extract year from listing text (look for 4-digit years from 2019-2025)
            import re
            year_match = re.search(r'\b(201[9]|202[0-5])\b', listing)
            year = year_match.group(1) if year_match else "Unknown"
            
            scraped_cars.append({
                "listing": listing, "link": link, "mileage": mileage,
                "price": price, "is_hybrid": is_hybrid, "year": year
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
        # Check if listing already exists
        existing = session.query(CarListing).filter_by(link=car["link"]).first()
        
        if existing:
            # Update existing record, but preserve manual price if no new price found
            existing.listing = car["listing"]
            existing.mileage = car["mileage"]
            existing.is_hybrid = car["is_hybrid"]
            existing.year = car["year"]
            existing.still_available = True  # Mark as active since we found it
            
            # Only update price if we found a new one AND it's not manually set
            if car["price"] and car["price"].strip():
                if not existing.manual_price:  # Only update if not manually set
                    existing.price = car["price"]
                    print(f"🔄 Updated price for existing listing: {car['price']}")
                else:
                    print(f"� Skipped price update (manual entry): {existing.listing[:50]}...")
            else:
                print(f"💰 Preserved price for: {existing.listing[:50]}...")
            
            try:
                session.commit()
                skipped_count += 1  # Count as "skipped" since not new
            except Exception as e:
                session.rollback()
                print(f"❌ Error updating {car['link']}: {e}")
        else:
            # Create new listing
            listing = CarListing(
                listing=car["listing"],
                link=car["link"],
                mileage=car["mileage"],
                price=car["price"],
                is_hybrid=car["is_hybrid"],
                year=car["year"],
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
    print(f"↪️ Updated {skipped_count} existing listings.")
    return saved_count, skipped_count


def check_listing_is_active(db_url, driver):
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)


    inactive_listings_removed = 0

    print("⏰ Checking and removing inactive listings...")

    with Session() as session:
        cars = session.scalars(
            select(CarListing).order_by(CarListing.id)).all()
        for c in cars:
            if not getattr(c, "still_available", False):
                continue
            try:
                driver.get(c.link)
                try:
                    WebDriverWait(driver, 15).until(lambda d: d.execute_script(
                        "return document.readyState") == "complete")
                except TimeoutException:
                    pass

                page_source = driver.page_source
                if "Anuncio no disponible" in page_source:
                    c.still_available = False
                    print(f"Removed {c.id} from the active listings.")
                    inactive_listings_removed += 1
                else:
                    c.still_available = True

            except (TimeoutException, WebDriverException) as e:
                print(f"[{c.id}] WebDriver error {e.__class__.__name__}: {e}")

            time.sleep(0.4)

        session.commit()

    print(f"✅ Removed {inactive_listings_removed} listings.")

    try:
        driver.quit()
    except Exception:
        pass

    return inactive_listings_removed


# ---- Enhanced Selenium setup for headless stealth ----
def create_chrome_options():
    """Create fresh Chrome options for each initialization attempt"""
    chrome_opts = uc.ChromeOptions()
    
    # Basic headless configuration
    if HEADLESS:
        chrome_opts.add_argument("--headless=new")
    
    # Essential anti-detection options
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--disable-blink-features=AutomationControlled")
    chrome_opts.add_argument("--window-size=1920,1080")
    
    # User agent
    chrome_opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    return chrome_opts

# Initialize Chrome driver with automatic version management
driver = None
max_retries = 3

for attempt in range(max_retries):
    try:
        print(f"🔧 Attempt {attempt + 1}: Initializing Chrome driver...")
        
        # Get the latest Chrome driver path
        chrome_driver_path = ChromeDriverManager().install()
        print(f"📍 Using ChromeDriver: {chrome_driver_path}")
        
        # Create fresh options for this attempt
        chrome_opts = create_chrome_options()
        
        # Initialize with webdriver-manager path
        driver = uc.Chrome(options=chrome_opts, driver_executable_path=chrome_driver_path)
        print("✅ Chrome driver initialized successfully with webdriver-manager")
        break
        
    except Exception as e:
        print(f"❌ Attempt {attempt + 1} failed: {e}")
        if attempt < max_retries - 1:
            print("🔄 Retrying with fresh options...")
            time.sleep(2)
        else:
            print("💥 All attempts failed, exiting...")
            exit(1)

# Additional stealth measures after driver creation
try:
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    print("✅ Additional stealth measures applied")
except Exception as e:
    print(f"Warning: Could not set additional stealth measures: {e}")

driver.set_page_load_timeout(45)
wait = WebDriverWait(driver, 20)

try:
    # Add random delay before starting
    time.sleep(random.uniform(2, 5))
    
    print("🌐 Navigating to Clasificados Online...")
    driver.get("https://www.clasificadosonline.com/Transportation.asp")
    
    # Random delay to mimic human behavior
    time.sleep(random.uniform(3, 6))
    
    search_field = wait.until(ec.element_to_be_clickable((By.XPATH, '//*[@id="Key"]')))
    
    # Type slowly like a human
    print(f"🔍 Searching for '{SEARCH_TERM}'...")
    for char in SEARCH_TERM:
        search_field.send_keys(char)
        time.sleep(random.uniform(0.1, 0.3))
    
    time.sleep(random.uniform(1, 2))
    search_button = wait.until(ec.element_to_be_clickable((By.NAME, 'Submit2')))
    search_button.click()
    
    # Wait for results with random delay
    time.sleep(random.uniform(3, 5))
    wait.until(ec.presence_of_element_located((By.CLASS_NAME, "Tahoma15blacknound")))

    car_list = []
    page_count = 1
    print(f"📄 Scraping page {page_count}...")
    get_cars_from_page(driver, car_list)
    
    while ec.presence_of_element_located((By.XPATH, '/html/body/table/tbody/tr/td/table[3]/tbody/tr[1]/td[2]/form[2]/div/table[1]/tbody/tr/td[3]/a')):
        try:
            # Random delay between pages
            time.sleep(random.uniform(2, 4))
            
            next_button = wait.until(ec.element_to_be_clickable((By.XPATH, '/html/body/table/tbody/tr/td/table[3]/tbody/tr[1]/td[2]/form[2]/div/table[1]/tbody/tr/td[3]/a')))
            
            # Scroll to button to mimic human behavior
            driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
            time.sleep(random.uniform(0.5, 1.5))
            
            next_button.click()
            page_count += 1
            print(f"📄 Scraping page {page_count}...")
            
            # Wait for new page to load
            time.sleep(random.uniform(3, 5))
            get_cars_from_page(driver, car_list)
            
        except ElementNotInteractableException:
            print("📄 Reached last page")
            get_cars_from_page(driver, car_list)
            break
        except TimeoutException:
            print("⏰ Timeout waiting for next page button")
            break

    print(f"🎯 Found {len(car_list)} total listings")
    saved, skipped = save_to_db(car_list, DB_URL)

    inactive_listings = check_listing_is_active(DB_URL, driver)
    print(f"Inactive listings type: {type(inactive_listings)}")
    
    # Generate and send report
    html = summarize_today(car_list, inactive_listings, saved, skipped, DB_URL)
    send_email_report(f"Maverick Daily Report – {date.today()}", html)
    print("📧 Email report sent successfully")

except TimeoutException as e:
    print(f"⏰ Page timed out: {e}")
except Exception as e:
    print(f"❌ An error occurred: {e}")
    import traceback
    traceback.print_exc()

finally:
    try:
        if 'driver' in locals():
            driver.quit()
            print("🔚 Browser closed")
    except Exception:
        pass
