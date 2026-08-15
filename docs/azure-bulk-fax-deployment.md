# Deploy Grounded DocParse on Azure for bulk medical faxes

## Purpose and readiness warning

This document is an implementation design and operations runbook for a single-organization, production deployment that processes protected health information (PHI). It covers browser batch uploads, automated Azure Blob Storage intake, local GLM-OCR on Azure GPU workers, optional classification and extraction, human review, and either Azure OpenAI or the official OpenAI API.

The repository is **not deployable in this form as a shared PHI service**. Its supported runtime is a trusted single-user workstation, the UI processes up to 20 files sequentially in session state, reusable definitions use local SQLite, and it has no durable jobs, multi-user authorization, or tenant isolation. Complete the application changes and acceptance gates in this document before exposing the service. Do not publish ports `7137`, `8080`, `8118`, or `8119` from the current launch scripts.

This design does not make an organization HIPAA compliant by itself. Microsoft describes HIPAA as a shared responsibility and states that a Business Associate Agreement (BAA) does not by itself establish customer compliance. The organization must approve the architecture, contracts, data flows, retention, access policy, incident response, and operating procedures before PHI is used. See [Microsoft HIPAA/HITECH guidance](https://learn.microsoft.com/compliance/regulatory/offering-hipaa-hitech).

## Chosen production baseline

| Decision | Baseline |
| --- | --- |
| Organization model | One Microsoft Entra tenant and one healthcare organization; not multi-tenant SaaS |
| Provisioning | Bicep modules deployed with Azure CLI |
| Web tier | Linux Azure App Service custom container running Streamlit |
| Authentication | App Service authentication with Microsoft Entra ID; no anonymous access |
| Edge | Application Gateway WAF v2, HTTPS only, certificate from Key Vault |
| Intake | UI folder/multiple-file upload and automated Blob batch manifests |
| Untrusted files | Separate DMZ storage account with Defender for Storage on-upload malware scanning |
| Work queue | Azure Service Bus Premium queues with dead-lettering and duplicate detection |
| Durable state | Azure Database for PostgreSQL Flexible Server |
| OCR workers | Ubuntu 24.04 Azure Virtual Machine Scale Set (VMSS), `Standard_NC8as_T4_v3` |
| Worker scale | Minimum 2, default 2, maximum 5; one active document per GPU worker |
| OCR | GLM-OCR and PP-DocLayoutV3 locally on each worker; vLLM stays on loopback |
| Optional AI | Administrator selects Azure OpenAI or official OpenAI per deployment |
| Review | Only the affected fax pauses when routing confidence is below `0.85` or segmentation needs review |
| Retention | Inputs and outputs expire after 30 days unless an approved policy overrides it |
| Definitions | Immutable, versioned Markdown routing profiles and extraction schemas |

`Standard_NC8as_T4_v3` has one NVIDIA T4 GPU with 16 GB GPU memory, eight vCPUs, and 56 GiB system memory. Availability and quota vary by subscription and region; NC-family quota commonly starts at zero. Confirm the SKU and request quota before choosing a region. See the [NCasT4_v3 specifications](https://learn.microsoft.com/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series) and [regional quota guidance](https://learn.microsoft.com/azure/quotas/regional-quota-requests).

## Reference architecture

```text
Corporate user
    |
    | HTTPS + Entra ID
    v
Application Gateway WAF v2
    |
    v
Private App Service endpoint -- Streamlit batch/review UI
    |             |                    |
    |             |                    +--> PostgreSQL: jobs, versions, audit
    |             +--> Service Bus: one message per fax
    +--> Upload broker --> DMZ Blob Storage: untrusted uploads
                         |
                  Defender malware scan
                         |
                  Event Grid + Function
                         |
                         v
                 Trusted Blob Storage
                         |
                  Service Bus work queue
                         |
                         v
             GPU VMSS worker (2-5 instances)
                |                 |
                |                 +--> Azure OpenAI private endpoint
                |                      or approved OpenAI API through controlled egress
                +--> local GLM-OCR/vLLM on 127.0.0.1:8080
                         |
                         v
            Trusted output Blob + PostgreSQL status/audit
                         |
                  Download broker
```

Use one virtual network with dedicated `ApplicationGatewaySubnet`, `AzureFirewallSubnet`, `AzureBastionSubnet`, web-integration, Function-integration, worker, private-endpoint, and image-build subnets. Delegate the two integration subnets to `Microsoft.Web/serverFarms`; do not place private endpoints in them. Route controlled outbound traffic through Azure Firewall Premium and use Azure DNS Private Resolver/approved corporate forwarding for private DNS. Use private DNS zones for Storage, Service Bus, Key Vault, PostgreSQL, Container Registry, and Azure OpenAI. Deny public network access on data services after private DNS and deployment access have been validated.

The official OpenAI API is the one intentional exception to private Azure routing. Send it through Azure Firewall Premium with stable egress, destination allowlisting and no inbound path. TLS inspection must follow the organization's approved privacy/certificate policy; never silently weaken certificate verification. Do not proxy PHI through an unapproved OpenAI-compatible endpoint. Defender for Storage scan-result delivery to an Event Grid custom topic currently requires that topic to allow public IP access. Account for that documented limitation explicitly: restrict and authenticate delivery, expose no application HTTP endpoint, and validate every event against the expected topic, type, subject, unique event ID, blob URI, ETag and Defender-provided SHA-256. Recheck the limitation before implementation and prefer private delivery when Microsoft supports it.

## Required application changes

These changes are prerequisites, not optional production enhancements.

### 1. Separate the web process from document processing

The Streamlit process must submit work and display durable state; it must not parse a batch during a browser session. Extract the existing `DocumentParser` and `DocumentAgent` calls into a worker entry point that:

1. receives one Service Bus message;
2. claims the document job atomically;
3. downloads the clean source PDF and immutable definition snapshot;
4. parses with local GLM-OCR;
5. classifies and segments when routing is enabled;
6. pauses only that document when human review is required;
7. extracts approved, eligible form segments;
8. writes outputs to Blob Storage;
9. commits status, metrics, audit events and an outbox event; and
10. completes the queue message only after the database commit succeeds.

Run one active PDF per GPU worker. The parser may retain its existing page concurrency inside that PDF. Do not run multiple vLLM servers or multiple document jobs against the same GPU until a measured load test proves memory and latency remain safe.

### 2. Add durable batch and document state

Replace session-state ownership of batch execution with PostgreSQL records. Use UUIDs, UTC timestamps, foreign keys, and optimistic concurrency. At minimum, persist:

| Record | Required data |
| --- | --- |
| `batch_job` | ID, creator Entra object ID, source, definition versions, provider mode, counts, status, created/completed timestamps |
| `document_job` | ID, batch ID, opaque display label, SHA-256, input blob URI/version/ETag, page count, stage, status, attempt, error code, review reason, worker lease/version |
| `definition` | ID, kind (`routing` or `extraction`), logical name, immutable version, SHA-256, normalized JSON, original Markdown blob key, creator, timestamp, active flag |
| `review` | document/segment IDs, predicted and corrected ranges/category, confidence, decision, reviewer Entra object ID, timestamps |
| `audit_event` | actor/service identity, action, object IDs, outcome, correlation ID, timestamp; never raw PHI or extracted values |
| `output_manifest` | document/attempt ID, immutable blob URI/version/ETag, SHA-256, media type, size, committed timestamp |
| `outbox_event` | unique event ID, aggregate/version, action, payload without PHI, publish status and attempts |

Use these statuses as the public contract:

```text
uploaded -> scanning -> queued -> parsing -> classifying
         -> needs_review -> queued_for_extraction
         -> extracting -> completed

terminal alternatives: rejected, failed, cancelled
```

Derive the batch status from document jobs: `completed`, `completed_with_review`, `completed_with_failures`, `failed`, or `cancelled`. A failed or uncertain document must not stop unrelated documents.

### 3. Make queue processing idempotent

Use `SHA256(source bytes + routing definition version + extraction definition versions + provider configuration version + parser release)` as the processing key. A repeated submission may reuse a completed result only when every component matches and policy permits reuse.

Use `document-work` for `parse` and `extract` actions and `export-work` for ZIP creation; human review is PostgreSQL state, not a queue. Every message contains schema version, unique message ID, job ID, action, expected job version and correlation ID, but no PHI. Configure duplicate detection, a five-minute lock and `maxDeliveryCount=5`. The worker renews its lock while processing and updates a database heartbeat; the maximum renewal duration must exceed the measured 99th-percentile job time. Before each stage it atomically compares job version/status so a duplicate delivery cannot run the same transition twice.

Blob Storage and PostgreSQL cannot participate in one atomic transaction. Use PostgreSQL as the visibility authority and a transactional outbox:

1. write each output once to an immutable, attempt-specific blob key and record its version, ETag and SHA-256;
2. in one PostgreSQL transaction, insert the `output_manifest`, advance the job version/status to `completed`, append the audit event and insert the outbox event;
3. expose/download only blobs referenced by a committed `output_manifest` visible to the caller;
4. complete the Service Bus message after that transaction commits;
5. have an outbox publisher send follow-on events idempotently; and
6. run a reconciler that removes unreferenced attempt blobs after a safety window and republishes unsent outbox rows.

Move exhausted deliveries to the dead-letter queue and expose them in the admin UI. This protocol tolerates a crash after Blob upload, after database commit, or before queue completion without making an orphan visible or duplicating a committed result.

Use deterministic error codes such as `malware_detected`, `invalid_pdf`, `encrypted_pdf`, `page_limit`, `ocr_failed`, `provider_failed`, `needs_review`, and `output_commit_failed`. Store safe diagnostic details separately from user-facing messages and exclude document text.

### 4. Version Markdown definitions

Keep the existing Markdown formats for routing profiles and extraction schemas. Change persistence from mutable SQLite rows to immutable versions:

1. an admin uploads `.md` in the UI;
2. the existing parser validates and normalizes it;
3. the original Markdown is stored in the trusted definition container;
4. PostgreSQL stores its normalized JSON, SHA-256, logical name, and monotonically increasing version;
5. activation changes which version is offered for new batches but never mutates existing jobs; and
6. every batch stores exact routing and extraction definition IDs/versions.

Reject a routing profile if an extractable category references a missing or inactive schema. Display a preflight summary before submission. Automated Blob batches reference the same immutable versions and cannot include arbitrary definitions.

### 5. Add the batch UI and upload/download brokers

Keep the current session-scoped workstation batch as a separate workflow. Add a durable production batch workflow with:

- a Streamlit v2 component or companion browser control that selects a directory/multiple PDFs and uploads Block Blobs directly to DMZ storage;
- a maximum of 100 PDFs, 50 MiB per batch-uploaded PDF, and 1 GiB aggregate per submission;
- a recommendation to use Blob-drop intake for larger files/batches;
- routing profile/version and provider-mode summary;
- validation results before submission;
- a durable batch table showing queued, running, review, completed, rejected, and failed counts;
- filters and pagination rather than loading all outputs into session state;
- a review screen for page-range/category corrections and approval;
- retry/cancel controls authorized by role;
- per-document JSON/Markdown/annotated-PDF downloads; and
- a server-generated ZIP request that is built asynchronously and expires with the batch.

Do not proxy a 100-file submission through Streamlit memory. An authenticated upload broker first authorizes the batch and issues a short-lived, HTTPS-only, write-only user-delegation SAS for one server-generated blob key. The browser uploads blocks directly, commits once, then calls finalize with its SHA-256. The broker records the resulting immutable version/ETag/hash and invalidates further application writes to that key. SAS lifetime is minutes, has no read/list/delete permission and is never logged. Configure DMZ Blob CORS for only the Application Gateway origin, only the required `PUT`/`OPTIONS` methods and headers, and no wildcard origins; apply a restrictive browser content-security policy.

An uploaded file is untrusted even when its extension is `.pdf`. Assign an opaque display label such as `Document 001`. Never persist a supplied filename or use it as a filesystem or Blob path because filenames may contain PHI. Identity comes from UUID and hash. Native `st.file_uploader` with `accept_multiple_files="directory"` may remain a development convenience for small synthetic batches, but it is not the production bulk-transfer path.

The web identity does not receive blanket trusted-output read access. A download broker checks the authenticated actor, application role, batch `access_scope_id`, document ownership/reviewer assignment and committed `output_manifest`, records an audit event, then returns a minutes-long read-only user-delegation SAS for exactly one blob. ZIP exports follow the same authorization and are never public.

Native Streamlit upload filtering is best-effort, not a security boundary. The installed Streamlit version supports `accept_multiple_files="directory"`, but the application must enforce count, byte, PDF-signature, encryption, and page limits on the server.

### 6. Support automated Blob batches

An upstream fax system uploads into this layout:

```text
dmz-incoming/<organization>/<batch-id>/documents/<document-id>.pdf
dmz-incoming/<organization>/<batch-id>/batch-manifest.json
```

Upload the manifest last. It is the commit marker and contains no PHI beyond approved opaque identifiers:

```json
{
  "schema_version": "1.0",
  "batch_id": "UUID",
  "routing_definition": {"id": "UUID", "version": 3},
  "documents": [
    {"document_id": "UUID", "blob_name": "documents/UUID.pdf", "sha256": "HEX"}
  ]
}
```

Validate the manifest schema and size, submitter/service-principal access scope, immutable definition versions, unique document IDs, exact blob prefix, declared hashes, 250 MiB per-file parser ceiling, 500-page ceiling, 100-document maximum and aggregate policy. The intake Function accepts only `Microsoft.Security.MalwareScanningResult` events from the configured topic/schema. It stores each event ID once to prevent replay and requires `No threats found`; `data.blobUri`, `data.eTag` and `data.scanResultDetails.sha256` must exactly match the finalized upload record and current immutable blob. It ignores Blob index tags as an authorization signal because Microsoft states they are not tamper-resistant.

Events may arrive before or after the manifest and in any order. The database records manifest and scan evidence independently and schedules a batch only when all expected finalized blob identities have matching clean evidence. A periodic reconciler marks missing/timeout/error evidence for review, retries trusted-copy/outbox failures idempotently and removes abandoned partial uploads after the approved DMZ retention window. A malicious, timed-out, unscanned, overwritten or scan-error file is never opened by a worker. Send clean files to a separate trusted storage account; quarantine or delete malicious content according to incident policy. Microsoft recommends a DMZ storage pattern and Event Grid/Function remediation for this workflow; see [Defender for Storage malware remediation](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-storage-configure-malware-scan).

### 7. Add a provider factory

The workstation gateway supports OpenAI, Google Gemini, and Agnes credentials selected in the UI. A production deployment should replace workstation environment discovery with administrator-owned secret and model configuration:

| Setting | Meaning |
| --- | --- |
| `DOCPARSE_AI_PROVIDER` | `azure_openai` or `openai`; immutable for a running deployment |
| `DOCPARSE_REASONING_MODEL` | Azure deployment name or approved OpenAI model identifier |
| `DOCPARSE_AZURE_OPENAI_ENDPOINT` | Private Azure resource endpoint; Azure mode only |
| `DOCPARSE_AZURE_OPENAI_API_VERSION` | Tested API version; Azure mode only |
| `DOCPARSE_OPENAI_BASE_URL` | Exact approved official OpenAI project endpoint; OpenAI mode only |
| `DOCPARSE_OPENAI_KEY_SECRET_URI` | Key Vault secret reference; OpenAI mode only |
| `DOCPARSE_PROVIDER_CONFIG_VERSION` | Immutable non-secret provider snapshot version included in job idempotency/audit metadata |

Azure mode uses `DefaultAzureCredential`/managed identity and grants only the required Foundry inference role. Disable local API-key fallback. OpenAI mode lets only worker identities read the versioned Key Vault secret and never shows or logs it. Store the complete non-secret endpoint/model/API-version/retention-policy snapshot under `DOCPARSE_PROVIDER_CONFIG_VERSION`. Fail closed when configuration is incomplete, when the configured hostname is not allowlisted, or when a required compliance approval flag is absent.

Before approving a model/deployment, run contract tests for the Responses API behavior, Pydantic structured output, image input, maximum context/output, rate limits, and every agentic stage. Do not assume an Azure deployment is interchangeable with the hardcoded current model. Azure states that prompts/completions for models sold by Azure are not available to model providers and are not used to train foundation models without permission, but abuse-monitoring and deployment geography still require review. See [Azure Foundry data privacy](https://learn.microsoft.com/azure/foundry/responsible-ai/openai/data-privacy).

For the official OpenAI API, PHI is prohibited until the organization has an OpenAI BAA that covers the API services and the organization/project is provisioned with the required retention controls. Confirm the exact endpoint and model are eligible. OpenAI documents the current requirements in [How to request an API BAA](https://help.openai.com/en/articles/8660679-how-can-i-get-a-business-associate-agreement-baa-with-openai/) and [HIPAA-eligible functionality](https://help.openai.com/en/articles/20001069-hipaa-eligible-products-and-functionality). Keep `store=false`; do not enable tools or endpoints outside the approved scope.

## Azure resource contract

Create Bicep modules rather than one monolithic template. The eventual implementation should contain modules equivalent to the following contract.

| Module | Required resources and controls |
| --- | --- |
| `network` | VNet, the eight named subnets, NSGs/UDRs, Azure Firewall Premium, Azure DNS Private Resolver, private DNS zones/links and DDoS Network Protection |
| `identity` | User-assigned identities for web, intake Function, and worker; least-privilege Entra/RBAC assignments |
| `edge` | Application Gateway WAF v2, WAF policy, HTTPS listener, Key Vault certificate identity, health probe |
| `web` | Linux App Service Plan and Web App custom container, dedicated user-assigned identity, VNet integration, private endpoint, Entra authentication, public access denied |
| `registry` | Premium ACR, public access denied, private endpoint, image-pull roles, content trust/signing policy |
| `storage-dmz` | GPv2 Blob account, Defender on-upload scan, no shared-key access, TLS 1.2+, private endpoint, Event Grid scan results, limited retention |
| `storage-trusted` | GPv2 Blob account for clean inputs, definitions, outputs and exports; versioning/soft-delete policy aligned with PHI deletion; private endpoint |
| `messaging` | Service Bus Premium namespace, document-work/export-work queues, duplicate detection, DLQs, private endpoint, managed-identity roles |
| `database` | Zone-redundant PostgreSQL Flexible Server, private networking, Entra administrator, PITR backup, hourly encrypted logical DR snapshots, no public access |
| `intake` | Function Apps for upload/download brokering, manifest/scan events, outbox/reconciliation and exports; private integration, managed identities, Event Grid subscriptions |
| `ai` | Optional Azure OpenAI/Foundry resource, approved regional or data-zone deployment, private endpoint, managed-identity role |
| `gpu-image` | Azure Compute Gallery and image definition/version containing the validated worker runtime and pinned models |
| `workers` | Flexible VMSS from the gallery image, `Standard_NC8as_T4_v3`, zones where supported, system health extension, min/default 2 and max 5 |
| `operations` | Log Analytics, Application Insights/OpenTelemetry destination, diagnostic settings, alerts, action group, budgets, Defender plans |

Use Bicep parameters for environment, location, resource-name prefix, Entra group object IDs, custom domain, certificate secret URI, retention days, GPU SKU, worker bounds, provider mode, Azure OpenAI deployment name, and alert recipients. Never put keys, connection strings, passwords, source documents, or extracted data in Bicep parameters or deployment outputs.

### Required roles

Assign at the narrowest resource/container scope that supports the operation:

| Identity | Minimum data-plane access |
| --- | --- |
| Web app | Service Bus sender and scoped database web role; no provider secret, DMZ-data or trusted-output data role |
| Upload/download broker | Storage Blob Delegator plus narrowly scoped DMZ write or committed-output read role, database authorization/audit role |
| Intake Function | DMZ reader, trusted Blob contributor, Service Bus sender, database intake/outbox role |
| GPU worker | Trusted input/definition reader, trusted output contributor, Service Bus receiver, database worker role, Azure OpenAI inference role when enabled |
| Export worker | Output reader/writer for export container, Service Bus receiver, database export role |
| Application Gateway | Key Vault certificate-secret read only |

Do not grant `Owner`, `Contributor`, Storage Account Contributor, or subscription-wide data roles to runtime identities. Use one documented user-assigned identity per runtime component; App Service/Function/VMSS system identities are disabled to avoid ambiguity. Separate deployment identity from runtime identities.

Every batch has an `access_scope_id`. For the initial single-scope deployment, use Entra groups `DocParse-Submitters`, `DocParse-Reviewers`, and `DocParse-Admins`: submitters may create batches and read only batches they created; reviewers may read/review batches in their assigned access scope; admins may manage definitions, retry/DLQ operations and access assignments but receive no routine clinical review permission. Enforce these rules in every database query and broker request, not only in the UI. Put admin membership behind Privileged Identity Management with approval/time limits, run quarterly access reviews, and apply conditional access/MFA. Automated Blob intake uses its own service principal/managed identity mapped to one access scope and exact DMZ prefix.

## Build and deployment procedure

Commands below are the operator contract for the future Bicep and image implementation. They assume Bash in Azure Cloud Shell and are not executable until the named files exist.

### 1. Select the subscription and region

```bash
az login
az account set --subscription "<subscription-id>"
az account show --query '{subscription:id,tenant:tenantId,name:name}' -o table
az vm list-usage --location <region> -o table
az vm list-skus --location <region> --size Standard_NC8as_T4_v3 \
  --all --query '[?restrictions==`[]`].[name,locations]' -o table
```

Request sufficient regional NCasT4_v3 vCPU quota for five `Standard_NC8as_T4_v3` workers plus rollout headroom. Verify the chosen region supports the VM SKU, availability zones if required, Defender malware scanning, App Service, Service Bus Premium, PostgreSQL, and the selected Azure OpenAI model/deployment type. Do not substitute a GPU SKU without rerunning OCR correctness, throughput, memory, and cold-start tests.

### 2. Prepare deployment parameters

Use a non-secret parameter file such as `infra/environments/prod.bicepparam`. Record resource names, region, subnet CIDRs, Entra group object IDs, retention, GPU bounds, custom domain, and provider mode. Reference the Key Vault certificate by resource ID/secret URI; do not place certificate contents in the file.

Validate before deployment:

```bash
az bicep upgrade
az deployment sub validate \
  --location <region> \
  --template-file infra/main.bicep \
  --parameters infra/environments/prod.bicepparam

az deployment sub what-if \
  --location <region> \
  --template-file infra/main.bicep \
  --parameters infra/environments/prod.bicepparam
```

Security and the resource owner must review `what-if`, provider egress, RBAC, public-network flags, retention, and estimated cost before creation.

### 3. Deploy shared infrastructure

```bash
az deployment sub create \
  --name docparse-prod-$(date -u +%Y%m%d%H%M%S) \
  --location <region> \
  --template-file infra/main.bicep \
  --parameters infra/environments/prod.bicepparam
```

Capture only non-secret deployment outputs. Verify private DNS from an authorized VNet host before disabling public access. Confirm Application Gateway cannot yet route to the application until the web health probe passes.

### 4. Build and validate the GPU image

Build an Ubuntu 24.04 image in an isolated image-build resource group. Install Azure-supported NVIDIA CUDA drivers, `uv`, Python 3.12.10, the locked project with the `local-ocr` extra, and systemd units for vLLM and the queue worker. Download the exact pinned GLM-OCR and PP-DocLayoutV3 snapshots during image build, materialize the runtime configuration, then force `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at runtime.

The image must not contain secrets, documents, results, logs, database credentials, or provider keys. Generalize it only after these checks pass:

```bash
nvidia-smi
uv run python -c "import glmocr, torch, transformers, vllm"
uv run python scripts/wsl/check-glmocr-api.py
uv run pytest -q
```

Publish an immutable Compute Gallery version. Pin the VMSS to that version; never deploy `latest`. Each VM runs vLLM on `127.0.0.1:8080` and the worker without a public IP. A health check must validate model discovery and a real synthetic image-recognition request before the instance receives queue work. Microsoft documents supported GPU driver installation in [N-series Linux driver setup](https://learn.microsoft.com/azure/virtual-machines/linux/n-series-driver-setup).

### 5. Build and publish application images

Create separate web, intake, and worker artifacts even if they share a Python package. Build from the locked dependency graph, run tests, generate an SBOM, scan dependencies/container layers, sign the image, and push an immutable digest to ACR. Deploy by digest, not a mutable tag. The web image exposes only Streamlit port `7137`; set App Service `WEBSITES_PORT=7137`.

### 6. Run database migrations

Run migrations as a one-off deployment job using a dedicated migration identity/role. The web and workers must not create or alter production tables at startup. Back up the database, test downgrade/forward compatibility, apply the migration, then deploy code that requires it.

### 7. Configure the AI provider

For Azure OpenAI:

1. deploy an approved model in the chosen region/data zone;
2. disable public access and approve the private endpoint;
3. assign the worker managed identity the inference role;
4. set provider, endpoint, API version, deployment name, and config version as App Service/VMSS settings; and
5. run the structured-output/image/limit contract suite from the worker subnet.

For official OpenAI:

1. obtain and record approval of the OpenAI BAA and eligible API configuration;
2. create a dedicated OpenAI project and least-privilege key;
3. place the key in Key Vault through an approved secret-entry channel;
4. grant only the worker identity access to that secret;
5. allowlist the exact official hostname through controlled egress; and
6. verify retention controls, `store=false`, model eligibility, and audit evidence before enabling PHI.

Do not configure both credentials in the same deployment. A provider switch is a maintenance event: pause intake, drain all parse/extract jobs and reviews under the old provider, verify no active leases, remove the old credential, deploy the new provider snapshot/config version, run synthetic contract tests, then reopen intake. Jobs may not cross that boundary. Historical records retain the non-secret snapshot and Key Vault secret-version identifier for audit, but the application never keeps both providers usable at once.

### 8. Enable ingress last

Enable Entra authentication with unauthenticated requests rejected, assign the three application groups, validate role mapping, then enable the Application Gateway listener. Configure the App Service custom domain, allowed redirect URLs and forwarded host handling so authentication always returns through the public Application Gateway hostname. Public access remains disabled on App Service; the gateway reaches its private endpoint. Require HTTPS, modern TLS, WAF prevention mode after tuning, secure cookies, short session lifetime, and organization-approved conditional-access/MFA policy. Run one web instance initially; before web scale-out, validate Streamlit WebSocket affinity and prove all authoritative state remains outside the process.

## Runtime configuration

Continue to use the parser variables in [SETUP.md](../SETUP.md), with values benchmarked for the production image. Add the following deployment settings:

| Variable | Production value/policy |
| --- | --- |
| `DOCPARSE_ENVIRONMENT` | `production` |
| `DOCPARSE_AI_PROVIDER` | Exactly `azure_openai` or `openai` |
| `DOCPARSE_REASONING_MODEL` | Approved deployment/model identifier |
| `DOCPARSE_PROVIDER_CONFIG_VERSION` | Monotonic release-controlled value |
| `DOCPARSE_DATABASE_DSN` | Managed-identity/Entra-capable PostgreSQL configuration; never plaintext password |
| `DOCPARSE_SERVICE_BUS_NAMESPACE` | Fully qualified private namespace |
| `DOCPARSE_WORK_QUEUE` | Production work queue name |
| `DOCPARSE_STORAGE_ACCOUNT` | Trusted storage account URL |
| `DOCPARSE_DMZ_STORAGE_ACCOUNT` | DMZ storage account URL |
| `DOCPARSE_INPUT_CONTAINER` | Clean input container |
| `DOCPARSE_OUTPUT_CONTAINER` | Result container |
| `DOCPARSE_DEFINITION_CONTAINER` | Immutable definitions container |
| `DOCPARSE_EXPORT_CONTAINER` | Expiring ZIP exports container |
| `DOCPARSE_BATCH_MAX_FILES` | `100` |
| `DOCPARSE_BATCH_MAX_FILE_BYTES` | `52428800` (50 MiB) |
| `DOCPARSE_BATCH_MAX_TOTAL_BYTES` | `1073741824` (1 GiB) |
| `DOCPARSE_RESULT_RETENTION_DAYS` | `30` |
| `DOCPARSE_CLASSIFICATION_THRESHOLD` | `0.85` |
| `DOCPARSE_LOG_LEVEL` | `INFO`; debug disabled in production |

Keep the parser's 250 MiB hard document limit as defense in depth for Blob intake, while the browser batch path uses the lower 50 MiB limit. Keep `DOCPARSE_MAX_PAGES=500` unless a lower organizational limit is approved. Worker-local temporary directories must use encrypted OS/temporary disks where supported and be removed after every job; startup cleanup removes abandoned job directories without logging their names.

## Security and PHI controls

### Data minimization and logging

Log correlation IDs, batch/document UUIDs, definition versions, provider/model name, prompt version, stage, status, duration, token counts, retry counts, worker ID, and safe error code. Do not log filenames when they contain patient data, raw prompts, OCR text, extracted fields, images, PDFs, access tokens, SAS URLs, keys, connection strings, or full provider error bodies. Configure diagnostics so HTTP query strings and headers containing credentials are not captured.

Use opaque Blob names. Encrypt in transit and at rest. Decide with security whether platform-managed keys or customer-managed keys are required; test key rotation and recovery. Disable Storage shared-key authorization and unrestricted SAS. Prefer managed identity. If a short-lived user-delegation SAS is required for a download, scope it to one blob, read-only, HTTPS-only, and minutes rather than hours.

### Retention and deletion

Apply these baseline active-data schedules unless legal policy requires a documented hold or different period:

| Data | Active retention and disposal |
| --- | --- |
| Incomplete DMZ upload | Delete after 24 hours |
| Clean DMZ source after trusted copy | Delete immediately after copy/hash verification and intake commit |
| Malicious, scan-error or timed-out DMZ source | Quarantine for seven days with security-only access, then delete unless incident/legal hold applies |
| Trusted source PDF and document outputs | Delete 30 days after terminal batch completion |
| Generated ZIP export | Delete after 24 hours |
| PostgreSQL review corrections, routing segments, output manifests and PHI linkage | Purge or irreversibly de-identify 30 days after terminal batch completion, after referenced blobs are deleted |
| Batch/document operational shell | Retain only opaque IDs, terminal status, definition/config versions and non-PHI audit linkage for the approved audit period |

A daily retention worker selects eligible records under a database lease, writes a non-PHI deletion audit event, deletes current Blob versions, waits for confirmation, then transactionally purges/de-identifies PHI columns and records a tombstone. It retries idempotently and alerts on anything overdue by 24 hours. Legal/incident holds are explicit records with owner, reason, approval and expiry; ordinary users cannot set them.

Use seven-day Blob soft delete/version recovery and 35-day PostgreSQL backup retention for the baseline; document that these create residual recovery windows, so active-data deletion is not immediate physical erasure from every backup. Align final values with legal policy and the BAA before launch. Platform-managed encryption is the baseline; enable customer-managed keys only when organizational policy requires them, then add and test key rotation/recovery before launch.

Definitions and non-PHI operational audit records may use a longer approved retention. Sources, OCR, outputs, review records, filenames received at ingress, form categories, page boundaries and linkage metadata are all treated as PHI. Privacy/legal owners decide whether any output belongs to a designated record set and define amendment/disclosure procedures before production.

### Availability and disaster recovery

The baseline target is 99.5% monthly application availability, primary-region RPO of 15 minutes and RTO of four hours, and regional-disaster RPO of one hour and RTO of 24 hours. These are engineering objectives, not an Azure or product SLA, and must be replaced if the business impact analysis requires stricter values.

Use zone-redundant Application Gateway, Service Bus Premium and PostgreSQL where the region supports them; keep at least two workers across zones. Require RA-GZRS for PHI/definition/recovery Blob data so exact versions are readable in the secondary region. Use PostgreSQL PITR backups for primary-region recovery, ACR geo-replication, replicated Compute Gallery image versions, versioned Bicep/parameters and a preapproved secondary region inside the required data geography. Service Bus messages are reconstructible from PostgreSQL/outbox state; after failover, reconcile and requeue every nonterminal job rather than assuming queue messages replicated. Rehearse regional recovery with synthetic data twice yearly and record achieved RPO/RTO. If RA-GZRS or the approved secondary-region posture is unavailable, production approval must formally accept that a regional outage can exceed the targets.

Create an hourly `dr_checkpoint` with this explicit protocol:

1. open a repeatable-read PostgreSQL transaction, call `pg_export_snapshot()` and capture aggregate sequence `N`;
2. create an encrypted logical database dump with `pg_dump --snapshot=<exported-id>` while the exporting transaction remains open;
3. upload the dump to the RA-GZRS recovery container with immutable version, ETag and SHA-256;
4. verify the dump and every committed input/output/definition blob referenced through sequence `N` are readable through the secondary endpoint with their exact versions/ETags/hashes; and
5. write a recovery manifest containing checkpoint ID, sequence, UTC time, dump version/hash, Blob inventory hash and provider/config versions, sign its canonical bytes with a dedicated Key Vault asymmetric key, and store the manifest/signature in the secondary-readable recovery container.

The checkpoint is valid only after all five steps succeed. Logical DR snapshots contain PHI, use the same access/encryption controls as source documents, retain the latest 35 days and are never application-downloadable. This verified checkpoint—not Flexible Server geo-restore or wall-clock guesswork—is the latest permissible coordinated regional recovery point.

Regional failover follows this order:

1. declare the incident, block new intake and fence primary-region web, broker, Function and worker identities;
2. select the newest verified `dr_checkpoint` available in the secondary region;
3. deploy/validate the secondary infrastructure from the approved Bicep and immutable image versions;
4. create/validate PostgreSQL in the secondary region and restore the exact logical dump named by the checkpoint manifest, then select the matching replicated Blob versions;
5. run reconciliation: every committed manifest must resolve to the recorded version/ETag/hash, unreferenced blobs remain invisible, and records newer than the checkpoint are treated as RPO loss rather than guessed/replayed;
6. reconstruct Service Bus work/outbox messages for every nonterminal committed job, preserving job versions and idempotency keys;
7. run synthetic authentication, malware-intake, OCR, provider, authorization and download tests;
8. switch the controlled DNS/Application Gateway entry point and reopen intake after incident-command approval; and
9. publish achieved RPO/RTO and affected batch IDs through the approved incident process without PHI in general logs.

For failback, keep the recovered region authoritative, drain intake/work, create and verify a new checkpoint replicated to the repaired primary, restore and reconcile there, run the same smoke tests, switch traffic once, then retire the temporary authority. Never accept writes in both regions concurrently.

### Network and host controls

- No public IPs on GPU workers, PostgreSQL, Storage, Service Bus, Key Vault, ACR, or Azure OpenAI.
- Never expose vLLM port `8080`; bind it to loopback on each worker.
- Restrict NSGs by subnet and service tag; deny lateral access not required by the data flow.
- Use Azure Bastion or approved just-in-time access for emergency administration; disable routine SSH.
- Apply OS security updates through a tested image replacement, not manual drift.
- Send Defender, WAF, identity, database, storage and VMSS alerts to the incident-response action group.
- Use Azure Policy to deny public access, unapproved regions/SKUs, missing diagnostics, and resources without required tags.

Use this default address/routing contract unless it overlaps an approved enterprise network; any replacement must preserve subnet separation and be documented in environment parameters:

| Subnet | Baseline CIDR | Delegation/use |
| --- | --- | --- |
| `ApplicationGatewaySubnet` | `10.40.0.0/24` | Application Gateway only |
| `AzureFirewallSubnet` | `10.40.1.0/26` | Azure Firewall only |
| `AzureBastionSubnet` | `10.40.1.64/26` | Azure Bastion only |
| `snet-web-integration` | `10.40.2.0/24` | Delegated to `Microsoft.Web/serverFarms` |
| `snet-function-integration` | `10.40.3.0/24` | Delegated to `Microsoft.Web/serverFarms` |
| `snet-workers` | `10.40.4.0/24` | GPU VMSS; no public IP |
| `snet-private-endpoints` | `10.40.5.0/24` | Private endpoints only; private-endpoint network policies configured as required |
| `snet-image-build` | `10.40.6.0/24` | Ephemeral image builder; separate identity/UDR |

Apply default-deny NSGs and UDRs. Permit only this application traffic; Azure platform/health traffic required by a service must be added from its current first-party documentation and captured in Bicep tests:

| Source | Destination | Ports | Purpose |
| --- | --- | ---: | --- |
| Internet/corporate edge | Application Gateway public frontend | TCP 443 | Authenticated UI only; WAF/TLS termination |
| Application Gateway | App Service private endpoint | TCP 443 | Streamlit/WebSocket backend |
| Web integration subnet | Upload/download broker, PostgreSQL and Service Bus private endpoints | TCP 443, 5432, 5671 | UI APIs, durable state and enqueue |
| Function integration subnet | Storage, PostgreSQL, Service Bus, Key Vault private endpoints | TCP 443, 5432, 5671 | Intake, brokers, outbox, reconciliation and exports |
| Worker subnet | Storage, PostgreSQL, Service Bus and Azure OpenAI private endpoints | TCP 443, 5432, 5671 | Job input/state/output and Azure provider calls |
| Worker subnet | Azure Firewall | TCP 443 | Official OpenAI only; firewall allows the approved API hostname and denies other Internet egress |
| Bastion subnet | Worker/image-build subnet | TCP 22 | Approved just-in-time emergency administration |
| All application subnets | Azure DNS Private Resolver | UDP/TCP 53 | Name resolution |
| Approved components | Azure Monitor/Entra/Key Vault service endpoints through Firewall | TCP 443 | Telemetry, identity and secret resolution |
| Image-build subnet | Approved ACR, package/model source allowlist through Firewall | TCP 443 | Build time only; runtime workers remain model-cache offline |

Route `0.0.0.0/0` from web, Function, worker and image-build subnets to Azure Firewall; do not create direct Internet routes or public IPs. Use explicit firewall application rules for official OpenAI, Entra, Azure Monitor and approved build sources, and network rules only where FQDN rules cannot work. Private DNS zones must include `privatelink.blob.core.windows.net`, `privatelink.servicebus.windows.net`, `privatelink.vaultcore.azure.net`, `privatelink.postgres.database.azure.com`, `privatelink.azurecr.io`, the App Service private-link zone and the Azure OpenAI/Foundry private-link zone documented for the deployed resource. Link them only to approved VNets and test that public names resolve to private addresses from each runtime subnet.

## Autoscaling and capacity

Autoscale the VMSS from two to five instances using Service Bus `ActiveMessageCount`, while maintaining one active document per worker. Start with these rules and tune only from measured production-like synthetic load:

- scale out by one when active messages exceed two per running instance for five minutes;
- use a ten-minute scale-out cooldown to avoid repeated model cold starts;
- scale in by one when no active messages exist for 30 minutes and no worker owns a lease;
- use a 30-minute scale-in cooldown; and
- never remove an instance until its worker drains, releases no job lease, and passes a termination check.

Azure Monitor can autoscale VMSS instances from Service Bus queue metrics; see [Azure Monitor autoscale metrics](https://learn.microsoft.com/azure/azure-monitor/autoscale/autoscale-common-metrics). GPU capacity is not guaranteed merely because quota exists. Reserve capacity for the two baseline workers when the chosen SKU/region supports reservations; otherwise production approval must explicitly accept allocation risk. Treat workers three through five as on-demand burst capacity and alert when scale-out allocation fails.

Do not publish a throughput promise before benchmarking representative fax page counts, resolution, classification frequency, extraction schemas, provider rate limits, and review rates. Track pages/minute, documents/hour, queue age, stage latency, GPU utilization/memory, provider tokens/cost, retry rate, failure rate, and review rate.

## Operations

### Normal batch flow

1. Submitter chooses an active routing definition and uploads/selects a folder of PDFs, or an upstream system commits a Blob manifest.
2. Files remain untrusted in the DMZ until malware results are available.
3. Clean files move to trusted storage and one job message is sent per PDF.
4. Workers parse and classify independently.
5. High-confidence eligible forms continue to extraction.
6. Only uncertain documents enter `needs_review`; the rest of the batch continues.
7. Reviewer corrects/approves routing; a new extraction message resumes that document without repeating OCR.
8. Results are written durably and appear in the batch UI.
9. An optional asynchronous export job creates an expiring ZIP.

### Alert baseline

Create actionable alerts for:

- oldest active message age over 15 minutes;
- DLQ message count above zero;
- no healthy GPU workers;
- VMSS allocation or image health failure;
- vLLM synthetic health probe failure;
- document failure rate above 5% for 15 minutes;
- provider HTTP 429/5xx or content-filter spike;
- malware detection or scan errors/timeouts;
- WAF blocks/authentication anomalies;
- PostgreSQL storage, connection or replica/backup failure;
- Blob lifecycle or Event Grid delivery failure;
- Key Vault access anomalies; and
- spending thresholds at 50%, 75%, 90%, and 100% of the monthly budget.

### Retry and recovery

- Operator retry creates an audit event and a new attempt; it never overwrites prior error evidence.
- Parser/provider transient failures use bounded exponential backoff, then Service Bus redelivery.
- A worker crash is recovered by message lock expiry and idempotent stage checks.
- A provider outage leaves OCR results durable and resumes only the failed optional stage.
- A review correction preserves predicted and corrected routing values and reviewer identity.
- Primary-region recovery may use PostgreSQL PITR; regional recovery must use a verified logical `dr_checkpoint` and matching RA-GZRS Blob versions. Rehearse both paths quarterly with synthetic data.
- Deployments use rolling replacement with at least two healthy workers. Roll back web/worker image digests and database-compatible code; never amend a released image.

## Pre-production acceptance gates

Use only synthetic or formally approved de-identified documents until every gate passes.

### Functional

- Submit 100 PDFs through UI folder selection and through a Blob manifest.
- Verify unique jobs, per-file progress, partial failures, pagination and result download.
- Verify routing profile and extraction schema versions are immutable and reproduced in outputs.
- Verify adjacent same-category forms remain separate unless evidence supports a boundary merge.
- Verify confidence below `0.85` pauses only the affected document.
- Correct a segment, approve it and confirm extraction resumes without rerunning OCR.
- Generate and expire a batch ZIP.

### Input and failure handling

- Reject a non-PDF renamed `.pdf`, malformed PDF, encrypted PDF, oversized file, over-page-limit PDF, duplicate manifest/document ID and hash mismatch.
- Confirm clean files alone reach trusted storage/workers.
- Confirm malicious, unscanned, timed-out and scan-error files never execute and create alerts.
- Kill a worker during OCR and confirm exactly one durable result after recovery.
- Deliver the same queue message repeatedly and confirm no duplicate processing/output.
- Exhaust retries and confirm the message, safe error and admin action appear in the DLQ workflow.

### AI providers

- Run the full structured-output and image-input contract suite for the selected Azure OpenAI deployment.
- Repeat for an approved official OpenAI project before that mode is separately released.
- Confirm `store=false`, expected endpoint hostname, provider/model/config version and token usage in safe audit metadata.
- Confirm no direct OpenAI key exists in Azure mode and no Azure credential fallback exists in OpenAI mode.
- Simulate rate limits, timeouts, invalid schemas, content filtering and endpoint DNS/TLS failure.

### Security and compliance

- Confirm anonymous users, submitters attempting review/admin actions and reviewers attempting administration are denied.
- Confirm data services and workers have no public network path.
- Confirm WAF/TLS, private DNS, managed identities and least-privilege roles from a clean deployment.
- Search logs, traces, alerts and deployment outputs for synthetic patient markers and secret canaries; the result must be empty.
- Prove DMZ cleanup, 30-day Blob expiry, 24-hour export expiry, PostgreSQL PHI purge/de-identification, tombstones and legal-hold exceptions in a shortened test environment.
- Create a coordinated DR checkpoint, fail over from matching PostgreSQL/Blob versions, reconcile/requeue nonterminal jobs, fail back and document achieved RPO/RTO.
- Obtain written security, privacy, compliance, model-risk and operational approval.

Production launch is blocked by any failed gate.

## Troubleshooting

| Symptom | Checks and action |
| --- | --- |
| GPU VMSS will not scale | Check regional NCasT4_v3 quota, SKU restrictions, capacity, image version and subnet address space |
| Worker is healthy but jobs remain queued | Check Service Bus receiver role, private DNS, lock acquisition, worker drain flag and queue name |
| vLLM model list works but OCR fails | Run the synthetic image probe, inspect safe worker/vLLM diagnostics, confirm pinned model/config and GPU memory |
| Every upload stays in scanning | Check Defender plan, scan-result Event Grid delivery, Function identity, supported region and scan status |
| File was scanned but not processed | Require `No threats found`; compare manifest hash/path and trusted-storage copy transaction |
| Batch repeats documents | Inspect idempotency key, database unique constraint, Service Bus duplicate window and message completion order |
| Review approval does not resume | Check review transaction, immutable definition versions, extraction enqueue event and document version conflict |
| Azure OpenAI returns auth failure | Check private DNS, managed identity role propagation, deployment name/API version and public-access setting |
| Official OpenAI is unreachable | Check approved hostname, NAT/Firewall egress, Key Vault access and project/key status; do not bypass the allowlist |
| UI loses progress after refresh | The UI must reload PostgreSQL state by batch ID; session state is not authoritative |
| PHI appears in logs | Disable affected logging/export immediately, preserve incident evidence securely, rotate exposed credentials if applicable and invoke incident response |

## Deployment evidence and handoff

Before handoff, store these non-PHI artifacts in the organization-approved evidence repository:

- approved architecture and data-flow diagram;
- Bicep source, parameter hashes, `what-if` review and deployment IDs;
- image digests, SBOMs, signatures, vulnerability reports and pinned model revisions;
- Entra groups, managed identities and reviewed RBAC export;
- private endpoint/DNS and public-access verification;
- WAF, Defender, retention, backup and alert configuration evidence;
- AI provider contract/eligibility approval and configuration version;
- synthetic acceptance and load-test reports;
- recovery exercise results; and
- named service owner, security owner, incident contacts and review date.

Revalidate the runbook after any model, provider API version, dependency lock, GPU image, retention rule, network boundary, identity policy or data-flow change. Review first-party service documentation and contractual scope at every production release; cloud capabilities and eligibility change over time.

## First-party references

- [Microsoft HIPAA/HITECH offering and shared responsibility](https://learn.microsoft.com/compliance/regulatory/offering-hipaa-hitech)
- [Data, privacy and security for models sold by Azure](https://learn.microsoft.com/azure/foundry/responsible-ai/openai/data-privacy)
- [Azure AI security best practices](https://learn.microsoft.com/azure/security/fundamentals/ai-security-best-practices)
- [App Service authentication with Microsoft Entra ID](https://learn.microsoft.com/azure/app-service/tutorial-auth-aad)
- [App Service custom containers](https://learn.microsoft.com/azure/app-service/configure-custom-container)
- [Azure private endpoints](https://learn.microsoft.com/azure/private-link/private-endpoint-overview)
- [NCasT4_v3 GPU VM sizes](https://learn.microsoft.com/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series)
- [NVIDIA drivers on Azure N-series Linux VMs](https://learn.microsoft.com/azure/virtual-machines/linux/n-series-driver-setup)
- [VMSS autoscaling](https://learn.microsoft.com/azure/virtual-machine-scale-sets/virtual-machine-scale-sets-autoscale-overview)
- [Service Bus queues, topics and subscriptions](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-queues-topics-subscriptions)
- [Defender for Storage malware scanning](https://learn.microsoft.com/azure/defender-for-cloud/introduction-malware-scanning)
- [Defender malware scan-result Event Grid configuration and schema](https://learn.microsoft.com/azure/defender-for-cloud/advanced-configurations-for-malware-scanning)
- [Automated malware remediation and DMZ storage](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-storage-configure-malware-scan)
- [Azure Storage lifecycle management](https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-overview)
- [Managed identities for Azure resources](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview)
- [OpenAI API data controls](https://platform.openai.com/docs/models/default-usage-policies-by-endpoint)
- [OpenAI API BAA requests](https://help.openai.com/en/articles/8660679-how-can-i-get-a-business-associate-agreement-baa-with-openai/)
- [OpenAI HIPAA-eligible products and API functionality](https://help.openai.com/en/articles/20001069-hipaa-eligible-products-and-functionality)
