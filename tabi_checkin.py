import os
import json
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

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
        context = browser.new_context()
        page = context.new_page()
        stealth_sync(page) 
        
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
            checkin_button = page.locator('button[data-slot="button"]')
            
            if checkin_button.is_visible():
                button_text = checkin_button.text_content().strip()
                print(f"Target button state discovered: '{button_text}'")
                
                is_disabled = checkin_button.get_attribute("disabled") is not None
                
                if "Checked in" in button_text or is_disabled:
                    print("Account has already been checked in for today. Skipping interaction.")
                else:
                    print("Clicking Check-in target element...")
                    checkin_button.click()
                    
                    page.wait_for_response(lambda response: "api/user/checkin" in response.url, timeout=20000)
                    print("Server confirmation acknowledged. Check-in successful!")
            else:
                print("Target action element was not found in the DOM hierarchy.")
        except Exception as e:
            print(f"Automation execution exception encountered: {e}")
        finally:
            context.close()
            browser.close()
            print("Job finalized.")

if __name__ == "__main__":
    run_checkin()
