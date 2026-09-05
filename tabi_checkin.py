import os
import json
import time
import sys
from flask import Flask, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "storage.json")
TARGET_URL = "https://tabitoken.com"

# Your random secret phrase securing the endpoint configuration
SECRET_TOKEN = "nepal_tabi_secure_trigger_9981" 

def log(message):
    """Forces chronological unbuffered log output on server consoles."""
    print(message)
    sys.stdout.flush()

def execute_automation():
    log("Starting cloud check-in routine via LocalStorage API trigger...")
    if not os.path.exists(STORAGE_FILE):
        return "Error: storage.json missing", 500

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
        
        log("Opening target domain root to establish origin...")
        page.goto("https://tabitoken.com", wait_until="commit")
        
        log("Injecting authentication tokens into LocalStorage...")
        with open(STORAGE_FILE, "r") as f:
            storage_data = json.load(f)
            
        page.evaluate(f"""(data) => {{
            localStorage.clear();
            for (const [key, value] of Object.entries(data)) {{
                localStorage.setItem(key, value);
            }}
        }}""", storage_data)
        
        log("Loading user profile layout...")
        page.goto(TARGET_URL, wait_until="networkidle")
        
        log("Waiting 10 seconds for Cloudflare Turnstile completion...")
        time.sleep(10)
        
        try:
            checkin_button = page.locator('button[data-slot="button"]')
            if checkin_button.count() > 0:
                button_element = checkin_button.first
                button_text = button_element.text_content().strip()
                
                if "Checked in" in button_text:
                    log("Status: Checked In")
                else:
                    log("Status: Check In")
                
                is_disabled = (
                    button_element.get_attribute("disabled") is not None or 
                    button_element.get_attribute("data-disabled") is not None
                )
                
                if "Checked in" in button_text or is_disabled:
                    return f"Skipped: Already checked in ({button_text})"
                else:
                    log("Clicking \"Check In\"")
                    button_element.click()
                    
                    # Short buffer pause to let backend API processes run
                    time.sleep(5)
                    
                    try:
                        log("Waiting for network API response confirmation...")
                        page.wait_for_response(lambda response: "api/user/checkin" in response.url, timeout=5000)
                        return "Server confirmation acknowledged. Check-in successful!"
                    except Exception:
                        # Fallback step: read the text on the button to check if the layout text changed to "Checked in"
                        updated_text = button_element.text_content().strip()
                        if "Checked in" in updated_text:
                            return "Success: Check-in completed (Verified via layout text change)!"
                        else:
                            return "Interaction complete: Request fired to site servers."
            else:
                return "Error: Button element not found in DOM hierarchy."
        except Exception as e:
            return f"Failed: {str(e)}"
        finally:
            context.close()
            browser.close()
            log("Automation sequence finalized.")

@app.route(f"/trigger/{SECRET_TOKEN}", methods=["GET", "POST"])
def trigger_endpoint():
    status = execute_automation()
    return jsonify({"status": status, "timestamp": time.time()})

@app.route("/", methods=["GET"])
def health_check():
    return "API Engine Online"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
