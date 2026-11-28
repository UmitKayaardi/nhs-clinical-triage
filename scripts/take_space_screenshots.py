"""
Screenshots of the live Hugging Face Space (deployment evidence): Space page, one demo case result
(Clinician Intake, Demo: High) and the Evaluation tab. One demo triage = one Groq call on the Space.

  python scripts/take_space_screenshots.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report_assets" / "screenshots"
SPACE_PAGE = "https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage"
APP = "https://umitkayaardi-nhs-clinical-triage.hf.space/?__theme=light"


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 900}, device_scale_factor=1.5)

        def shot(name, full=True):
            page.wait_for_timeout(1000)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
            print("saved", name, flush=True)

        # Space page on huggingface.co (URL, owner and running app visible).
        page.goto(SPACE_PAGE, wait_until="domcontentloaded")
        frame = page.frame_locator("iframe").first
        frame.get_by_text("NHS Triage Assistant").first.wait_for(timeout=300000)
        page.wait_for_timeout(4000)
        shot("20_space_home", full=False)

        # Direct app URL: one demo case.
        page.goto(APP)
        page.get_by_text("Please describe your symptoms").wait_for(timeout=300000)
        page.wait_for_timeout(3000)                      # let the Gradio client finish loading
        page.get_by_role("tab", name="Clinician Intake").click()
        page.get_by_text("Typed complaint and vital signs").wait_for(timeout=60000)
        page.locator("button", has_text="Demo: High").first.click()
        page.wait_for_function("() => [...document.querySelectorAll('textarea')]"
                               ".some(t => t.value.includes('Crushing central chest pain'))", timeout=60000)
        page.wait_for_timeout(1500)
        page.locator("button", has_text="Run triage").first.click()
        page.locator(".clinical-card").first.wait_for(timeout=240000)
        page.wait_for_timeout(2000)
        shot("21_space_demo_high_result")

        page.get_by_role("tab", name="Evaluation").click()
        page.get_by_text("Main evaluation").first.wait_for(timeout=60000)
        page.wait_for_timeout(3000)
        shot("22_space_evaluation_tab")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
