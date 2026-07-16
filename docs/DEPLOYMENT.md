# Production Deployment Plan

Internal RAG application. Self-hosted LLM is a hard requirement for data privacy — no document content may reach third-party AI providers. Deployed on **AWS** for scalability and a clear path to GPU inference. Access is controlled via **username/password authentication** (no VPN).

## Stack

| Service | Role |
|---|---|
| `nextjs` | PDF upload UI |
| `fastapi` | Ingestion pipeline + `/api/query` RAG endpoint |
| `chainlit` | Chat UI (`chat.py`, calls FastAPI over HTTP) |
| `postgres` | `pgvector/pgvector:pg16` — chunks + embeddings (all-minilm, 384-dim, HNSW index) |
| `ollama` | `all-minilm` (embeddings) + `llama3.2` (generation), `OLLAMA_KEEP_ALIVE=-1` |
| `caddy` | Reverse proxy, automatic TLS — the only container exposing ports |

## Architecture (AWS)

Single **EC2 instance** running Docker Compose, in a VPC with a security group allowing inbound **443 only** (SSH via AWS SSM Session Manager — no open port 22). All services communicate on an internal Docker network; Postgres and Ollama are never publicly reachable. EBS `gp3` volume (150 GB+) with persistent Docker volumes for Postgres data, uploaded PDFs, and `/root/.ollama`.

- **Launch instance:** `m7i.2xlarge` (8 vCPU, 32 GB) — llama3.2 (3B) on CPU, ~5–20 s per answer
- **GPU scaling path:** stop instance → change type to `g5.xlarge` / `g4dn.xlarge` (NVIDIA GPU) → install NVIDIA container toolkit → add GPU device reservation to the `ollama` service in Compose. Same EBS volume, same data, no re-architecture. Reserve/Savings Plan once the type stabilizes.
- **Region:** af-south-1 (Cape Town) keeps data on-continent; use eu-west-1 only if latency/instance availability demands it and compliance allows.

## Access Control (username / password)

- **All three UIs sit behind authentication** — nothing is served anonymously.
- **Chainlit:** built-in `@cl.password_auth_callback` validating against a `users` table in Postgres (bcrypt/argon2 hashes). Set `CHAINLIT_AUTH_SECRET`.
- **Next.js (upload):** Auth.js (NextAuth) Credentials provider against the **same** `users` table — one credential store, no duplicate accounts.
- **FastAPI:** never trusts callers blindly — Chainlit/Next.js attach a signed token (JWT, shared secret via env) on every backend call; `/api/query` and ingestion routes verify it.
- Enforce strong password policy, hash with bcrypt/argon2, rate-limit login attempts (Caddy or app-level), HTTPS-only cookies.
- Admin creates accounts (internal tool — no self-signup).

## CI/CD (GitHub Actions → AWS)

1. Push to `master` through pull requests → matrix build of the three custom images (Next.js, FastAPI, Chainlit).
2. Tag with git SHA + `latest`, push to **Amazon ECR** (auth via GitHub OIDC role — no long-lived AWS keys).
3. Deploy job runs `docker compose pull && docker compose up -d` on the instance via **SSM Run Command** (no SSH keys in CI).
4. **Rollback** = redeploy the previous SHA tag.

Postgres and Ollama images are version-pinned. Secrets: GitHub OIDC + Actions secrets for CI; runtime secrets (DB password, JWT secret, `CHAINLIT_AUTH_SECRET`) in **AWS SSM Parameter Store (SecureString)**, pulled into `.env` at deploy. Every service has a Compose `healthcheck`.

## Infrastructure Checklist

- [ ] Nightly `pg_dump` to **S3** (versioned bucket, lifecycle policy) + PDF volume sync; **test a restore once**
- [ ] Daily EBS snapshots via Data Lifecycle Manager (7-day retention)
- [ ] HNSW index on `chunks.embedding` before the corpus grows large
- [ ] Per-container memory limits (Ollama must not OOM-kill Postgres)
- [ ] Elastic IP + Route 53 record; Caddy auto-TLS on the domain
- [ ] CloudWatch agent (CPU/mem/disk alarms) + Uptime Kuma polling `/health` endpoints
- [ ] Security group: 443 only; SSM Session Manager instead of SSH; unattended OS security updates
- [ ] Login rate-limiting verified; password hashes are bcrypt/argon2 (never plaintext)
- [ ] Monthly base-image version bumps


## Future Scaling (beyond one VM)

If usage outgrows a single instance: we move Postgres to **RDS for PostgreSQL** (pgvector supported), run the app containers on **ECS**, and give Ollama a dedicated GPU instance behind an internal ALB. The Compose service boundaries map 1:1 onto that split — nothing needs rewriting.
