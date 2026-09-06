import os
import json
import sys
import time
from playwright.sync_api import sync_playwright

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "storage.json")
TARGET_URL = "https://tabitoken.com"

# Exit codes for cron / scheduling systems
EXIT_OK = 0           # checked in successfully (or already checked in)
EXIT_ALREADY = 0      # idempotent skip counts as success
EXIT_NO_BUTTON = 2    # button never appeared
EXIT_CLICK_FAILED = 3 # click happened but server didn't confirm
EXIT_AUTH = 4         # storage missing / auth likely expired
EXIT_OTHER = 1        # anything else


def log(message):
    """Unbuffered chronological logging for server consoles."""
    print(message)
    sys.stdout.flush()


def wait_for_turnstile(page, timeout_ms=30_000):
    """
    Block until the Cloudflare Turnstile challenge is solved (or absent).
    Returns True if challenge is solved / not present, False on timeout.
    """
    try:
        page.wait_for_function(
            """() => {
                const iframe = document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"]'
                );
                if (!iframe) return true; // no challenge present
                // If we can read the inner doc, look for the success marker.
                try {
                    const inner = iframe.contentDocument;
                    if (!inner) return false;
                    // Modern Turnstile writes a success response on the
                    // window via postMessage; the visible checkbox is the
                    // most reliable DOM signal.
                    const cb = inner.querySelector('input[type="checkbox"]');
                    if (cb && cb.checked) return true;
                    // Some variants expose a success state via [name="cf-bypass"] etc.
                    return inner.querySelector('[data-state="success"]') !== null;
                } catch (_) {
                    // Cross-origin: cannot read inner doc. Assume still pending.
                    return false;
                }
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception as e:
        log(f"Turnstile wait timed out or failed: {e}")
        return False


def run_checkin():
    log("Starting cloud check-in routine via LocalStorage...")

    if not os.path.exists(STORAGE_FILE):
        log(f"Error: Required snapshot context '{STORAGE_FILE}' was not found.")
        return EXIT_AUTH

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # --- Diagnostic network logging -----------------------------------
        # Comment these out once the flow is stable to reduce log noise.
        page.on(
            "request",
            lambda req: log(f"REQ  {req.method} {req.url}") if "/api/" in req.url else None,
        )
        page.on(
            "response",
            lambda res: log(f"RES  {res.status} {res.url}") if "/api/" in res.url else None,
        )
        # -----------------------------------------------------------------

        try:
            log("Opening target domain root to establish origin...")
            page.goto("https://tabitoken.com", wait_until="domcontentloaded")

            log("Injecting authentication tokens into LocalStorage...")
            with open(STORAGE_FILE, "r") as f:
                storage_data = json.load(f)

            # FIX #1: stringify every value so objects/numbers aren't
            # silently coerced to "[object Object]" by setItem.
            page.evaluate(
                """(data) => {
                    localStorage.clear();
                    for (const [key, value] of Object.entries(data)) {
                        localStorage.setItem(key, String(value));
                    }
                }""",
                storage_data,
            )

            log("Loading user profile layout...")
            page.goto(TARGET_URL, wait_until="networkidle")

            # FIX #2: wait for Turnstile (or its absence) instead of a
            # blind sleep, then wait for the actual button.
            log("Waiting for Cloudflare Turnstile completion (up to 30s)...")
            if not wait_for_turnstile(page, timeout_ms=30_000):
                log("Turnstile did not resolve in time; continuing anyway.")

            log("Waiting for check-in button...")
            try:
                checkin_button = page.locator(
                    'button[data-slot="button"]:has-text("Check")'
                )
                checkin_button.first.wait_for(state="visible", timeout=30_000)
            except Exception:
                # Broader fallback: any button with the data-slot attribute.
                log("Specific check-in button not found; falling back to "
                    "generic button[data-slot] selector.")
                checkin_button = page.locator('button[data-slot="button"]')
                if checkin_button.count() == 0:
                    log("Error: No button[data-slot] elements found in DOM.")
                    return EXIT_NO_BUTTON

            button_element = checkin_button.first
            button_text = button_element.text_content().strip()

            if "Checked in" in button_text:
                log("Status: Checked In")
            else:
                log("Status: Check In")

            is_disabled = (
                button_element.get_attribute("disabled") is not None
                or button_element.get_attribute("data-disabled") is not None
            )

            if "Checked in" in button_text or is_disabled:
                log("Account has already been checked in for today. "
                    "Skipping interaction safely.")
                return EXIT_ALREADY

            log("Clicking \"Check In\"")
            button_element.click()

            # FIX #3: tolerant endpoint matcher + graceful timeout handling.
            try:
                log("Waiting for network API response confirmation "
                    "(up to 20s)...")
                response = page.wait_for_response(
                    # Match any /api/.../checkin* URL — survives renames.
                    lambda r: "/api/" in r.url and "checkin" in r.url,
                    timeout=20_000,
                )
                status = response.status
                log(f"Server response: {status} {response.url}")
                if 200 <= status < 300:
                    log("Server confirmation acknowledged. "
                        "Check-in successful!")
                    return EXIT_OK
                else:
                    log(f"Server returned non-2xx ({status}). "
                        "Check-in likely failed.")
                    # Verify whether the UI actually updated anyway.
                    time.sleep(2)
                    updated = button_element.text_content().strip()
                    if "Checked in" in updated:
                        log("UI confirms 'Checked in' despite non-2xx; "
                            "treating as success.")
                        return EXIT_OK
                    return EXIT_CLICK_FAILED
            except Exception as wait_err:
                log(f"No matching API response within timeout: {wait_err}")
                # Fallback: did the button text change?
                time.sleep(2)
                updated = button_element.text_content().strip()
                if "Checked in" in updated:
                    log("UI confirms 'Checked in' (no network match). "
                        "Check-in completed.")
                    return EXIT_OK
                log("UI did not update and no network match observed. "
                    "Click likely blocked (Turnstile?) or auth expired.")
                return EXIT_CLICK_FAILED

        except Exception as e:
            log(f"Automation execution exception encountered: {e}")
            return EXIT_OTHER
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            log("Job finalized.")


if __name__ == "__main__":
    sys.exit(run_checkin())
