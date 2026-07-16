# Deployment Rationale

Justifications for the decisions in [DEPLOYMENT.md](./DEPLOYMENT.md). Each choice is weighed against the project's three governing constraints: **data privacy is non-negotiable** (self-hosted LLM), **the audience is small** assumption (<50 internal users), and **the team's operational comfort zone is a single VM with Docker Compose**.

## Why self-hosted Ollama rather than a managed AI API

Compliance requirement: document content must never leave infrastructure we control. Managed APIs (Bedrock, OpenAI, Anthropic) would be cheaper and faster to operate, but they transmit document text to a third party, which fails the constraint outright. This single requirement is what makes the deployment non-trivial — everything else in the plan is shaped around hosting inference ourselves.

## Why AWS

Three reasons. First, **the GPU path**: scaling from CPU to GPU inference on AWS is an instance-type change on the same EBS volume — no data migration, no re-architecture. Budget providers (Hetzner et al.) are 4–6x cheaper for CPU but have no comparable GPU story, so choosing them now would mean a provider migration later, precisely when the system is busiest. Second, **regional compliance**: af-south-1 (Cape Town) keeps data on-continent, which most African data-protection frameworks (including Kenya's DPA) treat far more favorably than EU/US hosting. Third, **managed growth path**: RDS, ECS, and ALB let the architecture scale by promotion rather than rewrite (see "Future scaling" below). The premium over budget hosting is the explicit price of scalability — accepted deliberately, not overlooked.

## Why a single EC2 + Docker Compose instead of ECS/EKS from day one

The team's stated comfort zone, and the honest match for the workload. Fifty internal users generate a load that one instance absorbs trivially; Kubernetes or ECS would add orchestration complexity, cost, and failure modes with zero benefit at this scale. Compose also preserves dev/prod parity — the same file structure runs locally. Critically, this is not a dead end: the Compose service boundaries (UI / API / DB / inference) are exactly the seams along which the system later splits onto RDS + ECS + a GPU node. We are deferring complexity, not accruing architectural debt.

## Why `m7i.2xlarge` (CPU) at launch, GPU later

llama3.2 is a 3B-parameter model — small enough that 8 modern vCPUs answer in ~5–20 seconds, which internal users on a non-streaming endpoint tolerate. Starting on GPU would roughly double cost from day one to solve a latency problem that may never materialize at this usage level. Because the GPU move is a stop-and-resize operation, we can make the decision **when evidence of demand exists** instead of speculatively. `OLLAMA_KEEP_ALIVE=-1` is set because the default unloads the model after idle periods, which would add a 10–30 s cold start to the first query of every session — the cheapest latency win available.

## Why username/password auth instead of VPN

A VPN (Tailscale) would be the smaller attack surface, but it pushes friction onto every user: client installation, key management, onboarding support. For a mixed internal audience, credential login on a hardened HTTPS endpoint is the pragmatic balance — provided it is done properly, which is why the plan mandates bcrypt/argon2 hashing, login rate-limiting, HTTPS-only cookies, and admin-created accounts (no self-signup). A **single `users` table** backs both Chainlit and Next.js so there is one credential store to secure, audit, and offboard from — duplicate account systems drift and become the weak link.

## Why FastAPI verifies a signed JWT on every call

Without it, the architecture is two locked front doors and an unlocked back door: anyone who discovers the API host could query the document corpus directly, bypassing both UIs' logins. Service-to-service verification (shared-secret JWT) ensures the authentication boundary covers the data, not just the interfaces. This is the difference between access control as a UI feature and access control as a security property.

## Why 443-only + SSM Session Manager (no SSH port)

Every open port is standing risk; an exposed port 22 attracts constant credential-stuffing within hours of provisioning. SSM Session Manager provides shell access through AWS's control plane with IAM authentication and CloudTrail audit logs — strictly better than SSH keys for both security and the compliance audit trail. The same mechanism (SSM Run Command) then powers deploys, which is why CI needs **no SSH keys and no long-lived AWS credentials** (GitHub OIDC assumes a role instead). Leaked CI credentials are one of the most common real-world breach vectors; OIDC eliminates the credential to leak.

## Why GitHub Actions with SHA-tagged images

The team already lives in GitHub; introducing a separate CI system adds surface without benefit. Immutable SHA tags make every deploy reproducible and make rollback a one-line redeploy of a known-good tag — no "what was running yesterday?" archaeology. Postgres and Ollama are version-pinned because `latest` turns routine deploys into surprise database or runtime upgrades; infrastructure versions should change only when deliberately chosen and tested.

## Why secrets live in SSM Parameter Store, not the repo or CI

Secrets in a repo are permanently in git history; secrets held only in CI are invisible to the running host and unauditable. Parameter Store (SecureString) gives KMS encryption, IAM-scoped access, and change history for the DB password, JWT secret, and `CHAINLIT_AUTH_SECRET` — and keeps rotation a config change rather than a code change.

## Why backups target both `pg_dump`→S3 and EBS snapshots

They fail differently. Snapshots restore a whole machine fast but can capture a corrupted database mid-write; logical dumps are consistent and portable (they restore into RDS later) but rebuild slower. Together they cover machine loss, data corruption, and accidental deletion. The corpus embeddings are technically re-derivable by re-running ingestion, but at hours of compute once the corpus is large — hence the database is treated as the primary asset. The checklist's "test a restore once" exists because an untested backup is a hope, not a plan.

## Why the HNSW index now rather than later

pgvector without an index scans every embedding per query — fine at thousands of chunks, degrading linearly after that. Building HNSW on a small table takes seconds; building it later on a large, live table locks and crawls. Creating it early costs nothing and removes a future incident.

## Why per-container memory limits

Ollama's memory use spikes during inference. Unbounded, a spike triggers the kernel OOM killer, which chooses its victim by size — frequently Postgres. Limits convert "database dies under load" into "one slow inference request fails," which is the correct failure to have.

## Why Uptime Kuma + CloudWatch instead of a full observability stack

Prometheus/Grafana/Loki is a system to run, tune, and secure — disproportionate for one VM and 50 users. Health-endpoint polling with alerting plus CloudWatch's host metrics answers the two questions that matter at this scale: *is it up, and is the machine running out of something?* The `/health` endpoint checking both Postgres and Ollama (built in the API phase) is what makes this cheap monitoring meaningful.

## Why the future-scaling section exists at all

To demonstrate the single-VM choice is a starting point with an exit, not a ceiling. Postgres promotes to RDS (pgvector supported), stateless containers move to ECS, and inference gets a dedicated GPU node — each along boundaries the Compose file already draws. The plan optimizes for today's reality while keeping tomorrow's growth a promotion exercise rather than a rewrite.
