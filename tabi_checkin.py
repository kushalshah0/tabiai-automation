import os
import json
import time
import sys
from flask import Flask, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "storage.json")
TARGET_URL = "https://tabitoken.com"

# Change this string to a random secret phrase to secure your endpoint!
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
            executable_path="/opt/render/.cache/ms-playwright/chromium-1105/chrome-linux/chrome",
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page.goto("https://tabitoken.com", wait_until="commit")
        with open(STORAGE_FILE, "r") as f:
            storage_data = json.load(f)
            
        page.evaluate(f"""(data) => {{
            localStorage.clear();
            for (const [key, value] of Object.entries(data)) {{
                localStorage.setItem(key, value);
            }}
        }}""", storage_data)
        
        page.goto(TARGET_URL, wait_until="networkidle")
        time.sleep(10) # Turnstile synchronization buffer
        
        try:
            checkin_button = page.locator('button[data-slot="button"]')
            if checkin_button.count() > 0:
                button_element = checkin_button.first
                button_text = button_element.text_content().strip()
                log(f"Status discovered: '{button_text}'")
                
                is_disabled = (
                    button_element.get_attribute("disabled") is not None or 
                    button_element.get_attribute("data-disabled") is not None
                )
                
                if "Checked in" in button_text or is_disabled:
                    return f"Skipped: Already checked in ({button_text})"
                else:
                    log("Clicking \"Check In\"")
                    button_element.click()
                    
                    # Direct check step matching your log layout requirements
                    time.sleep(5)
                    updated_text = button_element.text_content().strip()
                    if "Checked in" in updated_text:
                        return "Server confirmation acknowledged. Check-in successful!"
                    else:
                        page.wait_for_response(lambda response: "api/user/checkin" in response.url, timeout=10000)
                        return "Server confirmation acknowledged. Check-in successful!"
            else:
                return "Error: Button element not found in DOM context."
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
