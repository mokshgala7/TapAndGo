"""Seed (or reset) clearly-marked DEMO transaction history for passengers 69 and 70.

Exactly 60 rows per passenger (120 in total): 48 completed ride payments to fictional drivers and
12 simulated wallet top-ups, spread over the six months before the anchor date. This is NOT the
offline ML dataset (TapGo-ML/data/synthetic_passenger_driver_v1), which stays offline.

SAFETY MODEL
- Dry-run by default. Nothing is written without --apply, and writes also require
  --confirm-project <supabase project ref>, which must match both SUPABASE_URL and DATABASE_URL.
- Only INSERTs rows it owns and only DELETEs rows it owns. It never UPDATEs anything, never
  touches `wallets`, and never creates users (no driver accounts: driver_id stays NULL).
- Refuses unless each passenger is the expected active passenger, has a wallet with balance 0.00,
  and has no genuine (non-demo) transactions. The demo ledger for each passenger starts at 0 and
  returns to 0 after every block of rides, so stored balance_after values are internally
  consistent and the history ends at the real wallet balance (0.00), which is never changed.
- One database transaction. The two passengers, every wallet, and every transaction this script
  does not own are fingerprinted before/after; any change rolls everything back.
- No provider, provider_transaction_id, UTR, payer, idempotency key, payment request or email
  fields are set: no payment-gateway, bank or wallet operation is represented as having happened,
  and none is performed. No external service is contacted.

OWNED ROWS (no schema change) — a row belongs to this script only if ALL of these hold:
  payment_source = 'demo_seed'
  reference LIKE 'DEMO-P69-%' with passenger_id = 69  (or 'DEMO-P70-%' with passenger_id = 70)
  wallet_id = that passenger's wallet id
  driver_id IS NULL
The dashboards label these rows as demo; admin dashboard totals already exclude payment_source
'demo_seed'.

USAGE (from backend/):
    python scripts/seed_passenger_demo_history.py seed                      # dry run
    python scripts/seed_passenger_demo_history.py seed --apply --confirm-project <ref>
    python scripts/seed_passenger_demo_history.py verify
    python scripts/seed_passenger_demo_history.py reset                     # dry run
    python scripts/seed_passenger_demo_history.py reset --apply --confirm-project <ref>
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

MARKER = "demo_seed"
DEFAULT_ANCHOR = "2026-10-20"   # fixed so the plan is deterministic and re-runs never duplicate
WINDOW_DAYS = 182
IST_OFFSET = timedelta(hours=5, minutes=30)  # modelled in IST, stored as naive UTC like the app

N_RIDES = 48
N_TOPUPS = 12
RIDES_PER_TOPUP = N_RIDES // N_TOPUPS
N_PER_PASSENGER = N_RIDES + N_TOPUPS
MIN_RIDE_GAP = timedelta(minutes=40)

TOPUP_METHOD = "demo_topup"
TOPUP_DESCRIPTION = "Demo wallet top-up (simulated - no payment was made)"
RIDE_DESCRIPTION = "₹{amount:.2f} paid to {driver} (demo driver) via {method}"

#                0    1    2    3    4    5    6    7    8    9   10   11
#               12   13   14   15   16   17   18   19   20   21   22   23
_HOURS_DAY = [0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 1.0, 4.0, 9.0, 8.0, 4.0, 3.0,
              3.0, 3.0, 2.5, 2.5, 3.0, 6.0, 8.0, 6.0, 3.0, 1.5, 0.5, 0.2]
_HOURS_EVE = [3.0, 1.0, 0.3, 0.1, 0.0, 0.1, 0.3, 1.0, 2.0, 2.0, 2.0, 2.0,
              2.5, 2.5, 2.0, 2.0, 3.0, 4.0, 6.0, 7.0, 7.0, 7.0, 6.0, 5.0]

PASSENGERS = {
    69: {
        "name": "Moksh Gala", "seed": 69_2026, "hours": _HOURS_DAY,
        "vehicle_mix": {"auto_rickshaw": 0.8, "taxi": 0.2},
        "fare_median": {"auto_rickshaw": 100.0, "taxi": 220.0}, "nfc_share": 0.7,
        "drivers": {"auto_rickshaw": ["Ravi Kadam", "Suresh Pawar", "Ganesh More", "Prakash Jadhav"],
                    "taxi": ["Joseph D'Souza", "Rajesh Iyer"]},
    },
    70: {
        "name": "Aarav Sharma", "seed": 70_2026, "hours": _HOURS_EVE,
        "vehicle_mix": {"auto_rickshaw": 0.25, "taxi": 0.75},
        "fare_median": {"auto_rickshaw": 140.0, "taxi": 340.0}, "nfc_share": 0.35,
        "drivers": {"auto_rickshaw": ["Imran Shaikh", "Anil Gaikwad"],
                    "taxi": ["Harpreet Gill", "Manoj Tiwari", "Farhan Qureshi", "Arjun Menon"]},
    },
}
MIN_FARE = {"auto_rickshaw": Decimal("25"), "taxi": Decimal("30")}


class SeedError(RuntimeError):
    pass


def ref_prefix(pid):
    return f"DEMO-P{pid}-"


# ---------------------------------------------------------------- plan generation (pure)
def build_plan(pid, anchor):
    """The 60 demo rows for one passenger, in time order, with a consistent running balance."""
    prof = PASSENGERS[pid]
    rng = random.Random(prof["seed"])
    end_utc = datetime.combine(anchor, datetime.min.time()) - IST_OFFSET   # anchor midnight IST
    start_utc = end_utc - timedelta(days=WINDOW_DAYS)

    stamps = []
    while len(stamps) < N_RIDES:
        day = rng.randrange(WINDOW_DAYS)
        hour = rng.choices(range(24), weights=prof["hours"])[0]
        ist = start_utc + IST_OFFSET + timedelta(days=day, hours=hour, minutes=rng.randrange(60),
                                                 seconds=rng.randrange(60))
        ts = ist - IST_OFFSET
        if start_utc + timedelta(hours=3) <= ts < end_utc and all(abs(ts - s) >= MIN_RIDE_GAP for s in stamps):
            stamps.append(ts)
    stamps.sort()

    rides = []
    for ts in stamps:
        vehicle = rng.choices(list(prof["vehicle_mix"]), weights=list(prof["vehicle_mix"].values()))[0]
        fare = Decimal(round(prof["fare_median"][vehicle] * rng.lognormvariate(0, 0.3)))
        night = (ts + IST_OFFSET).hour >= 22 or (ts + IST_OFFSET).hour < 6
        if night:
            fare = (fare * Decimal("1.25")).quantize(Decimal("1"))
        rides.append({"ts": ts, "amount": max(MIN_FARE[vehicle], fare).quantize(Decimal("0.01")),
                      "method": "NFC" if rng.random() < prof["nfc_share"] else "QR",
                      "driver": rng.choice(prof["drivers"][vehicle])})

    rows, balance, prev_ts = [], Decimal("0.00"), start_utc
    for b in range(N_TOPUPS):
        block = rides[b * RIDES_PER_TOPUP:(b + 1) * RIDES_PER_TOPUP]
        topup = sum((r["amount"] for r in block), Decimal("0.00"))
        first = block[0]["ts"]
        lead = timedelta(minutes=rng.randint(10, 180))
        t_ts = max(first - lead, prev_ts + (first - prev_ts) / 2)
        balance += topup
        rows.append({"reference": f"{ref_prefix(pid)}TOPUP-{b + 1:04d}", "kind": "topup",
                     "created_at": t_ts.replace(microsecond=0), "amount": topup,
                     "payment_method": TOPUP_METHOD, "transaction_type": "deposit",
                     "description": TOPUP_DESCRIPTION, "balance_after": balance, "driver_name": None})
        for r in block:
            balance -= r["amount"]
            rows.append({"reference": f"{ref_prefix(pid)}RIDE-{len([x for x in rows if x['kind'] == 'ride']) + 1:04d}",
                         "kind": "ride", "created_at": r["ts"], "amount": r["amount"],
                         "payment_method": r["method"], "transaction_type": "ride_payment",
                         "description": RIDE_DESCRIPTION.format(amount=r["amount"], driver=r["driver"], method=r["method"]),
                         "balance_after": balance, "driver_name": r["driver"]})
        prev_ts = block[-1]["ts"]
    _check_plan(pid, rows)
    return rows


def _check_plan(pid, rows):
    if len(rows) != N_PER_PASSENGER or len({r["reference"] for r in rows}) != N_PER_PASSENGER:
        raise SeedError(f"Plan for {pid} does not have {N_PER_PASSENGER} unique rows.")
    bal = Decimal("0.00")
    for prev, r in zip([None] + rows[:-1], rows):
        if prev and r["created_at"] <= prev["created_at"]:
            raise SeedError(f"Plan for {pid} is not in strict time order.")
        bal += r["amount"] if r["kind"] == "topup" else -r["amount"]
        if bal != r["balance_after"] or bal < 0:
            raise SeedError(f"Plan for {pid} has an inconsistent running balance at {r['reference']}.")
    if bal != 0:
        raise SeedError(f"Plan for {pid} does not end at 0.00.")


# ---------------------------------------------------------------- database operations
def _owned_clause(suffix=""):
    """SQL for 'owned by this script'; `suffix` lets several passengers' clauses share one query."""
    return (f"payment_source = :m AND reference LIKE :p{suffix} AND passenger_id = :pid{suffix} "
            f"AND wallet_id = :w{suffix} AND driver_id IS NULL")


