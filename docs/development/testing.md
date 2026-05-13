# Testing strategy

## Test pyramid

```
          /\
         /e2e\          (manual, real CF account, gated)
        /------\
       /chaos   \       (staging only, scripted)
      /----------\
     /  contract  \     (Avro <-> Pydantic, fast)
    /--------------\
   /  integration   \   (testcontainers: PG / Redis / Kafka)
  /------------------\
 /        unit        \ (in-memory fakes, sub-second)
/----------------------\
```

| Layer | Marker | Run | Where |
|---|---|---|---|
| unit | `unit` (default) | `make test-unit` | every commit |
| contract | `contract` | `make test-contract` | every commit |
| integration | `integration` | `make test-integration` | PR + nightly |
| load | n/a | `make test-load` | manual / nightly |
| chaos | n/a | `tests/chaos/*.sh` | weekly in staging |
| e2e | `e2e` | `make smoke` | manual gated by CF token |

## Conventions

- **Fakes over mocks**: `tests/conftest.py` ships in-memory fakes for every port. Mocks are reserved for adapter-level tests.
- **No globals across tests**: every test gets fresh fakes. No shared event loop state.
- **Time**: `freezegun` for time-sensitive logic; never `time.sleep`.
- **Assertions on side effects**: prefer `assert fake.calls == [...]` to brittle mock call inspection.
- **Property-based tests**: hypothesis is allowed for value object parsers and serialisation round-trips.

## Adding a new saga step

1. Write a unit test in `tests/unit/test_<step>.py` exercising forward and compensation against a fake port.
2. Add the step to `application/sagas/steps/` and to the saga assembler.
3. Re-run `tests/unit/test_create_tunnel_saga.py` — happy path + each negative path should still pass without modification (this is the regression guarantee).

## Adding a new event type

1. Add the Pydantic payload in `platform/events/payloads.py`.
2. Register it in `platform/events/versioning.py` `EVENT_TYPE_TO_PAYLOAD`.
3. Add the matching `.avsc` in `platform/schemas/`.
4. Add an entry in `tests/contract/test_avro_pydantic_parity.py` `_PAIRS` — the test will then assert structural parity.

## Coverage targets

| Layer | Target |
|---|---|
| domain | 95% |
| application | 90% |
| infrastructure | 75% (adapters need integration tests) |
| apps (entrypoints) | 60% |

CI fails if total coverage drops below 80% (configured in `pyproject.toml`).
