"""Common error hierarchy used across all layers.

The base class :class:`AppError` carries a stable :pyattr:`code`,
:pyattr:`message` and an optional :pyattr:`context` dict. The two
top-level subclasses split the hierarchy into:

* :class:`DomainError` — invariant violations, business rules. Mappable to HTTP 4xx.
* :class:`InfrastructureError` — failures talking to external systems.
  Mappable to HTTP 5xx (or 4xx if upstream returned 4xx).

Sub-hierarchy is intentionally shallow. Each adapter raises its own
``InfrastructureError`` subclass so handlers can match precisely.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every application-defined exception.

    A stable ``code`` allows mapping to API responses, metrics and
    troubleshooting tables without leaking Python class names.
    """

    code: str = "APP_ERROR"
    http_status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.context: dict[str, Any] = context or {}
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ---------------------------------------------------------------- domain


class DomainError(AppError):
    """Base for domain rule violations."""

    code = "DOMAIN_ERROR"
    http_status = 400


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    http_status = 422


class NotFound(DomainError):
    code = "NOT_FOUND"
    http_status = 404


class Conflict(DomainError):
    code = "CONFLICT"
    http_status = 409


class TenantNotFound(NotFound):
    code = "TENANT_NOT_FOUND"


class TunnelNotFound(NotFound):
    code = "TUNNEL_NOT_FOUND"


class TunnelAlreadyExists(Conflict):
    code = "TUNNEL_ALREADY_EXISTS"


class CrossTenantAccessDenied(DomainError):
    code = "CROSS_TENANT_ACCESS_DENIED"
    http_status = 403


class InvalidHostname(ValidationError):
    code = "INVALID_HOSTNAME"


class InvalidIngressRule(ValidationError):
    code = "INVALID_INGRESS_RULE"


# --------------------------------------------------------- infrastructure


class InfrastructureError(AppError):
    """Base for failures interacting with external systems."""

    code = "INFRASTRUCTURE_ERROR"
    http_status = 502
    retryable = True


class CloudflareAPIError(InfrastructureError):
    code = "CLOUDFLARE_API_ERROR"


class CloudflareRateLimited(CloudflareAPIError):
    code = "CLOUDFLARE_RATE_LIMITED"
    http_status = 429
    retryable = True

    def __init__(self, retry_after_seconds: float | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.retry_after_seconds = retry_after_seconds


class CloudflareUnauthorized(CloudflareAPIError):
    code = "CLOUDFLARE_UNAUTHORIZED"
    http_status = 401
    retryable = False


class KubernetesAPIError(InfrastructureError):
    code = "KUBERNETES_API_ERROR"


class KubernetesConflict(KubernetesAPIError):
    code = "KUBERNETES_CONFLICT"
    http_status = 409
    retryable = False


class DatabaseError(InfrastructureError):
    code = "DATABASE_ERROR"


class CacheError(InfrastructureError):
    code = "CACHE_ERROR"


class LockAcquisitionFailed(InfrastructureError):
    code = "LOCK_ACQUISITION_FAILED"
    retryable = True


class MessagingError(InfrastructureError):
    code = "MESSAGING_ERROR"


class SchemaRegistryError(InfrastructureError):
    code = "SCHEMA_REGISTRY_ERROR"


class DnsVerificationFailed(InfrastructureError):
    code = "DNS_VERIFICATION_FAILED"
    retryable = True


class HttpVerificationFailed(InfrastructureError):
    code = "HTTP_VERIFICATION_FAILED"
    retryable = True


# ------------------------------------------------------------------ saga


class SagaError(AppError):
    code = "SAGA_ERROR"
    http_status = 500


class SagaStepFailed(SagaError):
    code = "SAGA_STEP_FAILED"

    def __init__(
        self,
        step_name: str,
        *,
        message: str | None = None,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message or f"Saga step {step_name!r} failed", context=context, cause=cause)
        self.step_name = step_name
        self.context.setdefault("step", step_name)


class SagaCompensationFailed(SagaError):
    """Raised when a compensating action fails — operator intervention required."""

    code = "SAGA_COMPENSATION_FAILED"
    http_status = 500
    retryable = False


class SagaTimeout(SagaError):
    code = "SAGA_TIMEOUT"
    retryable = False


class IdempotencyConflict(AppError):
    """Same key, different request — operator must choose."""

    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    retryable = False
