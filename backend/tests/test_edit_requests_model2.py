import pytest
import io
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, User, EditRequest, UserDocument, Admin
from app.utils.security import hash_password
from helpers import admin_headers
from sqlalchemy.pool import StaticPool

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture
def setup_model2_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    admin = Admin(
        name="Admin Test",
        email="admin@test.com",
        password_hash=hash_password("Admin123!"),
        is_active=True,
    )
    passenger = User(
        name="Passenger Alice",
        email="alice@test.com",
        phone="9876543210",
        password_hash=hash_password("Pass123!"),
        account_type="passenger",
        address="123 Street",
        city="Mumbai",
        bank_account_holder="Alice Pass",
        bank_account_number="123456789012",
        bank_ifsc="HDFC0001234",
        bank_upi_id="alice@hdfc",
        bank_locked=1,
        bank_request_status="none",
        phone_request_status="none",
        doc_request_status="none",
    )
    driver = User(
        name="Driver Bob",
        email="bob@test.com",
        phone="9876543211",
        password_hash=hash_password("Pass123!"),
        account_type="driver",
        bank_account_holder="Bob Driver",
        bank_account_number="987654321098",
        bank_ifsc="SBIN0001234",
        bank_upi_id="bob@sbi",
        bank_locked=1,
        bank_request_status="none",
        phone_request_status="none",
        doc_request_status="none",
    )
    db.add_all([admin, passenger, driver])
    db.commit()
    db.refresh(admin)
    db.refresh(passenger)
    db.refresh(driver)

    login_p = client.post("/api/auth/login", json={"account": "alice@test.com", "password": "Pass123!"})
    p_token = login_p.json()["token"]

    login_d = client.post("/api/auth/login", json={"account": "bob@test.com", "password": "Pass123!"})
    d_token = login_d.json()["token"]

    yield {
        "admin_id": admin.id,
        "passenger": passenger,
        "passenger_token": p_token,
        "driver": driver,
        "driver_token": d_token,
        "db": db,
    }
    db.close()


