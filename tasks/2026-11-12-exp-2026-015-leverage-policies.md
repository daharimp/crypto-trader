# 2026-11-12: EXP-2026-015 how should opening leverage be chosen? (owner question; ADR-034)

- [x] Plan committed before results (`research/EXP-2026-015-plan.md`)
- [x] Result (`research/EXP-2026-015-results.txt`): volatility-assessed leverage is not shown to beat or lose to fixed 12x (fewer dollars, smaller drops, fewer liquidations); raising leverage on signal strength is not shown to add money
- [x] Finding: at the paper session's 0.01%/h borrow no leverage policy is shown to make money; the borrow fee at 8x to 12x is about $1,400 to $2,600 a year on $2,500
- [ ] Owner: decide whether the paper session's holding cost should stay at the cautious 0.01%/h (UD-23) given measured funding
- [ ] Owner: decide whether to add the two-sided 1-month trend rule as a second paper session
- [ ] If wanted: a separate pre-registered test of trend strength with a signal that can be strong at entry (it could not be tested here)
