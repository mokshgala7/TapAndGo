"""Seed (or reset) clearly-marked SYNTHETIC transaction history for driver 27 (Rakesh Sharma).

Exactly 1,000 rows, nothing else: completed ride payments credited to the driver and completed
withdrawals debited from the driver, spread over the 12 months before the anchor date and
ending the day before it.

SAFETY MODEL
- Dry-run by default. Nothing is written without --apply, and writes also require
  --confirm-project <supabase project ref>, which must match both SUPABASE_URL and DATABASE_URL.
- Only INSERTs rows it marks itself, and only DELETEs rows carrying that mark. It never UPDATEs
  any existing row and never touches `wallets`.
- The synthetic ledger starts at 0 and ends at (wallet balance - net effect of genuine rows), so
  the wallet balance is unchanged and history + genuine rows reconcile with it. If that is not
  possible (e.g. genuine rows inside the window) it refuses.
- One database transaction; the driver, the driver's wallet and every genuine transaction that
  involves the driver are fingerprinted before/after and any change rolls everything back.
- No provider, UTR, payer or idempotency values are set: no payment-gateway or bank operation is
  represented as having happened, and none is performed. No external service is contacted.

HOW SYNTHETIC ROWS ARE MARKED (no schema change)
- transactions.payment_source = 'demo_seed' and reference starts with 'DEMO-'
- passengers: email '...@demo.tapgo.invalid' (cannot receive mail), status 'suspended', and a
  bcrypt hash of a discarded random secret (nobody can authenticate as them)

USAGE (from backend/, DATABASE_URL in the environment):
    python scripts/seed_driver_demo_history.py seed                      # dry run
    python scripts/seed_driver_demo_history.py seed --apply --confirm-project <ref>
    python scripts/seed_driver_demo_history.py verify
    python scripts/seed_driver_demo_history.py reset --apply --confirm-project <ref>
"""

import argparse
import hashlib
import os
import random
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent

DRIVER_ID = 27
DRIVER_NAME = "Rakesh Sharma"
MARKER = "demo_seed"
REF_PREFIX = "DEMO-"
PASSENGER_DOMAIN = "demo.tapgo.invalid"
DEFAULT_ANCHOR = "2026-10-20"  # fixed so the dataset is deterministic and re-runs never duplicate
RNG_SEED = 27_2026
IST_OFFSET = timedelta(hours=5, minutes=30)  # activity is modelled in IST, stored as UTC like the app

N_TOTAL = 1000
N_WITHDRAWALS = 110
N_PASSENGERS = 40
BANK_PLACEHOLDER = "bank account (XXXX XXXX 4821)"  # placeholder; not any real account

# bcrypt hash of a random secret that was discarded: nobody can log in as these accounts.
UNUSABLE_HASH = "$2b$10$H6/Wqh83ehnRwKGQBRmbd.uHaZ3EbWaSFi23KkVRo91qOKr.xytCC"

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Siddharth", "Nikhil", "Rahul", "Amit",
         "Priya", "Ananya", "Neha", "Kavya", "Pooja", "Sneha", "Isha", "Meera", "Divya", "Riya",
         "Farhan", "Imran", "Zoya", "Sana", "Joseph", "Maria", "Gurpreet", "Harleen", "Tanvi", "Manish",
         "Deepak", "Suresh", "Lakshmi", "Anjali", "Varun", "Kunal", "Shruti", "Pallavi", "Yash", "Mihir"]
LAST = ["Mehta", "Desai", "Patil", "Kulkarni", "Iyer", "Nair", "Reddy", "Singh", "Kapoor", "Joshi",
        "Shah", "Gupta", "Verma", "Khan", "Fernandes", "D'Souza", "Pillai", "Bose", "Chopra", "Malhotra",
        "Naik", "Shetty", "Agarwal", "Bhatt", "Sawant", "Jadhav", "More", "Pawar", "Rao", "Menon"]

HOUR_WEIGHTS = [0.2, 0.1, 0.1, 0.15, 0.3, 0.8, 1.6, 3.0, 4.0, 3.5, 2.5, 2.2,
                2.4, 2.2, 2.0, 2.2, 2.6, 3.5, 4.2, 4.0, 3.0, 2.0, 1.0, 0.5]
DOW_WEIGHTS = [1.0, 1.0, 1.0, 1.0, 1.15, 1.3, 1.1]  # Mon..Sun


class SeedError(RuntimeError):
    pass


