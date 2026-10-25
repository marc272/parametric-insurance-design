"""Shared fixtures for core tests (owner: MAR-61, ADR 0002).

Other issues may use these fixtures but add their own in their test files.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)


def make_toy_eventset() -> EventSet:
    """Three events in three years at two locations, A and B.

    ========  ====  =======  =======  ======  ======
    event     year  index A  index B  loss A  loss B
    ========  ====  =======  =======  ======  ======
    ev1       0     10       15       0       1
    ev2       1     30       35       4       2
    ev3       2     50       55       10      6
    ========  ====  =======  =======  ======  ======

    Every rate is 1/3 (one event per year, ``n_years = 3``).
    """
    events = pd.DataFrame(
        {
            "event_id": ["ev1", "ev2", "ev3"],
            "year": [0, 1, 2],
            "rate": [1 / 3, 1 / 3, 1 / 3],
            "draw_id": [0, 0, 0],
            "scenario_id": ["toy", "toy", "toy"],
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A", "B"],
            "lat": [25.0, 26.0],
            "lon": [-80.0, -81.0],
            "value": [100.0, 50.0],
            "name": ["Asset A", "Asset B"],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="toy", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=3,
        scenario="toy",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 25, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.array([[10.0, 15.0], [30.0, 35.0], [50.0, 55.0]]),
        loss=np.array([[0.0, 1.0], [4.0, 2.0], [10.0, 6.0]]),
        metadata=metadata,
    )


@pytest.fixture
def toy_eventset() -> EventSet:
    """The three-event toy EventSet of :func:`make_toy_eventset`."""
    return make_toy_eventset()
