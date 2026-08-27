# Process Improvements

## 1. Market Reconciliation Decimal Noise

**Issue →** Yahoo and Nasdaq closing prices showed extremely small differences.

**Root cause →** The providers stored the same prices at slightly different decimal precision.

**Fix →** Treat differences within 0.50% as matches.

**Prevention →** Keep the tolerance visible and monitor only differences above it.

## 2. Controlled Reconciliation Failure

**Issue →** A test changed the Nasdaq close from 100 to 110, creating a 10% difference.

**Root cause →** The discrepancy was deliberately injected to test the failure path.

**Fix →** The reconciliation rule marked the record as `BREAK` and created one MEDIUM Consistency issue.

**Prevention →** Run the isolated automated test without writing test records to the production database.

## 3. AMZN Net-Income Anomaly

**Issue →** The quality engine flagged AMZN net income changing 1,217.7% from 2022 to 2023, above its 70.5% IQR threshold.

**Root cause →** Stored net income moved from a $2.722B loss to a $30.425B profit, making the percentage change unusually large.

**Fix →** Treat it as an investigation flag and review the linked SEC filing metadata before calling it an error.

**Prevention →** Preserve source tags and filing dates so future anomalies can be checked against the original filing.
