import os
import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine, Base
from app.routes import admin, auth, wallet, payment, card_order, support, nfc_security, nfc_pay, qr as qr_routes

logger = logging.getLogger("tapgo")


def _exec_safe(eng, stmt: str, desc: str = "") -> bool:
    """Execute a single DDL or DML statement in an isolated transaction.

    If PostgreSQL or SQLite fails on this statement, only this statement's
    transaction is rolled back, preventing InFailedSqlTransaction from aborting
    subsequent migration steps.
    """
    try:
        with eng.begin() as conn:
            conn.execute(text(stmt))
        return True
    except Exception as ex:
        logger.warning(f"[Migration] {desc or stmt[:50]}: {ex}")
        return False


def ensure_unique_provider_transaction_index(eng) -> str:
    """Make transactions.provider_transaction_id unique on databases created before
    this was enforced (fresh databases get it from models.py).

    Safe by construction: it never deletes or edits rows. If duplicate non-null
    values already exist it logs them and SKIPS creating the index (the code
    path in payment.py is still protected by the payment_orders claim), so a
    human can review the duplicates first. See backend/migrations/.
    Returns one of: created, exists, skipped_duplicates, no_table, failed.
    """
    try:
        insp = inspect(eng)
        if "transactions" not in insp.get_table_names():
            return "no_table"
        for idx in insp.get_indexes("transactions"):
            if idx.get("unique") and idx.get("column_names") == ["provider_transaction_id"]:
                return "exists"
        for uc in insp.get_unique_constraints("transactions"):
            if uc.get("column_names") == ["provider_transaction_id"]:
                return "exists"
        with eng.connect() as conn:
            dups = conn.execute(text(
                "SELECT provider_transaction_id, COUNT(*) AS n FROM transactions "
                "WHERE provider_transaction_id IS NOT NULL "
                "GROUP BY provider_transaction_id HAVING COUNT(*) > 1"
            )).fetchall()
        if dups:
            logger.error(
                "[Migration] %d duplicated provider_transaction_id value(s) found; the unique index was NOT "
                "created. Review them (backend/migrations/2026_10_stage1_security.sql) and re-run.", len(dups)
            )
            return "skipped_duplicates"
        ok = _exec_safe(
            eng,
            "CREATE UNIQUE INDEX ux_transactions_provider_transaction_id ON transactions (provider_transaction_id)",
            "unique transactions.provider_transaction_id",
        )
        return "created" if ok else "failed"
    except Exception as e:
        logger.error(f"[Migration] ensure_unique_provider_transaction_index failed: {e}")
        return "failed"


