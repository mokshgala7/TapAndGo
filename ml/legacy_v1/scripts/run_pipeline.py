"""
run_pipeline.py  --  End-to-end TapGo-ML pipeline runner.

Steps:
  1. Training          (src.train)
  2. Hyperpar. Tuning  (src.tune)       [optional, --tune]
  3. Validation        (src.validate)   <- selects optimal thresholds
  4. Test Evaluation   (src.evaluate)   <- unbiased final metrics
  5. Visual Reports    (src.report)

Usage
-----
    python scripts/run_pipeline.py              # full pipeline (no tuning)
    python scripts/run_pipeline.py --tune       # include hyperparameter tuning
    python scripts/run_pipeline.py --skip-train # skip training, run rest
    python scripts/run_pipeline.py --report-only  # only regenerate plots
"""

import sys
import argparse
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.train    import train_all
from src.validate import validate_all
from src.evaluate import evaluate_all
from src.report   import generate_all_reports


def banner(step, title):
    print("\n" + "=" * 60)
    print(f"  {step}  --  {title}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="TapGo-ML full pipeline")
    parser.add_argument("--skip-train",  action="store_true")
    parser.add_argument("--tune",        action="store_true",
                        help="Run RandomizedSearchCV tuning after initial training")
    parser.add_argument("--report-only", action="store_true",
                        help="Only regenerate visual reports")
    args = parser.parse_args()

    t_start = time.time()

    if args.report_only:
        banner("REPORT", "VISUAL REPORTS ONLY")
        generate_all_reports()
        print(f"\n>> Done in {time.time() - t_start:.1f}s")
        return

    if not args.skip_train:
        banner("STEP 1 / 4", "TRAINING")
        train_all()

    if args.tune:
        banner("STEP 1b", "HYPERPARAMETER TUNING (RF + XGBoost)")
        from src.tune import run_tuning
        run_tuning("all")

    banner("STEP 2 / 4", "VALIDATION  (threshold selection)")
    validate_all()

    banner("STEP 3 / 4", "TEST EVALUATION")
    evaluate_all()

    banner("STEP 4 / 4", "VISUAL REPORTS")
    generate_all_reports()

    print(f"\n>> Pipeline complete in {time.time() - t_start:.1f}s")
    print("   Models  -> models/")
    print("   Reports -> reports/")


if __name__ == "__main__":
    main()
