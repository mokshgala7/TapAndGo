"""
test_driver_photo_urls.py
─────────────────────────
Data-driven photos on the passenger's confirm-payment page: users.driver_photo_url / users.vehicle_photo_url (additive
migration 2026_11_driver_vehicle_photo_urls.sql). The backend reads them on their own, so a database that does not have
the columns yet keeps working, and only safe URLs are passed on.
"""
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.helpers import Env

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


@pytest.fixture
def scene():
    env = Env()
    driver_id = env.add_user("drv@photo.local", account_type="driver", balance=0, name="Ravi Driver",
                             vehicle_type="Luxury Taxi", vehicle_registration="MH12AB1234")
    pax_id = env.add_user("pax@photo.local", account_type="passenger", balance=1000, name="Asha")
    token = env.client.post("/api/qr/create-request", json={"amount": 150}, headers=env.user_headers(driver_id)).json()["token"]
    return {"env": env, "driver_id": driver_id, "pax_headers": env.user_headers(pax_id), "token": token}


def details(scene):
    r = scene["env"].client.get(f"/api/qr/{scene['token']}", headers=scene["pax_headers"])
    assert r.status_code == 200, r.text
    return r.json()["payment"]


def add_columns(scene):
    with scene["env"].engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN driver_photo_url VARCHAR(500)"))
        conn.execute(text("ALTER TABLE users ADD COLUMN vehicle_photo_url VARCHAR(500)"))


def set_urls(scene, driver_url, vehicle_url):
    with scene["env"].engine.begin() as conn:
        conn.execute(text("UPDATE users SET driver_photo_url = :d, vehicle_photo_url = :v WHERE id = :i"),
                     {"d": driver_url, "v": vehicle_url, "i": scene["driver_id"]})


def test_the_page_works_before_the_migration_and_has_no_photos(scene):
    p = details(scene)
    assert p["driver_photo_url"] is None and p["vehicle_photo_url"] is None
    assert p["vehicle_type"] == "Luxury Taxi" and p["vehicle_registration"] == "MH12AB1234" and p["amount"] == 150.0


def test_empty_columns_give_no_photos(scene):
    add_columns(scene)
    p = details(scene)
    assert p["driver_photo_url"] is None and p["vehicle_photo_url"] is None


def test_set_urls_are_passed_on(scene):
    add_columns(scene)
    set_urls(scene, "https://cdn.example.com/drivers/ravi.jpg", "/vehicles/hyundai-creta.jpg")
    p = details(scene)
    assert p["driver_photo_url"] == "https://cdn.example.com/drivers/ravi.jpg"
    assert p["vehicle_photo_url"] == "/vehicles/hyundai-creta.jpg"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "http://insecure.example.com/a.jpg", "//evil.example.com/a.jpg",
                                 "data:image/png;base64,AAAA", "/../../etc/passwd?x=<script>", "https://" + "a" * 600,
                                 "vehicles/no-leading-slash.jpg", " ", "ftp://x.example.com/a.jpg"])
def test_unsafe_urls_are_dropped(scene, bad):
    add_columns(scene)
    set_urls(scene, bad, bad)
    p = details(scene)
    assert p["driver_photo_url"] is None and p["vehicle_photo_url"] is None


def test_no_other_private_field_reaches_the_page(scene):
    add_columns(scene)
    set_urls(scene, "/drivers/a.jpg", "/vehicles/b.jpg")
    p = details(scene)
    assert set(p) >= {"driver_name", "vehicle_type", "vehicle_registration", "amount", "driver_photo_url", "vehicle_photo_url"}
    blob = str(p)
    assert "drv@photo.local" not in blob and "phone" not in blob


def test_the_migration_is_additive_nullable_and_idempotent():
    sql = (BACKEND / "migrations" / "2026_11_driver_vehicle_photo_urls.sql").read_text()
    code = re.sub(r"--[^\n]*", "", sql)
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert len(statements) == 2
    for s in statements:
        assert re.fullmatch(r"ALTER TABLE users ADD COLUMN IF NOT EXISTS (driver|vehicle)_photo_url VARCHAR\(500\) NULL", s), s
    assert not re.search(r"\b(DROP|DELETE|TRUNCATE|UPDATE|INSERT)\b", code, re.I)
    schema = (BACKEND / "schema_postgres.sql").read_text()
    assert "driver_photo_url VARCHAR(500) NULL" in schema and "vehicle_photo_url VARCHAR(500) NULL" in schema


def test_the_vehicle_photo_is_light_and_credited():
    folder = REPO / "frontend" / "public" / "vehicles"
    photo = folder / "hyundai-creta.jpg"
    assert photo.exists() and photo.stat().st_size < 150 * 1024
    credits = (folder / "CREDITS.md").read_text()
    for needle in ("Dairokkan9", "CC BY-SA 4.0", "commons.wikimedia.org/wiki/File:2021_Hyundai_Creta", "Changes made"):
        assert needle in credits, needle


def test_the_page_respects_reduced_motion_and_hardcodes_no_driver():
    css = (REPO / "frontend" / "src" / "pages" / "QrPay" / "QrPay.css").read_text()
    assert "prefers-reduced-motion: reduce" in css and "animation: none" in css
    jsx = (REPO / "frontend" / "src" / "pages" / "QrPay" / "QrPay.jsx").read_text()
    art = (REPO / "frontend" / "src" / "pages" / "QrPay" / "QrPayArt.jsx").read_text()
    assert "driver_photo_url" in jsx and "vehicle_photo_url" in jsx and "alt=" in jsx
    assert not re.search(r"(===?\s*27\b|driver_?id\s*[:=]\s*27\b|\bid\s*[:=]\s*27\b)", jsx + art)   # no driver id in the page code