def _context(conn, pid):
    user = conn.execute(text("SELECT id, name, account_type, status FROM users WHERE id = :i"),
                        {"i": pid}).mappings().first()
    if not user:
        raise SeedError(f"User {pid} not found.")
    exp = PASSENGERS[pid]["name"]
    if (user["account_type"], user["name"], user["status"]) != ("passenger", exp, "active"):
        raise SeedError(f"User {pid} is not the active passenger '{exp}'; refusing.")
    wallet = conn.execute(text("SELECT id, balance, is_frozen FROM wallets WHERE user_id = :i"),
                          {"i": pid}).mappings().first()
    if not wallet:
        raise SeedError(f"User {pid} has no wallet; refusing to create one.")
    if Decimal(str(wallet["balance"])) != Decimal("0"):
        raise SeedError(f"Wallet of user {pid} is {wallet['balance']}, not 0.00; the demo ledger "
                        "could not reconcile with it. Refusing.")
    params = {"m": MARKER, "p": f"{ref_prefix(pid)}%", "pid": pid, "w": wallet["id"]}
    genuine = conn.execute(text(
        f"SELECT COUNT(*) FROM transactions WHERE (passenger_id = :pid OR wallet_id = :w) "
        f"AND NOT ({_owned_clause()})"), params).scalar()
    if genuine:
        raise SeedError(f"User {pid} has {genuine} genuine transaction(s); demo history would not "
                        "reconcile with them. Refusing.")
    clash = conn.execute(text(
        f"SELECT COUNT(*) FROM transactions WHERE reference LIKE :p AND NOT ({_owned_clause()})"), params).scalar()
    if clash:
        raise SeedError(f"{clash} row(s) not owned by this script use the {ref_prefix(pid)} prefix. Refusing.")
    return user, wallet, params


