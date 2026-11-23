### Added
- The hourly status push also writes `server-info.txt` (deployed commit, deploy hold,
  container states, `tailscale serve status`, last log lines per paper service) so scheduled
  reviews can confirm a deploy took effect and the dashboard is reachable (ADR-047).
