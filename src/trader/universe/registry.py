"""Asset registry lookups (D-26)."""

from __future__ import annotations

from trader.domain.universe import AssetEntry, AssetRegistry, InstrumentEntry


class Registry:
    """Read-only helper over ``configs/universe/assets.yaml``."""

    def __init__(self, data: AssetRegistry) -> None:
        """
        Index the registry.

        Args:
            data (AssetRegistry): Parsed registry.
        """
        self.data = data
        self._assets = {a.asset_id: a for a in data.assets}
        self._instruments = {i.instrument_id: i for i in data.instruments}
        self._mappings = {(m.instrument_id, m.venue_id) for m in data.market_symbol_map}

    def instrument(self, instrument_id: str) -> InstrumentEntry | None:
        """
        Look up an instrument.

        Args:
            instrument_id (str): Canonical ID.

        Returns:
            InstrumentEntry | None: Entry or None.
        """
        return self._instruments.get(instrument_id)

    def asset(self, asset_id: str) -> AssetEntry | None:
        """
        Look up an asset.

        Args:
            asset_id (str): Asset ID.

        Returns:
            AssetEntry | None: Entry or None.
        """
        return self._assets.get(asset_id)

    def tier_of(self, instrument_id: str) -> str | None:
        """
        Return the tier of an instrument's base asset.

        Args:
            instrument_id (str): Instrument.

        Returns:
            str | None: Tier, or None if unknown.
        """
        inst = self.instrument(instrument_id)
        asset = self.asset(inst.base) if inst else None
        return asset.tier if asset else None

    def has_mapping(self, instrument_id: str, venue_id: str) -> bool:
        """
        Check the support criterion (instrument mapped for the venue).

        Args:
            instrument_id (str): Instrument.
            venue_id (str): Venue.

        Returns:
            bool: True if mapped.
        """
        return (instrument_id, venue_id) in self._mappings
