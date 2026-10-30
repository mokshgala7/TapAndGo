# Next steps

Most important first. None of these needs GPS or location data.

1. **R1 trade-off: DECIDED (2026-10-26, D1 in `DECISIONS.md`): option (a) accepted. V6 is the reference candidate.**
   Kept for the record: R1 says a fare jump must stay
   visible even with a familiar driver, and also that high fares must not automatically be fraud. Without trip
   context, V6 resolves this by challenging about 23% of legitimate long/airport trips, which costs OTP friction,
   not rejections. Options:
   - **(a)** accept V6's behaviour, since OTP is cheap for genuine passengers
   - **(b)** keep V6's model, but surface `passenger_fare_anomaly` to the backend as information only, and raise the
     model threshold to cut friction. This needs a new validation-only threshold study; recall falls
   - **(c)** if Tap & Go **already** captures a fare category at booking (e.g. "outstation/airport" chosen by the
     passenger), evaluate it as an approved input. **Do not collect new location data for this.**
2. **10-minute rule policy.** As specified it adds 175 legitimate challenges per extra fraud on T3 (5,766 extra on
   238,790 rides). Decide in the backend whether it should trigger OTP on its own or only inform.
3. **Shadow-mode evaluation**, a separate backend project (prerequisites in `integration/INTEGRATION_CONTRACT.md`
   §5): call the scorer, log results, change nothing in the payment flow; review flagged rides and disputes;
   measure real precision and false-alarm cost; re-select the threshold on real outcomes.
4. **Real labels before any further synthetic optimisation.** Every number here comes from generators whose
   assumptions drive the results; V4/V5's advantage came partly from generator driver structure.
5. **Optional research, ML-only:**
   - sequence features for gradual compromise (19.5% recall)
   - calibration study for the risk score
   - fairness check of night-time FPR by archetype on real data
