"""Resolve Databento DBN records to MNQ / MES / MGC roots using store metadata — no silent guesses."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from databento import DBNStore

from app.services.instruments import PRIMARY_RESEARCH_SYMBOLS

CONTINUOUS_RE = re.compile(r"^(MNQ|MES|MGC)\.c\.\d+", re.I)
ROOT_ONLY_RE = re.compile(r"^(MNQ|MES|MGC)$", re.I)


@dataclass
class SymbologyResolver:
    """Maps instrument_id / raw_symbol / continuous symbols to research roots."""

    id_to_root: dict[str, str] = field(default_factory=dict)
    raw_to_root: dict[str, str] = field(default_factory=dict)
    file_symbols: list[str] = field(default_factory=list)
    unmapped_samples: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_store(cls, store: DBNStore) -> SymbologyResolver:
        resolver = cls()
        resolver.file_symbols = [str(s) for s in (store.symbols or [])]
        for sym in resolver.file_symbols:
            root = cls._root_from_label(sym)
            if root:
                resolver.raw_to_root[sym.upper()] = root

        symbology = getattr(store, "symbology", None)
        if symbology:
            try:
                if isinstance(symbology, dict):
                    resolver.diagnostics["symbology_keys"] = list(symbology.keys())[:20]
                    for key, val in symbology.items():
                        if isinstance(val, dict):
                            for inst_id, raw in val.items():
                                root = cls._root_from_label(str(raw))
                                if root:
                                    resolver.id_to_root[str(inst_id)] = root
                                    resolver.raw_to_root[str(raw).upper()] = root
            except Exception as exc:
                resolver.diagnostics["symbology_parse_error"] = str(exc)

        mappings = getattr(store, "mappings", None)
        if mappings:
            try:
                items = mappings if isinstance(mappings, list) else []
                resolver.diagnostics["mapping_count"] = len(items)
            except Exception:
                pass

        return resolver

    @staticmethod
    def _root_from_label(label: str) -> str | None:
        if not label:
            return None
        up = str(label).strip().upper()
        m = CONTINUOUS_RE.match(up)
        if m:
            return m.group(1).upper()
        m = ROOT_ONLY_RE.match(up)
        if m:
            return m.group(1).upper()
        for root in PRIMARY_RESEARCH_SYMBOLS:
            if up.startswith(f"{root}.") or (up.startswith(root) and len(up) > len(root) and not up[len(root)].isalpha()):
                return root
        return None

    def resolve_row(self, row, symbol_col: str | None, instrument_col: str | None) -> str | None:
        candidates: list[str] = []
        if symbol_col and symbol_col in row.index:
            candidates.append(str(row[symbol_col]))
        if instrument_col and instrument_col in row.index:
            iid = str(row[instrument_col])
            if iid in self.id_to_root:
                return self.id_to_root[iid]
            candidates.append(iid)
        for c in candidates:
            up = c.upper()
            if up in self.raw_to_root:
                return self.raw_to_root[up]
            root = self._root_from_label(c)
            if root:
                return root
        if len(self.file_symbols) == 1:
            only = self._root_from_label(self.file_symbols[0])
            if only and only in PRIMARY_RESEARCH_SYMBOLS:
                return only
        if candidates:
            sample = candidates[0]
            if sample not in self.unmapped_samples and len(self.unmapped_samples) < 20:
                self.unmapped_samples.append(sample)
        return None

    def assert_ready(self) -> None:
        if not self.id_to_root and not self.raw_to_root and not self.file_symbols:
            raise ValueError(
                "DBN file has no symbology metadata. Cannot map instrument IDs to MNQ/MES/MGC safely."
            )
        roots = set(self.id_to_root.values()) | set(self.raw_to_root.values())
        unknown_roots = roots - set(PRIMARY_RESEARCH_SYMBOLS)
        if unknown_roots:
            raise ValueError(f"Symbology maps to non-research roots: {sorted(unknown_roots)}")