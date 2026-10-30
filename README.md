# Tap&Go — Smart Transit Payouts & Cashless Payment Platform

Tap&Go is a modern, secure, and instant cashless payment and payout ecosystem built for transit (passengers, drivers, and fleet operators). It features Razorpay Standard Checkout for wallet funding, internal wallet-to-wallet ride payments, Email OTP protected withdrawals, NFC Tap-to-Pay, QR Payments, digital signature integration, document verification, database-backed wallet management, admin request approval workflows, and role-based dashboards.

---

## ML fraud detection

Ride payments are checked by an XGBoost fraud-risk model (V6) plus plain rules; a flagged payment needs an emailed OTP that is entered on the driver's POS. Trained and evaluated on synthetic data only. See [docs/ML_FRAUD_OVERVIEW.md](docs/ML_FRAUD_OVERVIEW.md) and the training code, data notes and results in [`ml/`](ml/README.md).

## 1. Project Architecture

**Frontend:**
React + Vite → Hosted on Vercel
- Production frontend: `https://www.thetapandgo.in`

**Backend:**
FastAPI → Hosted on Render
- Production API: `https://api.thetapandgo.in`

**Database:**
- Supabase PostgreSQL

---

## 2. Production Request Flow

Explain:

Browser
  ↓
www.thetapandgo.in
  ↓
Vercel
  ↓
api.thetapandgo.in
  ↓
Render FastAPI
  ↓
Supabase PostgreSQL

---

## 3. Domain Configuration

`thetapandgo.in` redirects to: `www.thetapandgo.in`

**Frontend DNS Configuration (Conceptual):**
- **A Record**: `@` → `216.198.79.1`
- **CNAME Record**: `www` → `0d1c15a97bcd503b.vercel-dns-017.com`

**API Domain Configuration:**
`api.thetapandgo.in` points to the Render FastAPI service using the DNS record/value provided by Render. *(Note: The exact DNS target value must be provided by Render)*.

---

## 4. CORS (Cross-Origin Resource Sharing)

The FastAPI backend allows requests from the following production frontend origins:
- `https://www.thetapandgo.in`
- `https://thetapandgo.in`

Additionally, the following origins are supported for development and testing:
- `http://localhost:5173`
- `https://tap-go-frontend.vercel.app` (Vercel deployment URL)

---

## 5. Environment Variables

> **Note:** Never commit actual secret values to the repository. Use placeholders in configuration files.

### Development / Local Variables
**Backend (`backend/.env`):**
```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<LOCAL_DB_PASSWORD>
DB_NAME=tapgo
SECRET_KEY=<LOCAL_JWT_SECRET>
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://www.thetapandgo.in,https://thetapandgo.in
```

**Frontend (`frontend/.env.local`):**
```ini
VITE_API_BASE_URL=http://localhost:8000
VITE_DEMO_MODE=true
```

### Production / Vercel Variables
Configured in Vercel Dashboard -> Settings -> Environment Variables.
```ini
VITE_API_BASE_URL=https://api.thetapandgo.in
VITE_DEMO_MODE=false
```

### Production / Render Variables
Configured in Render Dashboard -> Environment.
```ini
DATABASE_URL=<SUPABASE_POSTGRES_URL>
SECRET_KEY=<PRODUCTION_JWT_SECRET>
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://www.thetapandgo.in,https://thetapandgo.in,https://tap-go-frontend.vercel.app
AWS_ACCESS_KEY_ID=<AWS_KEY>
AWS_SECRET_ACCESS_KEY=<AWS_SECRET>
AWS_REGION=ap-south-1
SES_FROM_EMAIL=tapandgosupport@gmail.com
SUPABASE_URL=<SUPABASE_URL>
SUPABASE_SERVICE_ROLE_KEY=<SUPABASE_SERVICE_ROLE_KEY>
SUPABASE_STORAGE_BUCKET=verification-documents
```

---

## 6. Deployment Flow

1. **Step 1:** Push code to GitHub.
2. **Step 2:** Vercel deploys the React/Vite frontend.
3. **Step 3:** Vercel custom domain configuration is applied (`www.thetapandgo.in`).
4. **Step 4:** Render hosts the FastAPI backend.
5. **Step 5:** Configure Render custom domain (`api.thetapandgo.in`) in the Render dashboard.
6. **Step 6:** Add the DNS record requested by Render in GoDaddy.
7. **Step 7:** Verify HTTPS/TLS for `api.thetapandgo.in`.
8. **Step 8:** Set the production frontend API URL (`VITE_API_BASE_URL`) in Vercel to: `https://api.thetapandgo.in`.
9. **Step 9:** Configure FastAPI CORS (`ALLOWED_ORIGINS`) in Render to allow `https://www.thetapandgo.in` and `https://thetapandgo.in`.
10. **Step 10:** Verify frontend → API → Supabase communication.
11. **Step 11:** Only after everything works, configure AWS SES separately.

---

## 7. Production Architecture Diagram

```text
       User
         ↓
 www.thetapandgo.in
         ↓
       Vercel
         ↓ HTTPS
 api.thetapandgo.in
         ↓
   Render FastAPI
         ↓
 Supabase PostgreSQL
```

---

## 8. Local Development Flow

```text
 React/Vite localhost
         ↓
   Local FastAPI
         ↓
 Supabase PostgreSQL (or Local MySQL)
```

The existing local setup remains fully intact for development, utilizing `http://localhost:5173` for the frontend and `http://localhost:8000` for the backend.

---

## 9. Deployment Notes

- **Separation of Concerns:** Frontend and backend are separate deployments.
- **Security:** The frontend must never contain backend secrets. Database credentials remain strictly server-side.
- **CORS Management:** CORS controls which frontend origins can call the API. Ensure Render environment variables reflect allowed domains.
- **Email Delivery:** AWS SES configuration is a later deployment step handled entirely via Render environment variables.
