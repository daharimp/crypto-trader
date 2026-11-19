# 2026-11-15: Confidence replay (owner: 5-15% by confidence, trade more at 85%+)

Follows `tasks/2026-11-15-trend-stack-replay.md`, where confidence measured at the open never
rose above 50%.

- [x] Confidence measured every 4h while a trade runs; rules committed before results (`024c98e`)
- [x] Run, results and calibration recorded: highest confidence 66%, not calibrated (60-70%
      moments made money 41% of the time over 3 days); the 85% add never fired
- [ ] Owner: choose the degen paper account's settings (candidate: 5% collateral, buffer 3,
      30% stop, stop for the rest of a 15% loss day); needs owner-approved values (UD) and
      coordination with the main session, which owns the perps config, simulator and UI

Test inputs only; none is an approved risk value.
