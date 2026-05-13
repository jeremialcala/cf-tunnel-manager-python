# Contributing

## Workflow

1. Fork or branch off `main`.
2. Open a draft PR early — CI runs on every push.
3. Keep commits small and message conventional (`feat: ...`, `fix: ...`).
4. Pre-commit hooks run ruff + mypy + gitleaks. Don't bypass them; if a hook is wrong, fix the hook.
5. PR template asks for: motivation, breaking change?, alembic migration?, observability impact?, runbook update?.

## Code style

- Type hints **everywhere**. `mypy --strict` passes in CI.
- Public functions documented with concise docstrings — focus on *why*, not *what*.
- No print/`logging` calls — use `shared.logging.get_logger`.
- One thing per line; PEP-8 line length 100.

## Architectural rules (enforced by review + linters)

- `domain/` imports only `shared/` and stdlib. **Never** infra.
- `application/` imports `domain/` + own `ports/`. **Never** infra.
- `infrastructure/` may import `application/ports/` and `domain/`. **Never** other infra adapters across boundaries.
- `apps/` is the only place the composition root lives. **Never** import infra from a business module.
- New adapter? Add it under `infrastructure/<area>/` and bind it in `apps/composition.py`.
- New use case? Command + handler + saga (if multi-step) + DTOs + tests.

## Database changes

- Always via Alembic. `make migrate-rev M="message"`.
- Migrations must be **forward-only and reversible without data loss**.
- For column drops: 2-PR pattern — first PR ignores the column in code, second PR drops.

## Event schema changes

- See `docs/kafka-contracts/README.md` versioning policy.
- Run `make test-contract` locally before pushing.

## Releasing

- Tag a SemVer release (`vX.Y.Z`). The `release.yml` workflow builds + pushes images and packages the Helm chart as a GitHub Release asset.
- ArgoCD will pick up the new chart on its next sync.
