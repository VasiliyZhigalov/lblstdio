# Task 1: Tripwire geometry + `StreamTriggerConfig`

**Files:**
- Create: `backend/app/domain/services/tripwire.py`
- Create: `backend/app/domain/value_objects/stream_trigger_config.py`
- Modify: `backend/app/domain/enums.py`
- Test: `backend/tests/unit/domain/test_tripwire.py`
- Test: `backend/tests/unit/domain/test_stream_trigger_config.py`

**Interfaces:**
- Consumes: none (pure domain)
- Produces:
  - `StreamSourceType` = `RTSP` | `VIDEO_FILE` | `DEVICE`
  - `TripwireDirection` = `ANY` | `FORWARD` | `BACKWARD`
  - `segments_intersect(a1, a2, b1, b2) -> bool`
  - `crossing_direction(p_prev, p_curr, line_a, line_b) -> TripwireDirection` (`FORWARD` if cross product of line×motion > 0, else `BACKWARD`)
  - `TripwireDebouncer(debounce_seconds).allow(track_id, now) -> bool`
  - `StreamTriggerConfig(...)` frozen dataclass with validation in `__post_init__`

- [ ] **Step 1: Write failing tripwire tests**

```python
# backend/tests/unit/domain/test_tripwire.py
from app.domain.enums import TripwireDirection
from app.domain.services.tripwire import (
    TripwireDebouncer,
    crossing_direction,
    segments_intersect,
)


def test_segments_intersect_when_crossing():
    assert segments_intersect((0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)) is True


def test_segments_do_not_intersect_when_parallel():
    assert segments_intersect((0.0, 0.2), (1.0, 0.2), (0.0, 0.8), (1.0, 0.8)) is False


def test_crossing_direction_forward_left_to_right():
    # horizontal line left→right; motion top→bottom is FORWARD by convention
    direction = crossing_direction((0.5, 0.2), (0.5, 0.8), (0.0, 0.5), (1.0, 0.5))
    assert direction == TripwireDirection.FORWARD


def test_debouncer_blocks_same_track_within_window():
    debouncer = TripwireDebouncer(debounce_seconds=3.0)
    assert debouncer.allow(track_id=7, now=100.0) is True
    assert debouncer.allow(track_id=7, now=101.0) is False
    assert debouncer.allow(track_id=7, now=104.0) is True
```

- [ ] **Step 2: Run tests — expect FAIL (import/enum missing)**

Run: `cd backend; python -m pytest tests/unit/domain/test_tripwire.py -v`  
Expected: FAIL with `ImportError` or `AttributeError` for `TripwireDirection` / `tripwire`.

- [ ] **Step 3: Implement enums + tripwire helpers**

Add to `enums.py`:

```python
class StreamSourceType(str, Enum):
    RTSP = "RTSP"
    VIDEO_FILE = "VIDEO_FILE"
    DEVICE = "DEVICE"


class TripwireDirection(str, Enum):
    ANY = "ANY"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
```

Implement `tripwire.py` using CCW orientation for intersection; direction via sign of `(Bx-Ax)*(Py-Ay) - (By-Ay)*(Px-Ax)` on the **current** point relative to directed line A→B (or equivalently cross of line vector and motion vector). Document in module docstring: `FORWARD` = positive cross (approx. left→right / top→bottom relative to A→B).

- [ ] **Step 4: Write failing config tests + implement `StreamTriggerConfig`**

```python
# backend/tests/unit/domain/test_stream_trigger_config.py
import pytest
from app.domain.enums import TripwireDirection
from app.domain.value_objects.stream_trigger_config import StreamTriggerConfig
from app.domain.exceptions import DomainValidationException


def test_defaults_are_valid():
    cfg = StreamTriggerConfig()
    assert cfg.uncertainty_range == (0.70, 0.90)
    assert cfg.cooldown_seconds == 3.0
    assert cfg.tripwire_direction == TripwireDirection.ANY


def test_rejects_inverted_uncertainty_range():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(uncertainty_range=(0.9, 0.5))


def test_rejects_line_coords_outside_unit_square():
    with pytest.raises(DomainValidationException):
        StreamTriggerConfig(tripwire_line=(0.0, 0.0, 1.5, 1.0))
```

`StreamTriggerConfig` fields (all with defaults matching the spec):  
`timer_enabled=False`, `timer_interval_seconds=5.0`, `tripwire_enabled=False`, `tripwire_line=None`, `tripwire_classes=()`, `tripwire_direction=ANY`, `tripwire_debounce_seconds=3.0`, `uncertainty_range=(0.70, 0.90)`, `cooldown_seconds=3.0`.  
Validate: intervals > 0; `0 <= unc_min < unc_max <= 1`; line coords in `[0,1]` when set; debounce/cooldown >= 0.

- [ ] **Step 5: Run all Task 1 tests — expect PASS**

Run: `cd backend; python -m pytest tests/unit/domain/test_tripwire.py tests/unit/domain/test_stream_trigger_config.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/enums.py backend/app/domain/services/tripwire.py backend/app/domain/value_objects/stream_trigger_config.py backend/tests/unit/domain/test_tripwire.py backend/tests/unit/domain/test_stream_trigger_config.py
git commit -m "feat(domain): add stream trigger config and tripwire geometry"
```