def run_database_migrations(eng):
    """
    Safely ensures all required tables and columns exist across
    PostgreSQL (Supabase), MySQL, and SQLite.
    Operates additively and never drops data or fails the process.
    Each DDL/DML statement executes in its own isolated transaction.
    """
    try:
        inspector = inspect(eng)
        dialect = eng.dialect.name
        table_names = set(inspector.get_table_names())

        # 1. EMAIL OTPS TABLE & COLUMNS
        if "email_otps" in table_names:
            otp_cols = {col["name"] for col in inspector.get_columns("email_otps")}

            # Step 1A: Ensure all columns exist before running any backfill updates
            if dialect == "postgresql":
                # PostgreSQL 9.6+ supports ADD COLUMN IF NOT EXISTS natively
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS reason VARCHAR(32) DEFAULT 'create_account'", "add email_otps.reason")
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS purpose VARCHAR(32) DEFAULT 'create_account'", "add email_otps.purpose")
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0", "add email_otps.attempts")
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE", "add email_otps.is_verified")
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS used BOOLEAN NOT NULL DEFAULT FALSE", "add email_otps.used")
                _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN IF NOT EXISTS otp_metadata TEXT NULL", "add email_otps.otp_metadata")
            elif dialect == "mysql":
                if "reason" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN reason VARCHAR(32) DEFAULT 'create_account'", "add email_otps.reason")
                if "purpose" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN purpose VARCHAR(32) DEFAULT 'create_account'", "add email_otps.purpose")
                if "attempts" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN attempts INT NOT NULL DEFAULT 0", "add email_otps.attempts")
                if "is_verified" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN is_verified TINYINT(1) NOT NULL DEFAULT 0", "add email_otps.is_verified")
                if "used" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN used TINYINT(1) NOT NULL DEFAULT 0", "add email_otps.used")
                if "otp_metadata" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN otp_metadata TEXT NULL", "add email_otps.otp_metadata")
            else:  # sqlite
                if "reason" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN reason VARCHAR(32) DEFAULT 'create_account'", "add email_otps.reason")
                if "purpose" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN purpose VARCHAR(32) DEFAULT 'create_account'", "add email_otps.purpose")
                if "attempts" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0", "add email_otps.attempts")
                if "is_verified" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT 0", "add email_otps.is_verified")
                if "used" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN used BOOLEAN NOT NULL DEFAULT 0", "add email_otps.used")
                if "otp_metadata" not in otp_cols:
                    _exec_safe(eng, "ALTER TABLE email_otps ADD COLUMN otp_metadata TEXT NULL", "add email_otps.otp_metadata")

            # Step 1B: Safely backfill reason & purpose now that both columns are guaranteed to exist
            _exec_safe(eng, """
                UPDATE email_otps 
                SET reason = CASE 
                    WHEN purpose = 'registration' THEN 'create_account' 
                    WHEN purpose = 'withdrawal' THEN 'withdraw_balance' 
                    WHEN purpose IS NOT NULL AND purpose != '' THEN purpose 
                    ELSE 'create_account' 
                END
                WHERE reason IS NULL OR reason = ''
            """, "backfill email_otps.reason")

            _exec_safe(eng, """
                UPDATE email_otps 
                SET purpose = reason 
                WHERE purpose IS NULL OR purpose = ''
            """, "synchronize email_otps.purpose")

            # Step 1C: Ensure indexes exist idempotently
            if dialect == "postgresql":
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_reason ON email_otps(reason)", "idx email_otps.reason")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_used ON email_otps(used)", "idx email_otps.used")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_email ON email_otps(email)", "idx email_otps.email")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_purpose ON email_otps(purpose)", "idx email_otps.purpose")
            elif dialect == "sqlite":
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_reason ON email_otps(reason)", "ix email_otps.reason")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_used ON email_otps(used)", "ix email_otps.used")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_email ON email_otps(email)", "ix email_otps.email")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_purpose ON email_otps(purpose)", "ix email_otps.purpose")
            elif dialect == "mysql":
                # MySQL does not support IF NOT EXISTS on index creation directly, check existing
                existing_indices = {idx["name"] for idx in inspector.get_indexes("email_otps")}
                for idx_name, col_name in [("idx_reason", "reason"), ("idx_purpose", "purpose"), ("idx_used", "used")]:
                    if idx_name not in existing_indices:
                        _exec_safe(eng, f"CREATE INDEX {idx_name} ON email_otps({col_name})", f"mysql idx {col_name}")
        else:
            if dialect == "postgresql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_otps (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(120) NOT NULL,
                        otp VARCHAR(10) NOT NULL,
                        reason VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        purpose VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                        used BOOLEAN NOT NULL DEFAULT FALSE,
                        otp_metadata TEXT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                    )
                """, "create email_otps postgresql")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_email ON email_otps(email)", "idx email_otps email")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_reason ON email_otps(reason)", "idx email_otps reason")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_purpose ON email_otps(purpose)", "idx email_otps purpose")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_otps_used ON email_otps(used)", "idx email_otps used")
            elif dialect == "mysql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_otps (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        email VARCHAR(120) NOT NULL,
                        otp VARCHAR(10) NOT NULL,
                        reason VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        purpose VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        attempts INT NOT NULL DEFAULT 0,
                        is_verified TINYINT(1) NOT NULL DEFAULT 0,
                        used TINYINT(1) NOT NULL DEFAULT 0,
                        otp_metadata TEXT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NOT NULL,
                        KEY idx_email (email),
                        KEY idx_reason (reason),
                        KEY idx_purpose (purpose),
                        KEY idx_used (used)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """, "create email_otps mysql")
            else:  # sqlite
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_otps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email VARCHAR(120) NOT NULL,
                        otp VARCHAR(10) NOT NULL,
                        reason VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        purpose VARCHAR(32) NOT NULL DEFAULT 'create_account',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        is_verified BOOLEAN NOT NULL DEFAULT 0,
                        used BOOLEAN NOT NULL DEFAULT 0,
                        otp_metadata TEXT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NOT NULL
                    )
                """, "create email_otps sqlite")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_email ON email_otps(email)", "ix email_otps email")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_reason ON email_otps(reason)", "ix email_otps reason")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_purpose ON email_otps(purpose)", "ix email_otps purpose")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_otps_used ON email_otps(used)", "ix email_otps used")
            logger.info("[Migration] Created table email_otps")

        # 2. EMAIL LOGS TABLE
        table_names = set(inspect(eng).get_table_names())
        if "email_logs" not in table_names:
            if dialect == "postgresql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_logs (
                        id SERIAL PRIMARY KEY,
                        email_type VARCHAR(50) NOT NULL,
                        recipient VARCHAR(120) NOT NULL,
                        reference VARCHAR(64) NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'SENT',
                        error_message TEXT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create email_logs postgresql")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_logs_recipient ON email_logs(recipient)", "idx email_logs recipient")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_email_logs_created_at ON email_logs(created_at)", "idx email_logs created_at")
            elif dialect == "mysql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        email_type VARCHAR(50) NOT NULL,
                        recipient VARCHAR(120) NOT NULL,
                        reference VARCHAR(64) NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'SENT',
                        error_message TEXT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        KEY idx_recipient (recipient),
                        KEY idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """, "create email_logs mysql")
            else:  # sqlite
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS email_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email_type VARCHAR(50) NOT NULL,
                        recipient VARCHAR(120) NOT NULL,
                        reference VARCHAR(64) NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'SENT',
                        error_message TEXT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create email_logs sqlite")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_logs_recipient ON email_logs(recipient)", "ix email_logs recipient")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_email_logs_created_at ON email_logs(created_at)", "ix email_logs created_at")
            logger.info("[Migration] Created table email_logs")

        # 3. USERS TABLE LEGACY COLUMNS
        if "users" in table_names:
            user_cols = {col["name"] for col in inspector.get_columns("users")}
            user_migrations = [
                ("status", "VARCHAR(20) NOT NULL DEFAULT 'active'"),
                ("qr_identifier", "VARCHAR(128) NULL"),
                ("nfc_identifier", "VARCHAR(128) NULL"),
                ("signature_document", "VARCHAR(255) NULL"),
                ("id_document", "VARCHAR(255) NULL"),
                ("state", "VARCHAR(100) NULL"),
                ("emergency_contact_name", "VARCHAR(100) NULL"),
                ("emergency_contact_phone", "VARCHAR(20) NULL"),
                ("bank_account_holder", "VARCHAR(100) NULL"),
                ("bank_account_number", "VARCHAR(50) NULL"),
                ("bank_ifsc", "VARCHAR(20) NULL"),
                ("bank_upi_id", "VARCHAR(50) NULL"),
                ("bank_locked", "INT DEFAULT 0" if dialect == "mysql" else "INTEGER DEFAULT 0"),
                ("bank_request_status", "VARCHAR(20) DEFAULT 'none'"),
                ("doc_request_status", "VARCHAR(20) DEFAULT 'none'"),
                ("phone_request_status", "VARCHAR(20) DEFAULT 'none'"),
            ]
            for col_name, col_def in user_migrations:
                if dialect == "postgresql":
                    _exec_safe(eng, f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_def}", f"users.{col_name}")
                elif col_name not in user_cols:
                    _exec_safe(eng, f"ALTER TABLE users ADD COLUMN {col_name} {col_def}", f"users.{col_name}")

        # 4. TRANSACTIONS TABLE LEGACY COLUMNS
        if "transactions" in table_names:
            txn_cols = {col["name"] for col in inspector.get_columns("transactions")}
            txn_migrations = [
                ("transaction_type", "VARCHAR(30) NULL"),
                ("description", "TEXT NULL"),
                ("balance_after", "DECIMAL(12, 2) NULL"),
                ("idempotency_key", "VARCHAR(128) NULL"),
                ("related_transaction_id", "INT NULL" if dialect == "mysql" else "INTEGER NULL"),
                ("provider", "VARCHAR(30) NULL"),
                ("provider_transaction_id", "VARCHAR(128) NULL"),
                ("utr", "VARCHAR(128) NULL"),
                ("payer_name", "VARCHAR(120) NULL"),
                ("payment_request_id", "INT NULL" if dialect == "mysql" else "INTEGER NULL"),
                ("payment_source", "VARCHAR(50) NULL"),
                ("email_received_at", "DATETIME NULL" if dialect != "postgresql" else "TIMESTAMP WITHOUT TIME ZONE NULL"),
                ("raw_email_id", "VARCHAR(255) NULL"),
                ("failure_code", "VARCHAR(40) NULL"),
            ]
            for col_name, col_def in txn_migrations:
                if dialect == "postgresql":
                    _exec_safe(eng, f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {col_name} {col_def}", f"transactions.{col_name}")
                elif col_name not in txn_cols:
                    _exec_safe(eng, f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}", f"transactions.{col_name}")

        # 5. CREATE ALL REMAINING TABLES FROM MODELS.PY
        try:
            Base.metadata.create_all(bind=eng)
        except Exception as create_ex:
            logger.warning(f"[Warning] Base.metadata.create_all: {create_ex}")

        # 5b. fraud_assessments.enforced_by_allowlist (create_all never adds a column to an existing table;
        #     only matters if an earlier version of the table was already created).
        try:
            insp = inspect(eng)
            if "fraud_assessments" in set(insp.get_table_names()):
                if "enforced_by_allowlist" not in {c["name"] for c in insp.get_columns("fraud_assessments")}:
                    _exec_safe(eng, "ALTER TABLE fraud_assessments ADD COLUMN enforced_by_allowlist BOOLEAN NOT NULL DEFAULT FALSE",
                               "fraud_assessments.enforced_by_allowlist")
        except Exception as fa_ex:
            logger.warning(f"[Warning] fraud_assessments column check: {fa_ex}")

        # 5b. UNIQUE provider_transaction_id (guarded; never deletes data)
        ensure_unique_provider_transaction_index(eng)

        # 6. ENSURE DEFAULT ADMIN EXISTS
        try:
            from app.database import SessionLocal
            from app.routes.admin import ensure_default_admin
            with SessionLocal() as db:
                ensure_default_admin(db)
        except Exception as admin_ex:
            logger.warning(f"[Warning] ensure_default_admin: {admin_ex}")

        # 7. SUPPORT TICKETS TABLE
        table_names = set(inspect(eng).get_table_names())
        if "support_tickets" not in table_names:
            if dialect == "postgresql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        name VARCHAR(100) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        phone VARCHAR(20) NOT NULL,
                        category VARCHAR(50) NOT NULL DEFAULT 'other',
                        priority VARCHAR(20) NOT NULL DEFAULT 'medium',
                        subject VARCHAR(255) NOT NULL,
                        message TEXT NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'open',
                        admin_reply TEXT NULL,
                        replied_by INTEGER NULL REFERENCES admins(id),
                        replied_at TIMESTAMP WITHOUT TIME ZONE NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create support_tickets postgresql")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_support_tickets_user_id ON support_tickets(user_id)", "idx support_tickets user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status)", "idx support_tickets status")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at ON support_tickets(created_at)", "idx support_tickets created_at")
            elif dialect == "mysql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        phone VARCHAR(20) NOT NULL,
                        category VARCHAR(50) NOT NULL DEFAULT 'other',
                        priority VARCHAR(20) NOT NULL DEFAULT 'medium',
                        subject VARCHAR(255) NOT NULL,
                        message TEXT NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'open',
                        admin_reply TEXT NULL,
                        replied_by INT NULL,
                        replied_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        KEY idx_user_id (user_id),
                        KEY idx_status (status),
                        KEY idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """, "create support_tickets mysql")
            else:
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        phone VARCHAR(20) NOT NULL,
                        category VARCHAR(50) NOT NULL DEFAULT 'other',
                        priority VARCHAR(20) NOT NULL DEFAULT 'medium',
                        subject VARCHAR(255) NOT NULL,
                        message TEXT NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'open',
                        admin_reply TEXT NULL,
                        replied_by INTEGER NULL,
                        replied_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create support_tickets sqlite")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON support_tickets(user_id)", "ix support_tickets user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_support_tickets_status ON support_tickets(status)", "ix support_tickets status")
            logger.info("[Migration] Created table support_tickets")

        # 8. NFC CARDS TABLE
        table_names = set(inspect(eng).get_table_names())
        if "nfc_cards" not in table_names:
            if dialect == "postgresql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS nfc_cards (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        card_reference VARCHAR(64) NOT NULL UNIQUE,
                        card_type VARCHAR(50) NOT NULL DEFAULT 'standard_nfc',
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        blocked_reason TEXT NULL,
                        block_requested_at TIMESTAMP WITHOUT TIME ZONE NULL,
                        nfc_order_id INTEGER NULL REFERENCES nfc_card_orders(id),
                        replacement_order_id INTEGER NULL REFERENCES nfc_card_orders(id),
                        issued_at TIMESTAMP WITHOUT TIME ZONE NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create nfc_cards postgresql")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_nfc_cards_user_id ON nfc_cards(user_id)", "idx nfc_cards user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_nfc_cards_status ON nfc_cards(status)", "idx nfc_cards status")
                _exec_safe(eng, "CREATE UNIQUE INDEX IF NOT EXISTS idx_nfc_cards_ref ON nfc_cards(card_reference)", "idx nfc_cards ref")
            elif dialect == "mysql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS nfc_cards (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        card_reference VARCHAR(64) NOT NULL UNIQUE,
                        card_type VARCHAR(50) NOT NULL DEFAULT 'standard_nfc',
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        blocked_reason TEXT NULL,
                        block_requested_at DATETIME NULL,
                        nfc_order_id INT NULL,
                        replacement_order_id INT NULL,
                        issued_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        KEY idx_user_id (user_id),
                        KEY idx_status (status)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """, "create nfc_cards mysql")
            else:
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS nfc_cards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        card_reference VARCHAR(64) NOT NULL UNIQUE,
                        card_type VARCHAR(50) NOT NULL DEFAULT 'standard_nfc',
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        blocked_reason TEXT NULL,
                        block_requested_at DATETIME NULL,
                        nfc_order_id INTEGER NULL,
                        replacement_order_id INTEGER NULL,
                        issued_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create nfc_cards sqlite")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_nfc_cards_user_id ON nfc_cards(user_id)", "ix nfc_cards user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_nfc_cards_status ON nfc_cards(status)", "ix nfc_cards status")
            logger.info("[Migration] Created table nfc_cards")

        # 8b. NFC CARD CHIP UID (create_all never adds columns to an existing table).
        # Production is Postgres; the SQLite branch only keeps the test database in step.
        if "nfc_cards" in set(inspect(eng).get_table_names()):
            if dialect == "postgresql":
                _exec_safe(eng, "ALTER TABLE nfc_cards ADD COLUMN IF NOT EXISTS card_uid VARCHAR(32) NULL", "nfc_cards.card_uid")
            elif "card_uid" not in {col["name"] for col in inspect(eng).get_columns("nfc_cards")}:
                _exec_safe(eng, "ALTER TABLE nfc_cards ADD COLUMN card_uid VARCHAR(32) NULL", "nfc_cards.card_uid")
            # NULLs are allowed many times in a unique index on all three dialects.
            has_unique_uid = any(
                idx.get("unique") and idx.get("column_names") == ["card_uid"]
                for idx in inspect(eng).get_indexes("nfc_cards")
            ) or any(
                uc.get("column_names") == ["card_uid"]
                for uc in inspect(eng).get_unique_constraints("nfc_cards")
            )
            if not has_unique_uid:
                _exec_safe(eng, "CREATE UNIQUE INDEX IF NOT EXISTS idx_nfc_cards_card_uid ON nfc_cards(card_uid)", "idx nfc_cards.card_uid")

        # 9. WITHDRAWAL REQUESTS TABLE
        table_names = set(inspect(eng).get_table_names())
        if "withdrawal_requests" not in table_names:
            if dialect == "postgresql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS withdrawal_requests (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        wallet_id INTEGER NOT NULL REFERENCES wallets(id),
                        hold_transaction_id INTEGER NULL REFERENCES transactions(id),
                        amount NUMERIC(12,2) NOT NULL,
                        destination_desc TEXT NOT NULL,
                        reference VARCHAR(64) NOT NULL UNIQUE,
                        otp_verified BOOLEAN NOT NULL DEFAULT TRUE,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        admin_id INTEGER NULL REFERENCES admins(id),
                        admin_note TEXT NULL,
                        reviewed_at TIMESTAMP WITHOUT TIME ZONE NULL,
                        paid_at TIMESTAMP WITHOUT TIME ZONE NULL,
                        idempotency_key VARCHAR(128) NULL UNIQUE,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create withdrawal_requests postgresql")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_wr_user_id ON withdrawal_requests(user_id)", "idx wr user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_wr_status ON withdrawal_requests(status)", "idx wr status")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS idx_wr_reference ON withdrawal_requests(reference)", "idx wr ref")
            elif dialect == "mysql":
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS withdrawal_requests (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        wallet_id INT NOT NULL,
                        hold_transaction_id INT NULL,
                        amount DECIMAL(12,2) NOT NULL,
                        destination_desc TEXT NOT NULL,
                        reference VARCHAR(64) NOT NULL UNIQUE,
                        otp_verified TINYINT(1) NOT NULL DEFAULT 1,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        admin_id INT NULL,
                        admin_note TEXT NULL,
                        reviewed_at DATETIME NULL,
                        paid_at DATETIME NULL,
                        idempotency_key VARCHAR(128) NULL UNIQUE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        KEY idx_user_id (user_id),
                        KEY idx_status (status)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """, "create withdrawal_requests mysql")
            else:
                _exec_safe(eng, """
                    CREATE TABLE IF NOT EXISTS withdrawal_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        wallet_id INTEGER NOT NULL,
                        hold_transaction_id INTEGER NULL,
                        amount NUMERIC(12,2) NOT NULL,
                        destination_desc TEXT NOT NULL,
                        reference VARCHAR(64) NOT NULL UNIQUE,
                        otp_verified BOOLEAN NOT NULL DEFAULT 1,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        admin_id INTEGER NULL,
                        admin_note TEXT NULL,
                        reviewed_at DATETIME NULL,
                        paid_at DATETIME NULL,
                        idempotency_key VARCHAR(128) NULL UNIQUE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """, "create withdrawal_requests sqlite")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_wr_user_id ON withdrawal_requests(user_id)", "ix wr user_id")
                _exec_safe(eng, "CREATE INDEX IF NOT EXISTS ix_wr_status ON withdrawal_requests(status)", "ix wr status")
            logger.info("[Migration] Created table withdrawal_requests")

        # 6. SUPPORT TICKETS COLUMNS
        if "support_tickets" in table_names:
            st_cols = {col["name"] for col in inspector.get_columns("support_tickets")}
            if "admin_reply" not in st_cols:
                _exec_safe(eng, "ALTER TABLE support_tickets ADD COLUMN admin_reply TEXT NULL", "add support_tickets.admin_reply")
            if "replied_by" not in st_cols:
                _exec_safe(eng, "ALTER TABLE support_tickets ADD COLUMN replied_by INT NULL", "add support_tickets.replied_by")
            if "replied_at" not in st_cols:
                _exec_safe(eng, "ALTER TABLE support_tickets ADD COLUMN replied_at DATETIME NULL" if dialect != "postgresql" else "ALTER TABLE support_tickets ADD COLUMN replied_at TIMESTAMP WITHOUT TIME ZONE NULL", "add support_tickets.replied_at")
            if "admin_response" in st_cols:
                _exec_safe(eng, "UPDATE support_tickets SET admin_reply = admin_response WHERE admin_reply IS NULL AND admin_response IS NOT NULL", "backfill support_tickets.admin_reply")


    except Exception as e:
        logger.error(f"[Database Migration Critical] Startup migration error: {e}")


# Refuse to start on an invalid TAPGO_FRAUD_MODE, or on enforce without a real PAYMENT_OTP_SECRET.
from app.services.fraud_gate import validate_fraud_config  # noqa: E402
validate_fraud_config()

# Load the ML model in the background so the first payment after a restart is not the one that pays for it.
from app.services.fraud_risk_shadow import start_warm_up  # noqa: E402
start_warm_up()

# Execute migration at startup
run_database_migrations(engine)

app = FastAPI(title="Tap&Go API", version="1.0.0")


# Configure CORS Middleware
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins else ["*"],
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handler for safe debugging & clean JSON responses
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[Unhandled Exception] {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}
    )

# Ensure upload directories exist and mount static route
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(
    BASE_DIR,
    "reviewer_seed/uploads" if settings.REVIEW_DEMO_MODE else "uploads",
)
for folder in ["profile", "rc", "licence", "insurance", "signatures", "id_documents"]:
    os.makedirs(os.path.join(UPLOADS_DIR, folder), exist_ok=True)

if settings.REVIEW_DEMO_MODE:
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


# Include Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(wallet.router)
app.include_router(payment.router)
app.include_router(payment.debug_router)
app.include_router(card_order.router)
app.include_router(card_order.admin_router)
app.include_router(support.router)
app.include_router(support.admin_router)
app.include_router(nfc_security.router)
app.include_router(nfc_pay.router)
app.include_router(qr_routes.router)

@app.get("/")
def root():
    """Root endpoint for status check."""
    return {"message": "Tap&Go Backend Running", "demo_mode": settings.DEMO_MODE}