# A row belongs to this dataset only if ALL of these hold. Other demo datasets share the
# 'demo_seed' marker and the 'DEMO-' prefix (e.g. DEMO-P69-* passenger history), so the marker
# and prefix alone are never enough to delete or count a row.
OWNED_SQL = ("payment_source = :m AND driver_id = :d AND wallet_id = :w "
             "AND (reference LIKE :p_txn OR reference LIKE :p_wd)")


def _owned_params(wallet_id):
    return {"m": MARKER, "d": DRIVER_ID, "w": wallet_id,
            "p_txn": f"{REF_PREFIX}TXN-%", "p_wd": f"{REF_PREFIX}WD-%"}


# ---------------------------------------------------------------- dataset generation (pure)
def _fare(rng):
    r = rng.random()
    if r < 0.46:
        x = rng.uniform(30, 110)      # short auto hop
    elif r < 0.80:
        x = rng.uniform(110, 260)     # medium city ride
    elif r < 0.97:
        x = rng.uniform(260, 620)     # taxi
    else:
        x = rng.uniform(620, 1450)    # long / airport
    x = round(x / 5) * 5 if rng.random() < 0.6 else round(x)
    return max(25, int(x))


def _withdraw_amount(rng, bal):
    if bal < 300:
        return None
    amt = min(int(bal * rng.uniform(0.5, 0.95) // 100) * 100, 5000)
    return amt if amt >= 100 else None


def _timestamps(rng, anchor):
    """N_TOTAL strictly increasing UTC datetimes within [anchor-365d, anchor-1d] (IST dates)."""
    first_day = datetime.combine(anchor - timedelta(days=365), datetime.min.time())
    weights = []
    for k in range(365):
        d = first_day + timedelta(days=k)
        w = DOW_WEIGHTS[d.weekday()]
        w *= 1.15 if d.month in (10, 11) else 0.9 if d.month in (7, 8) else 1.0
        if rng.random() < 0.08:
            w *= 0.05  # day off
        weights.append(w)
    stamps = []
    for _ in range(N_TOTAL):
        day = rng.choices(range(365), weights=weights)[0]
        hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
        ist = first_day + timedelta(days=day, hours=hour, minutes=rng.randrange(60), seconds=rng.randrange(60))
        stamps.append(ist - IST_OFFSET)
    stamps.sort()
    for i in range(1, len(stamps)):
        if stamps[i] <= stamps[i - 1]:
            stamps[i] = stamps[i - 1] + timedelta(seconds=1)
    return stamps


def build_dataset(anchor, target_end_balance):
    """Return (passengers, events). Ledger starts at 0, never goes negative, ends at target."""
    rng = random.Random(RNG_SEED)
    stamps = _timestamps(rng, anchor)
    kinds = ["ride"] * N_TOTAL
    chosen = set()
    for k in range(N_WITHDRAWALS - 1):  # stratified across the year; the final row is forced below
        pos = int((k + 0.5) * (N_TOTAL - 1) / (N_WITHDRAWALS - 1) + rng.uniform(-3, 3))
        pos = min(max(pos, 0), N_TOTAL - 2)
        while pos in chosen:
            pos = (pos + 1) % (N_TOTAL - 1)
        chosen.add(pos)
    for pos in chosen:
        kinds[pos] = "wd"
    kinds[-1] = "wd"  # the year ends with the driver cashing out, so the ledger returns to target

    for attempt in range(500):
        arng = random.Random(RNG_SEED * 1000 + attempt)
        bal, events = 0, []
        for ts, kind in zip(stamps[:-1], kinds[:-1]):
            amount = None
            if kind == "wd":
                amount = _withdraw_amount(arng, bal)
            if amount is None:
                kind, amount = "ride", _fare(arng)
                bal += amount
            else:
                kind = "wd"
                bal -= amount
            events.append({"kind": kind, "ts": ts, "amount": amount, "balance_after": bal})
        last = bal - target_end_balance
        if 100 <= last <= 8000:
            events.append({"kind": "wd", "ts": stamps[-1], "amount": last, "balance_after": target_end_balance})
            break
    else:
        raise SeedError("Could not build a ledger that ends at the required balance.")

    names, seen = [], set()
    while len(names) < N_PASSENGERS:
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in seen:
            seen.add(n)
            names.append(n)
    passengers = [{"name": n, "email": f"demo.passenger{i + 1:03d}@{PASSENGER_DOMAIN}",
                   "phone": f"+9100000{i + 1:05d}"} for i, n in enumerate(names)]
    weights = [1 / (i + 4) ** 0.6 for i in range(N_PASSENGERS)]
    nr = nw = 0
    for ev in events:
        if ev["kind"] == "ride":
            nr += 1
            ev["reference"] = f"{REF_PREFIX}TXN-{nr:06d}"
            ev["passenger_email"] = rng.choices(passengers, weights=weights)[0]["email"]
        else:
            nw += 1
            ev["reference"] = f"{REF_PREFIX}WD-{nw:06d}"
            ev["passenger_email"] = None
    return passengers, events


def _row(ev, wallet_id, passenger_ids):
    amt = float(ev["amount"])
    row = {"reference": ev["reference"], "driver_id": DRIVER_ID, "wallet_id": wallet_id, "amount": amt,
           "balance_after": float(ev["balance_after"]), "created_at": ev["ts"], "updated_at": ev["ts"],
           "passenger_id": None, "payment_source": MARKER}
    if ev["kind"] == "ride":  # same shape as the QR ride payments the app writes
        row.update(passenger_id=passenger_ids[ev["passenger_email"]], payment_method="QR",
                   transaction_type="ride_payment", description=f"₹{amt:.2f} paid to {DRIVER_NAME} via QR")
    else:  # same shape as existing completed 'withdrawal' rows
        row.update(payment_method="bank_transfer", transaction_type="withdrawal",
                   description=f"₹{amt:.2f} transferred to {BANK_PLACEHOLDER}")
    return row


# ---------------------------------------------------------------- database operations
def _dt(value):
    """Timestamps come back as datetimes from PostgreSQL but as strings from SQLite (tests)."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _signed(row):
    """Effect of a genuine row on the driver's balance, mirroring GET /api/wallet/{id}/transactions."""
    amt = Decimal(str(row["amount"]))
    t, pm = row["transaction_type"], row["payment_method"]
    if t == "withdrawal_reversal":
        return abs(amt)
    if t == "deposit" and row["passenger_id"] != DRIVER_ID:
        return abs(amt)
    if row["passenger_id"] == DRIVER_ID:
        credit = pm in ("razorpay", "topup", "payment_gateway", "deposit", "upi") or t == "deposit" or amt < 0
        return abs(amt) if credit else -abs(amt)
    if row["driver_id"] == DRIVER_ID:
        return -abs(amt) if (pm == "bank_transfer" or t == "withdrawal") else abs(amt)
    return amt if amt > 0 else -abs(amt)


def _context(conn):
    user = conn.execute(text("SELECT id, account_type, name, status FROM users WHERE id=:i"),
                        {"i": DRIVER_ID}).mappings().first()
    if not user:
        raise SeedError(f"User {DRIVER_ID} not found.")
    if (user["account_type"], user["name"], user["status"]) != ("driver", DRIVER_NAME, "active"):
        raise SeedError(f"User {DRIVER_ID} is not the active driver '{DRIVER_NAME}'; refusing.")
    wallet = conn.execute(text("SELECT id, balance, is_frozen FROM wallets WHERE user_id=:i"),
                          {"i": DRIVER_ID}).mappings().first()
    if not wallet:
        raise SeedError(f"User {DRIVER_ID} has no wallet; refusing to create one.")
    genuine = conn.execute(text(
        "SELECT * FROM transactions WHERE COALESCE(payment_source,'')<>:m AND "
        "(wallet_id=:w OR passenger_id=:u OR driver_id=:u) ORDER BY created_at, id"),
        {"m": MARKER, "w": wallet["id"], "u": DRIVER_ID}).mappings().all()
    genuine = [dict(g) for g in genuine]
    for g in genuine:
        g["created_at"] = _dt(g["created_at"])
    return user, wallet, genuine


def _fingerprint(conn, wallet_id):
    h = hashlib.sha256()
    for sql, p in (
        ("SELECT * FROM users WHERE id=:u", {"u": DRIVER_ID}),
        ("SELECT * FROM wallets WHERE id=:w", {"w": wallet_id}),
        ("SELECT * FROM transactions WHERE COALESCE(payment_source,'')<>:m AND "
         "(wallet_id=:w OR passenger_id=:u OR driver_id=:u) ORDER BY id", {"m": MARKER, "w": wallet_id, "u": DRIVER_ID}),
    ):
        for r in conn.execute(text(sql), p):
            h.update(repr(tuple(r)).encode())
    return h.hexdigest()


def _plan(conn, anchor):
    user, wallet, genuine = _context(conn)
    window_end = datetime.combine(anchor, datetime.min.time()) - IST_OFFSET  # anchor midnight IST, in UTC
    if any(g["created_at"] is None or g["created_at"] < window_end for g in genuine):
        raise SeedError("Genuine rows exist inside the synthetic window; cannot keep the ledger consistent.")
    target = Decimal(str(wallet["balance"])) - sum((_signed(g) for g in genuine), Decimal(0))
    if target < 0 or target != target.to_integral_value():
        raise SeedError(f"Cannot reconcile: required ledger end balance would be {target}.")
    passengers, events = build_dataset(anchor, int(target))
    return user, wallet, genuine, passengers, events, int(target)


def _existing_signature(conn, wallet_id):
    rows = conn.execute(text(
        "SELECT t.reference, u.email, t.amount, t.status, t.transaction_type, t.created_at, t.balance_after "
        "FROM transactions t LEFT JOIN users u ON u.id=t.passenger_id "
        f"WHERE t.id IN (SELECT id FROM transactions WHERE {OWNED_SQL}) ORDER BY t.created_at, t.id"),
        _owned_params(wallet_id)).all()
    return [(r[0], r[1], float(r[2]), r[3], r[4], _dt(r[5]), float(r[6])) for r in rows]


def _expected_signature(events):
    out = []
    for ev in events:
        v = _row(ev, 0, {ev["passenger_email"]: 0})
        out.append((v["reference"], ev["passenger_email"], v["amount"], "completed", v["transaction_type"],
                    v["created_at"], v["balance_after"]))
    return out


def do_seed(engine, anchor, apply):
    with engine.connect() as probe:  # read-only planning
        user, wallet, genuine, passengers, events, target = _plan(probe, anchor)
        existing = _existing_signature(probe, wallet["id"])
        have = probe.execute(text("SELECT COUNT(*) FROM users WHERE email LIKE :p"),
                             {"p": f"%@{PASSENGER_DOMAIN}"}).scalar()
        probe.rollback()
    kinds = Counter(e["kind"] for e in events)
    print(f"[plan] {len(events)} rows: {kinds['ride']} ride payments, {kinds['wd']} withdrawals; "
          f"{events[0]['ts']} .. {events[-1]['ts']} (UTC); ledger 0 -> {target}; "
          f"wallet stays {wallet['balance']}; genuine rows kept: {len(genuine)}")
    if existing == _expected_signature(events) and have == N_PASSENGERS:
        print("[ok] Identical synthetic dataset already present; nothing to do.")
        return
    if not apply:
        print("[dry-run] No changes written. Re-run with --apply --confirm-project <ref> to write.")
        return

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _, wallet, genuine = _context(conn)
            before = _fingerprint(conn, wallet["id"])
            conn.execute(text(f"DELETE FROM transactions WHERE {OWNED_SQL}"), _owned_params(wallet["id"]))
            ids = {}
            for p in passengers:
                found = conn.execute(text("SELECT id FROM users WHERE email=:e"), {"e": p["email"]}).first()
                if found:
                    ids[p["email"]] = found[0]
                    continue
                ids[p["email"]] = conn.execute(text(
                    "INSERT INTO users(account_type,name,email,phone,city,state,password_hash,status,"
                    "bank_locked,bank_request_status,doc_request_status,phone_request_status,created_at,updated_at) "
                    "VALUES ('passenger',:n,:e,:ph,'Mumbai','Maharashtra',:h,'suspended',0,'none','none','none',:c,:c) "
                    "RETURNING id"),
                    {"n": p["name"], "e": p["email"], "ph": p["phone"], "h": UNUSABLE_HASH,
                     "c": events[0]["ts"] - timedelta(days=1)}).scalar()
            rows = [_row(ev, wallet["id"], ids) for ev in events]
            conn.execute(text(
                "INSERT INTO transactions(reference,passenger_id,driver_id,wallet_id,amount,payment_method,status,"
                "otp_verified,fraud_status,transaction_type,description,balance_after,payment_source,created_at,updated_at) "
                "VALUES (:reference,:passenger_id,:driver_id,:wallet_id,:amount,:payment_method,'completed',"
                "true,'clear',:transaction_type,:description,:balance_after,:payment_source,:created_at,:updated_at)"),
                rows)
            if _fingerprint(conn, wallet["id"]) != before:
                raise SeedError("Genuine data fingerprint changed; rolling back.")
            n = conn.execute(text(f"SELECT COUNT(*) FROM transactions WHERE {OWNED_SQL}"),
                             _owned_params(wallet["id"])).scalar()
            if n != N_TOTAL:
                raise SeedError(f"Expected {N_TOTAL} synthetic rows, found {n}; rolling back.")
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
    print(f"[ok] Committed {N_TOTAL} synthetic transactions and {len(passengers)} synthetic passengers.")


def do_reset(engine, apply):
    with engine.connect() as conn:
        user, wallet, _ = _context(conn)
        n = conn.execute(text(f"SELECT COUNT(*) FROM transactions WHERE {OWNED_SQL}"),
                         _owned_params(wallet["id"])).scalar()
        conn.rollback()
        print(f"[plan] would remove {n} synthetic transactions (and orphaned synthetic passengers).")
        if not apply:
            print("[dry-run] No changes written.")
            return
        trans = conn.begin()
        try:
            before = _fingerprint(conn, wallet["id"])
            conn.execute(text(f"DELETE FROM transactions WHERE {OWNED_SQL}"), _owned_params(wallet["id"]))
            m = conn.execute(text(
                "DELETE FROM users WHERE email LIKE :e AND account_type='passenger' AND status='suspended' "
                "AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.passenger_id=users.id OR t.driver_id=users.id)"),
                {"e": f"demo.passenger%@{PASSENGER_DOMAIN}"}).rowcount
            if _fingerprint(conn, wallet["id"]) != before:
                raise SeedError("Genuine data fingerprint changed; rolling back.")
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
    print(f"[ok] Removed {n} synthetic transactions and {m} synthetic passengers.")


def do_verify(engine, anchor):
    with engine.connect() as conn:
        user, wallet, genuine = _context(conn)
        syn = conn.execute(text(f"SELECT * FROM transactions WHERE {OWNED_SQL} ORDER BY created_at, id"),
                           _owned_params(wallet["id"])).mappings().all()
        print(f"driver {DRIVER_ID}: {user['name']} ({user['account_type']}, {user['status']}); "
              f"wallet balance {wallet['balance']}; genuine rows {len(genuine)}; synthetic rows {len(syn)}")
        print("by type/status/direction:", dict(Counter((r["transaction_type"], r["status"], r["payment_method"])
                                                         for r in syn)))
        if syn:
            print(f"range (UTC): {syn[0]['created_at']} .. {syn[-1]['created_at']}")
            print("distinct passengers:", len({r["passenger_id"] for r in syn if r["passenger_id"]}))
        rows = [dict(r) for r in conn.execute(text(
            "SELECT * FROM transactions WHERE wallet_id=:w OR passenger_id=:u OR driver_id=:u ORDER BY created_at, id"),
            {"w": wallet["id"], "u": DRIVER_ID}).mappings()]
        prev, bad = Decimal(0), 0
        for r in rows:
            if r["payment_source"] == MARKER:
                if abs(prev + _signed(r) - Decimal(str(r["balance_after"]))) > Decimal("0.005") or r["balance_after"] < 0:
                    bad += 1
                prev = Decimal(str(r["balance_after"]))
            else:
                prev += _signed(r)  # genuine rows keep their own stored balance_after convention
        print(f"synthetic ledger breaks: {bad}; ledger end incl. genuine rows {prev} (wallet {wallet['balance']})")
        conn.rollback()


# ---------------------------------------------------------------- CLI
def _project_ref_from_supabase_url():
    url = os.getenv("SUPABASE_URL", "")
    if not url:
        env = BACKEND_DIR / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("SUPABASE_URL="):
                    url = line.split("=", 1)[1].strip()
    m = re.search(r"https://([a-z0-9]+)\.supabase\.co", url)
    return m.group(1) if m else None


def engine_from_environment(confirm_ref):
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if not raw.startswith("postgresql"):
        raise SeedError("DATABASE_URL must be a PostgreSQL (Supabase) URL; refusing to fall back to anything else.")
    url = make_url(raw.replace("postgresql://", "postgresql+psycopg2://", 1))
    ref = _project_ref_from_supabase_url()
    if not ref or ref not in raw or "supabase" not in raw:
        raise SeedError("DATABASE_URL does not match the SUPABASE_URL project; refusing.")
    if confirm_ref != ref:
        raise SeedError("--confirm-project does not match the Supabase project ref; refusing.")
    return create_engine(url, connect_args={"sslmode": "require", "connect_timeout": 15}, pool_pre_ping=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["seed", "verify", "reset"])
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--confirm-project", default="", help="Supabase project ref, required with --apply")
    ap.add_argument("--anchor", default=DEFAULT_ANCHOR, help="'today' of the dataset, YYYY-MM-DD")
    args = ap.parse_args(argv)
    anchor = date.fromisoformat(args.anchor)
    try:
        if args.apply and not args.confirm_project:
            raise SeedError("--apply requires --confirm-project <ref>.")
        engine = engine_from_environment(args.confirm_project or _project_ref_from_supabase_url())
        {"seed": lambda: do_seed(engine, anchor, args.apply),
         "reset": lambda: do_reset(engine, args.apply),
         "verify": lambda: do_verify(engine, anchor)}[args.action]()
    except SeedError as exc:
        print(f"[refused] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # never echo driver messages: they can contain connection details
        print(f"[error] {type(exc).__name__} (details suppressed)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
