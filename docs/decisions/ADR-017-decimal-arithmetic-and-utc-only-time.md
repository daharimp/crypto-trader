# ADR-017: Decimal arithmetic and UTC-only time

- **Status:** Proposed (R-04, R-07)
- **Decision:** Money and quantities use `Decimal` with documented rounding (quantities round down to the instrument step; USD amounts quantized to cents for reporting only). All timestamps are timezone-aware UTC; candles are labelled by open time and become available at close time.

Source: `docs/spec/architecture.md` §14.
