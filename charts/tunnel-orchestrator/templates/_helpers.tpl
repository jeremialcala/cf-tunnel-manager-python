{{/*
Common helpers
*/}}

{{- define "tunnel-orchestrator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tunnel-orchestrator.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "tunnel-orchestrator.componentName" -}}
{{- printf "%s-%s" (include "tunnel-orchestrator.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tunnel-orchestrator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tunnel-orchestrator.commonLabels" -}}
app.kubernetes.io/name: {{ include "tunnel-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ include "tunnel-orchestrator.chart" . }}
app.kubernetes.io/part-of: tunnel-orchestrator
{{- end -}}

{{- define "tunnel-orchestrator.componentLabels" -}}
{{ include "tunnel-orchestrator.commonLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "tunnel-orchestrator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "tunnel-orchestrator.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "tunnel-orchestrator.image" -}}
{{- $top := index . 0 -}}
{{- $cmp := index . 1 -}}
{{- $tag := default $top.Chart.AppVersion $cmp.image.tag -}}
{{- printf "%s/%s:%s" $top.Values.global.image.registry $cmp.image.repository $tag -}}
{{- end -}}

{{/* Common env vars block (referenced by api/worker/scheduler/dlq) */}}
{{- define "tunnel-orchestrator.commonEnv" -}}
- name: APP_ENV
  value: {{ .Values.config.appEnv | quote }}
- name: APP_LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: APP_LOG_FORMAT
  value: {{ .Values.config.logFormat | quote }}
- name: API_DOCS_ENABLED
  value: {{ .Values.config.api.docsEnabled | quote }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.config.database.existingSecret }}
      key: {{ .Values.config.database.existingSecretKey }}
- name: DATABASE_POOL_SIZE
  value: {{ .Values.config.database.poolSize | quote }}
- name: DATABASE_MAX_OVERFLOW
  value: {{ .Values.config.database.maxOverflow | quote }}
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.config.redis.existingSecret }}
      key: {{ .Values.config.redis.existingSecretKey }}
- name: REDIS_LOCK_TTL_SECONDS
  value: {{ .Values.config.redis.lockTtlSeconds | quote }}
- name: KAFKA_BOOTSTRAP_SERVERS
  value: {{ .Values.config.kafka.bootstrapServers | quote }}
- name: KAFKA_SECURITY_PROTOCOL
  value: {{ .Values.config.kafka.securityProtocol | quote }}
- name: KAFKA_SCHEMA_REGISTRY_URL
  value: {{ .Values.config.kafka.schemaRegistryUrl | quote }}
- name: KAFKA_WORKER_CONCURRENCY
  value: {{ .Values.config.kafka.workerConcurrency | quote }}
- name: KAFKA_PARTITIONS_DEFAULT
  value: {{ .Values.config.kafka.partitionsDefault | quote }}
- name: KAFKA_REPLICATION_FACTOR
  value: {{ .Values.config.kafka.replicationFactor | quote }}
- name: KAFKA_CONSUMER_GROUP
  value: {{ .Values.config.kafka.consumerGroup | quote }}
- name: CLOUDFLARE_RATE_LIMIT_PER_5MIN
  value: {{ .Values.config.cloudflare.rateLimitPer5min | quote }}
- name: CLOUDFLARE_REQUEST_TIMEOUT_SECONDS
  value: {{ .Values.config.cloudflare.requestTimeoutSeconds | quote }}
- name: CLOUDFLARE_TUNNEL_CONFIG_SRC
  value: {{ .Values.config.cloudflare.tunnelConfigSrc | quote }}
- name: K8S_MODE
  value: {{ .Values.config.kubernetes.mode | quote }}
- name: K8S_DEFAULT_NAMESPACE
  value: {{ .Values.config.kubernetes.defaultNamespace | quote }}
- name: K8S_CLOUDFLARED_IMAGE
  value: {{ .Values.config.kubernetes.cloudflaredImage | quote }}
- name: K8S_CLOUDFLARED_REPLICAS
  value: {{ .Values.config.kubernetes.cloudflaredReplicas | quote }}
- name: DNS_VERIFY_TIMEOUT_SECONDS
  value: {{ .Values.config.verification.dnsTimeoutSeconds | quote }}
- name: DNS_VERIFY_NAMESERVERS
  value: {{ .Values.config.verification.dnsNameservers | quote }}
- name: HTTP_VERIFY_TIMEOUT_SECONDS
  value: {{ .Values.config.verification.httpTimeoutSeconds | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.config.observability.otlpEndpoint | quote }}
- name: OTEL_SERVICE_NAME
  value: {{ include "tunnel-orchestrator.fullname" . | quote }}
- name: OTEL_TRACES_SAMPLER_ARG
  value: {{ .Values.config.observability.tracesSamplerArg | quote }}
- name: PROMETHEUS_METRICS_PORT
  value: {{ .Values.config.observability.metricsPort | quote }}
- name: SAGA_STEP_TIMEOUT_SECONDS
  value: {{ .Values.config.resilience.sagaStepTimeoutSeconds | quote }}
- name: SAGA_GLOBAL_TIMEOUT_SECONDS
  value: {{ .Values.config.resilience.sagaGlobalTimeoutSeconds | quote }}
- name: RETRY_MAX_ATTEMPTS
  value: {{ .Values.config.resilience.retryMaxAttempts | quote }}
- name: CIRCUIT_BREAKER_THRESHOLD
  value: {{ .Values.config.resilience.circuitBreakerThreshold | quote }}
- name: CIRCUIT_BREAKER_RESET_SECONDS
  value: {{ .Values.config.resilience.circuitBreakerResetSeconds | quote }}
- name: JWT_ALGORITHM
  value: {{ .Values.jwt.algorithm | quote }}
- name: JWT_ISSUER
  value: {{ .Values.jwt.issuer | quote }}
- name: JWT_AUDIENCE
  value: {{ .Values.jwt.audience | quote }}
- name: JWT_PUBLIC_KEY_PATH
  value: /etc/jwt/public.pem
{{- end -}}

{{- define "tunnel-orchestrator.commonVolumes" -}}
- name: jwt-public
  secret:
    secretName: {{ .Values.jwt.publicKey.existingSecret }}
    items:
      - key: {{ .Values.jwt.publicKey.existingSecretKey }}
        path: public.pem
- name: tmp
  emptyDir: {}
{{- end -}}

{{- define "tunnel-orchestrator.commonVolumeMounts" -}}
- name: jwt-public
  mountPath: /etc/jwt
  readOnly: true
- name: tmp
  mountPath: /tmp
{{- end -}}
