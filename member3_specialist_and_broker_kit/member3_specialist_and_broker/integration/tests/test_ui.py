"""Browser tests: the portal as a person uses it. Skipped unless Playwright and its Chromium are installed."""
import pytest

pw = pytest.importorskip("playwright.sync_api")
from conftest import ADMIN_PASSWORD, G, MONDAY, PASSWORD


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser not downloaded
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


def sign_in(browser, user, password=PASSWORD, **ctx):
    page = browser.new_context(**ctx).new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(G + "/ui/"); page.fill("#u", user); page.fill("#p", password)
    page.click("#login-form button.primary"); page.wait_for_selector("#stats .stat")
    return page


def dismiss_password_prompt(page):  # a password someone else chose opens the change-password dialog; Escape closes it
    page.wait_for_selector("dialog[open] #f")
    page.keyboard.press("Escape")


def test_the_login_page_tells_a_first_time_visitor_what_to_do(browser):
    page = browser.new_page(); page.goto(G + "/ui/")
    text = page.inner_text("#login-form")
    assert "admin" in text and "README" in text and page.locator(".role").count() == 0  # no demo role buttons


def test_the_starting_administrator_is_asked_for_a_new_password(browser):
    page = sign_in(browser, "admin", ADMIN_PASSWORD)
    page.wait_for_selector("dialog[open] #f")
    assert "Change my password" in page.inner_text("dialog") and page.errors == []


def test_the_administrator_adds_a_doctor_who_can_then_sign_in(browser):
    admin = sign_in(browser, "admin", ADMIN_PASSWORD); dismiss_password_prompt(admin)
    admin.click("#hero-actions button:has-text('Add staff member')"); admin.wait_for_selector("#f")
    admin.select_option("#f [name=role]", "doctor")
    admin.fill("#f [name=username]", "dr_ui"); admin.fill("#f [name=full_name]", "Dr. Ulwazi Interface")
    admin.fill("#f [name=password]", "ui-password-1"); admin.fill("#f [name=specialty]", "General Practice")
    for day in ("Mon", "Tue", "Wed"):
        admin.check(f"#f [name=working_days][value={day}]")
    admin.fill("#f [name=start]", "08:00"); admin.fill("#f [name=end]", "12:00"); admin.fill("#f [name=slot_minutes]", "30")
    admin.locator("#f button.primary").click(); admin.wait_for_selector(".toast:has-text('can now sign in as dr_ui')")
    admin.wait_for_timeout(600)
    assert "Dr. Ulwazi Interface" in admin.inner_text("#table") and "Mon,Tue,Wed 08:00-12:00" in admin.inner_text("#table")
    doctor = sign_in(browser, "dr_ui", "ui-password-1")  # their own account, straight away
    assert doctor.inner_text("#hero-title") == "Doctor dashboard" and "Dr. Ulwazi Interface" in doctor.inner_text("#who-name")
    doctor.wait_for_selector("dialog[open] #f")  # the password the administrator chose must be replaced
    assert admin.errors == [] and doctor.errors == []


def test_a_receptionist_books_with_any_available_doctor(browser, patient):
    page = sign_in(browser, "reception1"); dismiss_password_prompt(page)
    page.click("#hero-actions button:has-text('Book appointment')"); page.wait_for_selector("#f")
    assert page.locator("#f [name=doctor] option").count() >= 4  # "Any available doctor" and the doctors on the staff list
    page.select_option("#f [name=patient_id]", value=str(patient["id"]))
    page.fill("#f [name=date]", MONDAY.isoformat()); page.fill("#f [name=time]", "09:30")
    page.locator("#f button.primary").click(); page.wait_for_selector(".toast:has-text('Booked with Dr.')")
    page.click('[data-tab="1"]'); page.wait_for_timeout(400)
    assert MONDAY.isoformat() in page.inner_text("#table") and page.errors == []


def test_a_doctor_sees_their_own_work_and_can_widen_the_view(browser, api, patient):
    api("dr_dlamini").post("/consultations", json={"patient_id": patient["id"], "symptoms": "ui-mine-alpha"})
    api("dr_nkosi").post("/consultations", json={"patient_id": patient["id"], "symptoms": "ui-mine-beta"})
    page = sign_in(browser, "dr_dlamini"); dismiss_password_prompt(page)
    page.click('[data-tab="2"]'); page.wait_for_timeout(500)
    text = page.inner_text("#table")
    assert "ui-mine-alpha" in text and "ui-mine-beta" not in text
    page.uncheck("#mine"); page.wait_for_timeout(300)
    assert "ui-mine-beta" in page.inner_text("#table")


@pytest.mark.parametrize("user,title", [
    ("reception1", "Reception desk"), ("dr_dlamini", "Doctor dashboard"), ("lab1", "Laboratory bench"),
    ("spec1", "Specialist clinic"), ("pharm1", "Pharmacy counter")])
def test_every_role_gets_its_dashboard(browser, user, title):
    page = sign_in(browser, user)
    assert page.inner_text("#hero-title") == title and page.locator("#stats .stat").count() >= 3 and page.errors == []


def test_small_screens_use_cards(browser, api):
    page = sign_in(browser, "reception2", viewport={"width": 390, "height": 800})
    page.wait_for_selector("#table tbody tr")
    assert page.evaluate("getComputedStyle(document.querySelector('#table tbody tr')).display") == "block"
