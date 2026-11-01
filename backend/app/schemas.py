import re
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_REGEX = re.compile(r"^[0-9]{10}$")
PINCODE_REGEX = re.compile(r"^[0-9]{6}$")
AADHAAR_REGEX = re.compile(r"^[0-9]{12}$")
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
VEHICLE_REG_REGEX = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$")
DL_REGEX = re.compile(r"^[A-Z]{2}[0-9]{13}$")
UPI_REGEX = re.compile(r"^[a-zA-Z0-9.\-_]{2,50}@[a-zA-Z0-9.\-_]{2,50}$")

class UserRegisterForm(BaseModel):
    account_type: str = "passenger"
    name: str
    email: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    aadhaar: Optional[str] = None
    email_otp: Optional[str] = None
    pan: Optional[str] = None
    password: str

    vehicle_type: Optional[str] = None
    vehicle_registration: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    driving_licence_number: Optional[str] = None

    @field_validator("account_type")
    def validate_account_type(cls, v: str) -> str:
        # Public sign-up may only create passengers and drivers; "admin" (or anything else) is never accepted.
        v_clean = (v or "").strip().lower()
        if v_clean not in ("passenger", "driver"):
            raise ValueError("Account type must be 'passenger' or 'driver'.")
        return v_clean

    @field_validator("password")
    def validate_password_length(cls, v: str) -> str:
        # Minimum shared by the website and the mobile app (which also ask for letters and
        # digits); the server enforces only the part that cannot be bypassed by a client.
        if not (8 <= len(v) <= 128):
            raise ValueError("Password must be between 8 and 128 characters.")
        return v

    @field_validator("email")

    def validate_email_format(cls, v: str) -> str:
        v_clean = v.strip()
        if not EMAIL_REGEX.match(v_clean):
            raise ValueError("Invalid email format.")
        return v_clean

    @field_validator("phone")

    def validate_phone_format(cls, v: str) -> str:
        v_clean = v.strip()
        if not PHONE_REGEX.match(v_clean):
            raise ValueError("Phone number must be exactly 10 digits.")
        return v_clean

    @field_validator("pincode")
    def validate_pincode_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip()
        if not PINCODE_REGEX.match(v_clean):
            raise ValueError("Pincode must be exactly 6 digits.")
        return v_clean

    @field_validator("email_otp")
    def validate_email_otp_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip()
        if not PINCODE_REGEX.match(v_clean):
            raise ValueError("Email OTP must be exactly 6 digits.")
        return v_clean

    @field_validator("aadhaar")

    def validate_aadhaar_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip()
        if not AADHAAR_REGEX.match(v_clean):
            raise ValueError("Aadhaar must be exactly 12 digits.")
        return v_clean

    @field_validator("pan")

    def validate_pan_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip().upper()
        if not PAN_REGEX.match(v_clean):
            raise ValueError("PAN card must match format: ABCDE1234F.")
        return v_clean

    @field_validator("vehicle_registration")

    def validate_vehicle_reg_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip().upper()
        if not VEHICLE_REG_REGEX.match(v_clean):
            raise ValueError("Invalid Vehicle Registration format (e.g. MH01AB1234).")
        return v_clean

    @field_validator("driving_licence_number")

    def validate_dl_format(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v_clean = v.strip().upper()
        if not DL_REGEX.match(v_clean):
            raise ValueError("Invalid Driving Licence Number format.")
        return v_clean

class UserLoginRequest(BaseModel):
    account: str
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    account_type: str
    email: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    profile_photo: Optional[str] = None
    vehicle_type: Optional[str] = None
    vehicle_registration: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    driving_licence_number: Optional[str] = None
    rc_document: Optional[str] = None
    licence_document: Optional[str] = None
    insurance_document: Optional[str] = None

    class Config:
        from_attributes = True

class LoginSuccessResponse(BaseModel):
    success: bool = True
    access_token: str
    token_type: str
    user_id: int
    account_type: str
    user: UserResponse

class SendOTPRequest(BaseModel):
    email: EmailStr
    account_type: str = "passenger"

class LoginFailureResponse(BaseModel):
    success: bool = False
    message: str = "Invalid Credentials"
