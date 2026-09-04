import os
import json
import time
from playwright.sync_api import sync_playwright

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "storage.json")
TARGET_URL = "https://tabitoken.com"

def run_checkin():
    print("Starting cloud check-in routine via LocalStorage...")
    
    if not os.path.exists(STORAGE_FILE):
        print(f"Error: Required snapshot context '{STORAGE_FILE}' was not found.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        print("Opening target domain root to establish origin...")
        page.goto("https://tabitoken.com", wait_until="commit")
        
        print("Injecting authentication tokens into LocalStorage...")
        with open(STORAGE_FILE, "r") as f:
            storage_data = json.load(f)
            
        page.evaluate(f"""(data) => {{
            localStorage.clear();
            for (const [key, value] of Object.entries(data)) {{
                localStorage.setItem(key, value);
            }}
        }}""", storage_data)
        
        print("Loading user profile layout...")
        page.goto(TARGET_URL, wait_until="networkidle")
        
        print("Waiting 10 seconds for Cloudflare Turnstile completion...")
        time.sleep(10)
        
        try:
            # Locate the exact check-in button by its data-slot attribute
            checkin_button = page.locator('button[data-slot="button"]')
            
            if checkin_button.count() > 0:
                button_element = checkin_button.first
                button_text = button_element.text_content().strip()
                
                if "Checked in" in button_text:
                    print("Status: Checked In")
                else:
                    print("Status: Check In")
                
                is_disabled = (
                    button_element.get_attribute("disabled") is not None or 
                    button_element.get_attribute("data-disabled") is not None
                )
                
                if "Checked in" in button_text or is_disabled:
                    print("Account has already been checked in for today. Skipping interaction safely.")
                else:
                    print("Clicking \"Check In\"")
                    button_element.click()
                    
                    page.wait_for_response(lambda response: "api/user/checkin" in response.url, timeout=20000)
                    print("Server confirmation acknowledged. Check-in successful!")
            else:
                print("Target action element button tag was not found in the DOM hierarchy.")
                
        except Exception as e:
            print(f"Automation execution exception encountered: {e}")
        finally:
            context.close()
            browser.close()
            print("Job finalized.")

if __name__ == "__main__":
    run_checkin()