def _fingerprint(conn, ctx):
    """Everything this script must never change: the passengers, all wallets, all non-owned rows."""
    owned = " OR ".join(f"({_owned_clause(f'_{pid}')})" for pid in ctx)
    params = {"m": MARKER}
    for pid, (_, wallet, p) in ctx.items():
        params.update({f"p_{pid}": p["p"], f"pid_{pid}": pid, f"w_{pid}": wallet["id"]})
    h = hashlib.sha256()
    for sql, p in (
        ("SELECT * FROM users WHERE id IN (69, 70) ORDER BY id", {}),
        ("SELECT * FROM wallets ORDER BY id", {}),
        (f"SELECT * FROM transactions WHERE NOT ({owned}) ORDER BY id", params),
    ):
        for r in conn.execute(text(sql), p):
            h.update(repr(tuple(r)).encode())
    return h.hexdigest()


def _owned_rows(conn, params):
    return conn.execute(text(f"SELECT * FROM transactions WHERE {_owned_clause()} ORDER BY created_at, id"),
                        params).mappings().all()


def _dt(value):
    """Timestamps come back as datetimes from PostgreSQL but as strings from SQLite (tests)."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _signature(rows):
    return sorted((r["reference"], _dt(r["created_at"]).replace(microsecond=0), Decimal(str(r["amount"])),
                   r["transaction_type"], r["payment_method"], Decimal(str(r["balance_after"])), r["description"])
                  for r in rows)


def _insert_params(pid, wallet_id, row):
    return {"reference": row["reference"], "passenger_id": pid, "wallet_id": wallet_id,
            "amount": float(row["amount"]), "payment_method": row["payment_method"],
            "transaction_type": row["transaction_type"], "description": row["description"],
            "balance_after": float(row["balance_after"]), "payment_source": MARKER,
            "otp_verified": False, "created_at": row["created_at"], "updated_at": row["created_at"]}


def describe(plan_by_pid, examples=3):
    for pid, rows in plan_by_pid.items():
        kinds = Counter(r["kind"] for r in rows)
        rides = [r for r in rows if r["kind"] == "ride"]
        ist = lambda r: (r["created_at"] + IST_OFFSET).strftime("%Y-%m-%d %H:%M IST")
        print(f"[plan] passenger {pid}: {len(rows)} rows ({kinds['ride']} ride payments, {kinds['topup']} demo top-ups); "
              f"{ist(rows[0])} .. {ist(rows[-1])}; ride total ₹{sum(r['amount'] for r in rides):.2f} "
              f"= top-up total ₹{sum(r['amount'] for r in rows if r['kind'] == 'topup'):.2f}; "
              f"ledger 0.00 -> {rows[-1]['balance_after']:.2f}")
        print(f"       methods {dict(Counter(r['payment_method'] for r in rows))}; "
              f"drivers {dict(Counter(r['driver_name'] for r in rides))}")
        for r in rows[:1 + examples] + rows[-1:]:
            print(f"       {r['reference']:<22} {ist(r)}  {r['transaction_type']:<12} ₹{r['amount']:>8.2f}  "
                  f"{r['payment_method']:<10} completed  balance_after ₹{r['balance_after']:.2f}  {r['description']}")


def do_seed(engine, anchor, apply):
    plans = {pid: build_plan(pid, anchor) for pid in PASSENGERS}
    with engine.connect() as probe:   # read-only planning
        ctx = {pid: _context(probe, pid) for pid in PASSENGERS}
        existing = {pid: _signature(_owned_rows(probe, ctx[pid][2])) for pid in PASSENGERS}
        probe.rollback()
    describe(plans)
    for pid, (_, wallet, _p) in ctx.items():
        print(f"[plan] passenger {pid}: wallet {wallet['id']} stays {wallet['balance']}; "
              f"owned rows already present: {len(existing[pid])}")
    if all(existing[pid] == _signature(plans[pid]) for pid in PASSENGERS):
        print("[ok] Identical demo history already present; nothing to do.")
        return
    if not apply:
        print(f"[dry-run] Would insert {sum(len(p) for p in plans.values())} rows "
              f"({', '.join(f'{pid}: {len(p)}' for pid, p in plans.items())}) and delete only previously "
              "owned rows. No changes written. Re-run with --apply --confirm-project <ref> to write.")
        return

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ctx = {pid: _context(conn, pid) for pid in PASSENGERS}
            before = _fingerprint(conn, ctx)
            for pid, (_, wallet, params) in ctx.items():
                conn.execute(text(f"DELETE FROM transactions WHERE {_owned_clause()}"), params)
                conn.execute(text(
                    "INSERT INTO transactions(reference,passenger_id,driver_id,wallet_id,amount,payment_method,status,"
                    "otp_verified,fraud_status,transaction_type,description,balance_after,payment_source,created_at,updated_at) "
                    "VALUES (:reference,:passenger_id,NULL,:wallet_id,:amount,:payment_method,'completed',"
                    ":otp_verified,'clear',:transaction_type,:description,:balance_after,:payment_source,:created_at,:updated_at)"),
                    [_insert_params(pid, wallet["id"], r) for r in plans[pid]])
                n = conn.execute(text(f"SELECT COUNT(*) FROM transactions WHERE {_owned_clause()}"), params).scalar()
                if n != N_PER_PASSENGER:
                    raise SeedError(f"Expected {N_PER_PASSENGER} demo rows for {pid}, found {n}; rolling back.")
            if _fingerprint(conn, ctx) != before:
                raise SeedError("Data this script must not touch changed; rolling back.")
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
    print(f"[ok] Committed {N_PER_PASSENGER * len(PASSENGERS)} demo transactions; wallets unchanged.")


def do_reset(engine, apply):
    with engine.connect() as conn:
        ctx = {pid: _context(conn, pid) for pid in PASSENGERS}
        counts = {pid: len(_owned_rows(conn, ctx[pid][2])) for pid in PASSENGERS}
        conn.rollback()
        print(f"[plan] would remove owned demo rows only: {counts} "
              "(payment_source='demo_seed' AND reference LIKE 'DEMO-P<id>-%' AND passenger_id=<id> "
              "AND wallet_id=<that wallet> AND driver_id IS NULL).")
        if not apply:
            print("[dry-run] No changes written.")
            return
        trans = conn.begin()
        try:
            before = _fingerprint(conn, ctx)
            for pid, (_, _, params) in ctx.items():
                conn.execute(text(f"DELETE FROM transactions WHERE {_owned_clause()}"), params)
            if _fingerprint(conn, ctx) != before:
                raise SeedError("Data this script must not touch changed; rolling back.")
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
    print(f"[ok] Removed {sum(counts.values())} demo transactions.")


def do_verify(engine, anchor):
    with engine.connect() as conn:
        for pid in PASSENGERS:
            user, wallet, params = _context(conn, pid)
            rows = _owned_rows(conn, params)
            bal, bad = Decimal("0.00"), 0
            for r in rows:
                bal += Decimal(str(r["amount"])) if r["transaction_type"] == "deposit" else -Decimal(str(r["amount"]))
                if abs(bal - Decimal(str(r["balance_after"]))) > Decimal("0.005") or bal < 0:
                    bad += 1
            matches = _signature(rows) == _signature(build_plan(pid, anchor))
            print(f"passenger {pid} ({user['name']}): wallet {wallet['balance']}; demo rows {len(rows)} "
                  f"{dict(Counter(r['transaction_type'] for r in rows))}; ledger breaks {bad}; "
                  f"ledger end {bal}; matches plan: {matches}")
        conn.rollback()


# ---------------------------------------------------------------- CLI
def _env_value(key):
    value = os.getenv(key, "")
    if not value:
        env = BACKEND_DIR / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(f"{key}="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
    return value


def _project_ref_from_supabase_url():
    m = re.search(r"https://([a-z0-9]+)\.supabase\.co", _env_value("SUPABASE_URL"))
    return m.group(1) if m else None


def engine_from_environment(confirm_ref):
    raw = _env_value("DATABASE_URL")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if not raw.startswith("postgresql"):
        raise SeedError("DATABASE_URL must be a PostgreSQL (Supabase) URL; refusing to fall back to anything else.")
    url = make_url(re.sub(r"^postgresql(\+\w+)?://", "postgresql+psycopg2://", raw))
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
    ap.add_argument("--anchor", default=DEFAULT_ANCHOR, help="'today' of the plan, YYYY-MM-DD")
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