def test_phone_permission_lifecycle(setup_model2_db):
    data = setup_model2_db
    p_token = data["passenger_token"]
    admin_id = data["admin_id"]

    # 1. Direct phone edit without permission fails
    res_direct = client.put(
        "/api/auth/profile",
        json={"phone": "9998887776"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert res_direct.status_code == 400
    assert "administrator approval" in res_direct.json()["detail"].lower()

    # 2. Request phone edit permission (Model 2: no phone value provided)
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "phone", "reason": "Changed my mobile operator"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert req_res.status_code == 200
    assert req_res.json()["user"]["phone_request_status"] == "requested"

    # 3. Duplicate request is prevented
    dup_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "phone"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert dup_res.status_code == 400
    assert "already pending" in dup_res.json()["detail"].lower()

    # 4. Admin sees the request in edit-requests list
    admin_res = client.get(
        "/api/admin/edit-requests",
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert admin_res.status_code == 200
    items = admin_res.json()["items"]
    phone_req = next((it for it in items if it["field_name"] == "phone" and it["status"] == "pending"), None)
    assert phone_req is not None
    assert phone_req["new_value"] is None   # Model 2 stores no premature value (the key itself is now returned)

    # 5. Admin approves the request
    approve_res = client.post(
        f"/api/admin/edit-requests/{phone_req['id']}/review",
        json={"action": "approve"},
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert approve_res.status_code == 200

    # 6. Verify user profile now has phone_request_status == 'approved'
    me_res = client.get(f"/api/auth/profile/{data['passenger'].id}", headers={"Authorization": f"Bearer {p_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["phone_request_status"] == "approved"

    # 7. User edits and saves new phone
    save_res = client.put(
        "/api/auth/profile",
        json={"phone": "9998887776"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert save_res.status_code == 200
    user_updated = save_res.json()["user"]
    assert user_updated["phone"] == "9998887776"
    assert user_updated["phone_request_status"] == "none"

    # 8. Phone is locked again: user cannot change phone without another request
    res_again = client.put(
        "/api/auth/profile",
        json={"phone": "9991112223"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert res_again.status_code == 400


def test_phone_rejection_lifecycle(setup_model2_db):
    data = setup_model2_db
    p_token = data["passenger_token"]
    admin_id = data["admin_id"]

    # 1. User requests phone access
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "phone"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert req_res.status_code == 200

    # 2. Admin rejects request
    admin_res = client.get("/api/admin/edit-requests", headers=admin_headers(TestingSessionLocal, admin_id))
    items = admin_res.json()["items"]
    phone_req = next((it for it in items if it["field_name"] == "phone" and it["status"] == "pending"), None)
    assert phone_req is not None

    reject_res = client.post(
        f"/api/admin/edit-requests/{phone_req['id']}/review",
        json={"action": "reject", "rejection_reason": "Invalid justification"},
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert reject_res.status_code == 200

    # 3. User phone remains locked, phone_request_status is 'rejected'
    me_res = client.get(f"/api/auth/profile/{data['passenger'].id}", headers={"Authorization": f"Bearer {p_token}"})
    assert me_res.json()["user"]["phone_request_status"] == "rejected"

    save_attempt = client.put(
        "/api/auth/profile",
        json={"phone": "9112223334"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert save_attempt.status_code == 400

    # 4. User can submit a new request later
    new_req = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "phone", "reason": "Second attempt with valid docs"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert new_req.status_code == 200
    assert new_req.json()["user"]["phone_request_status"] == "requested"


def test_bank_details_permission_and_partial_edit(setup_model2_db):
    data = setup_model2_db
    p_token = data["passenger_token"]
    admin_id = data["admin_id"]

    # 1. Request bank permission (no bank values in request)
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "bank", "reason": "Need to update UPI ID"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert req_res.status_code == 200
    assert req_res.json()["user"]["bank_request_status"] == "requested"

    # Duplicate prevented
    dup_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "bank"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert dup_res.status_code == 400

    # 2. Admin approves
    admin_res = client.get("/api/admin/edit-requests", headers=admin_headers(TestingSessionLocal, admin_id))
    bank_req = next((it for it in admin_res.json()["items"] if it["field_name"] == "bank" and it["status"] == "pending"), None)
    assert bank_req is not None

    approve_res = client.post(
        f"/api/admin/edit-requests/{bank_req['id']}/review",
        json={"action": "approve"},
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert approve_res.status_code == 200

    # 3. User is now unlocked: bank_request_status == 'approved', bank_locked == 0
    me_res = client.get(f"/api/auth/profile/{data['passenger'].id}", headers={"Authorization": f"Bearer {p_token}"})
    u = me_res.json()["user"]
    assert u["bank_request_status"] == "approved"
    assert u["bank_locked"] == 0

    # 4. Partial edit: User changes only UPI ID, leaving account holder, number, and ifsc intact (or pre-filled)
    save_res = client.put(
        "/api/auth/profile",
        json={
            "bank_upi_id": "alice.new@okhdfcbank",
        },
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert save_res.status_code == 200
    saved_u = save_res.json()["user"]
    assert saved_u["bank_account_holder"] == "Alice Pass"
    assert saved_u["bank_account_number"] == "123456789012"
    assert saved_u["bank_ifsc"] == "HDFC0001234"
    assert saved_u["bank_upi_id"] == "alice.new@okhdfcbank"
    assert saved_u["bank_locked"] == 1
    assert saved_u["bank_request_status"] == "none"

    # 5. Subsequent edit without permission is rejected
    again_res = client.put(
        "/api/auth/profile",
        json={"bank_upi_id": "alice.hacked@okhdfcbank"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert again_res.status_code == 400


def test_driver_bank_request_and_approval(setup_model2_db):
    data = setup_model2_db
    d_token = data["driver_token"]
    admin_id = data["admin_id"]

    # 1. Driver requests bank permission via API
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "bank", "reason": "Changed bank branch"},
        headers={"Authorization": f"Bearer {d_token}"}
    )
    assert req_res.status_code == 200
    assert req_res.json()["user"]["bank_request_status"] == "requested"

    # 2. Admin receives and approves
    admin_res = client.get("/api/admin/edit-requests", headers=admin_headers(TestingSessionLocal, admin_id))
    bank_req = next((it for it in admin_res.json()["items"] if it["user_name"] == "Driver Bob" and it["status"] == "pending"), None)
    assert bank_req is not None

    approve_res = client.post(
        f"/api/admin/edit-requests/{bank_req['id']}/review",
        json={"action": "approve"},
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert approve_res.status_code == 200

    # 3. Driver saves new IFSC & Account number with existing holder & UPI
    save_res = client.put(
        "/api/auth/profile",
        json={
            "bank_account_holder": "Bob Driver",
            "bank_account_number": "112233445566",
            "bank_ifsc": "HDFC0009999",
            "bank_upi_id": "bob@sbi",
        },
        headers={"Authorization": f"Bearer {d_token}"}
    )
    assert save_res.status_code == 200
    saved_d = save_res.json()["user"]
    assert saved_d["bank_account_number"] == "112233445566"
    assert saved_d["bank_ifsc"] == "HDFC0009999"
    assert saved_d["bank_locked"] == 1
    assert saved_d["bank_request_status"] == "none"


def test_documents_permission_and_replacement_lifecycle(setup_model2_db):
    data = setup_model2_db
    p_token = data["passenger_token"]
    admin_id = data["admin_id"]

    # 1. Attempting to upload replacement document without approval fails
    fake_file = io.BytesIO(b"fake image content")
    unauth_upload = client.post(
        "/api/auth/profile/document",
        data={"document_type": "profile_photo"},
        files={"file": ("profile.jpg", fake_file, "image/jpeg")},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert unauth_upload.status_code == 400
    assert "not authorized" in unauth_upload.json()["detail"].lower()

    # 2. User requests document edit permission
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "documents", "reason": "Update address proof"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert req_res.status_code == 200
    assert req_res.json()["user"]["doc_request_status"] == "requested"

    # Duplicate document request prevented
    dup_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "documents"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert dup_res.status_code == 400

    # 3. Admin approves
    admin_res = client.get("/api/admin/edit-requests", headers=admin_headers(TestingSessionLocal, admin_id))
    doc_req = next((it for it in admin_res.json()["items"] if it["field_name"] == "documents" and it["status"] == "pending"), None)
    assert doc_req is not None

    approve_res = client.post(
        f"/api/admin/edit-requests/{doc_req['id']}/review",
        json={"action": "approve"},
        headers=admin_headers(TestingSessionLocal, admin_id)
    )
    assert approve_res.status_code == 200

    # 4. Upload replacement document succeeds
    fake_file = io.BytesIO(b"new document content")
    upload_res = client.post(
        "/api/auth/profile/document",
        data={"document_type": "profile_photo"},
        files={"file": ("new_avatar.png", fake_file, "image/png")},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert upload_res.status_code == 200
    upload_json = upload_res.json()
    assert upload_json["success"] is True
    assert upload_json["user"]["doc_request_status"] == "none"

    # 5. Subsequent upload is locked again
    fake_file2 = io.BytesIO(b"another doc content")
    upload_again = client.post(
        "/api/auth/profile/document",
        data={"document_type": "profile_photo"},
        files={"file": ("another.png", fake_file2, "image/png")},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert upload_again.status_code == 400


def test_unrelated_profile_saves_and_existing_bank_details(setup_model2_db):
    data = setup_model2_db
    p_token = data["passenger_token"]

    # 1. Request bank permission so bank_request_status == 'requested'
    req_res = client.post(
        "/api/auth/request-admin-access",
        json={"request_type": "bank"},
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert req_res.status_code == 200

    # 2. User updates address & city while passing unchanged existing bank details (as loaded in UI form)
    update_res = client.put(
        "/api/auth/profile",
        json={
            "address": "456 Marine Drive",
            "city": "Mumbai South",
            "bank_account_holder": "Alice Pass",
            "bank_account_number": "123456789012",
            "bank_ifsc": "HDFC0001234",
            "bank_upi_id": "alice@hdfc",
        },
        headers={"Authorization": f"Bearer {p_token}"}
    )
    assert update_res.status_code == 200
    updated_u = update_res.json()["user"]
    assert updated_u["address"] == "456 Marine Drive"
    assert updated_u["city"] == "Mumbai South"
    # Existing bank request is STILL pending and not disturbed
    assert updated_u["bank_request_status"] == "requested"
