"""Admin-side fraud alert sync.

The fraud gate (app/services/fraud_gate.py) records every payment decision in `fraud_assessments`. Nothing wrote
`fraud_alerts`, so the admin Fraud Centre was always empty. Instead of touching any payment code, the admin endpoints
call `sync_flagged_assessments` to copy the assessments the ML model FLAGGED into `fraud_alerts` rows (status "open").

  - It only reads fraud_assessments / transactions and only inserts fraud_alerts; it never changes a payment.
  - It is idempotent: each alert's reason starts with a "[FA#<assessment id>]" tag and an assessment already tagged is
    skipped, so calling it on every page load never duplicates anything.
  - It never raises: any failure is rolled back inside a SAVEPOINT and logged, and the admin page still loads.
  - The 10-minute rule and the new-account policy are OTP triggers for everyone, not fraud flags, so they are not copied.
"""
import logging
import re

from sqlalchemy import func

from app.models import FraudAlert, FraudAssessment, Transaction

logger = logging.getLogger("tapgo.fraud_alert_sync")

TAG_PREFIX = "[FA#"
_TAG_RE = re.compile(r"^\[FA#(\d+)\]")


def assessment_id_of(alert) -> "int | None":
    """The fraud_assessments id an alert was created from, or None for an alert that was not synced."""
    match = _TAG_RE.match(alert.reason or "")
    return int(match.group(1)) if match else None


def _score_points(score) -> int:
    try:
        return max(0, min(100, int(round(float(score) * 100))))
    except (TypeError, ValueError):
        return 0


def _reason(a: FraudAssessment) -> str:
    parts = [f"{TAG_PREFIX}{a.id}] ML model flagged this {str(a.channel or '').upper()} payment"]
    if a.risk_score is not None:
        parts.append(f"(score {float(a.risk_score):.2f}" + (f", threshold {float(a.threshold):.2f})" if a.threshold is not None else ")"))
    parts.append(f"- decision: {a.decision}")
    if a.reasons:
        parts.append(f"- reasons: {a.reasons.replace(',', ', ')}")
    return " ".join(parts)


def sync_flagged_assessments(db, limit: int = 500) -> int:
    """Create an open alert for each model-flagged assessment that has none yet. Returns how many were created."""
    try:
        with db.begin_nested():
            synced = set()
            for (reason,) in db.query(FraudAlert.reason).filter(FraudAlert.reason.like(f"{TAG_PREFIX}%")).all():
                match = _TAG_RE.match(reason or "")
                if match:
                    synced.add(int(match.group(1)))
            flagged = (
                db.query(FraudAssessment)
                .filter(FraudAssessment.model_flag.is_(True))
                .order_by(FraudAssessment.id.asc())
                .all()
            )
            created = 0
            for a in flagged:
                if a.id in synced or created >= limit:
                    continue
                txn_id = None
                if a.idempotency_key and a.passenger_id:
                    txn_id = db.query(func.min(Transaction.id)).filter(
                        Transaction.passenger_id == a.passenger_id,
                        Transaction.idempotency_key == a.idempotency_key,
                    ).scalar()
                db.add(FraudAlert(
                    user_id=a.passenger_id, transaction_id=txn_id, risk_score=_score_points(a.risk_score),
                    reason=_reason(a), status="open", created_at=a.created_at,
                ))
                created += 1
        if created:
            db.commit()
        return created
    except Exception as exc:  # noqa: BLE001 - an admin page must load even if the sync cannot run
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("fraud alert sync skipped: %s", type(exc).__name__)
        return 0
