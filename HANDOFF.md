# Infrastructure migration implementation handoff

Prepared 2026-10-05. This document records the user's agreed target and implementation sequence. It supersedes the initial proposal to reproduce the old `core/internum/externum` layout. (At the time of writing implementation had not started; see "Current state and next steps" below for where things stand.)

## Current state and next steps (updated 2026-10-07, read this first)

The sections after this one are the original plan (2026-10-05) and a dated progress log. This section is the summary.

### What runs where now

| Machine | Guest | ID / address | What | Managed by |
|---|---|---|---|---|
| kestrel (10.1.0.2) | dns1 (LXC, Alpine) | 2054 / 10.20.0.54 | Technitium primary, Arcane agent | stages 3–5 |
| kestrel | zoltan (LXC, Alpine) | 2010 / 10.20.0.10 | Caddy (`*.lab.wsiwiec.com` wildcard via Cloudflare DNS), Arcane v2.15.0 manager at https://arcane.lab.wsiwiec.com, CLIProxyAPI at https://cliproxy.lab.wsiwiec.com | stages 3–5 |
| kestrel | pdm (LXC, Debian 13) | 2011 / 10.20.0.11 | Proxmox Datacenter Manager 1.1.7 at https://pdm.lab.wsiwiec.com through Caddy; kestrel and torus reachable | stages 2–5 + network |
| torus (10.1.0.30) | dns2 (LXC, Alpine) | 2055 / 10.20.0.55 | Technitium secondary, Arcane agent | stages 3–5 |
| torus | engi (LXC, Alpine) | 2020 / 10.20.0.20 | Arcane agent (later S3) | stages 3–5 |
| torus | nas (VM, Debian 13 "generic") | 2040 / 10.20.0.40 | OpenMediaVault 8; USB HDD W380WY6S passed through (mapping nas-hdd), ext4 mounted; SMB share `wojtek` (user wojtek) | stages 2–5 |
| torus | komoda 101, tailscale-box 105, internum 201, externum 301 | old | old apps incl. live Research Cruise staging (externum); HyperDX and Uptime Kuma on externum stopped (disk wear) | not managed; retire in step 7 |

Secrets: `secrets/services.sops.yaml` (Arcane, Technitium, Cloudflare token, nas_admin/root/user passwords), `secrets/tofu.sops.yaml`, `secrets/fleet-ssh-key.sops.yaml`, per-host root passwords. All commands need the YubiKey (owner runs them; the agent cannot reach the machines).

### Done
- Step 1 (stage 1–2 safety fixes), step 2 for Arcane (HTTPS through Caddy; router stays `allow_insecure`, owner's choice), step 3 (disk inspection; Research Cruise backup `ResearchCruiseApp-20261005-2234Z.bak` on both backup disks, test-restored), step 4 (zoltan/engi, Arcane on zoltan, OMV VM `nas`), step 5 chunk 1 (OMV data disk, user/share `wojtek`).
- PDM in a Debian LXC, PDM and OMV HTTPS web routes through Caddy with pinned backend certificates, CLIProxyAPI, Arcane v2.15.0 and CPU reporting fixes: deployed; combined in commit `8e20bcf`. Services re-run changed=0; PDM/OMV routes verified from the laptop.
- PDM router access fixed 2026-10-07: UniFi allows only inventory `api_from` (currently pdm, 10.20.0.11) to the Proxmox machines (10.1.0.2, 10.1.0.30) on TCP 8006, with return traffic. Owner applied exactly 1 added / 0 changed / 0 destroyed. Their dashboard screenshot confirms all remotes reachable, 2 nodes online, 1 VM and 9 LXCs running. Guest power operations and cross-node migration were not tested.
- Tools: `mise run inspect-storage` (read-only disk/health/wear report), `mise run research-cruise-backup` (tested DB backup), `scripts/tofu-apply.sh` behind `mise run guests|network` (destroying plans need `destroy <n>`; new VMs' old host keys are forgotten).

### Dropped / deferred (owner, 2026-10-06)
- **Proxmox Backup Server and Proxmox guest backups: dropped.** Guests are rebuildable from this repo; only Arcane's data matters, and Arcane will back up to S3 later. **Cleaned up 2026-10-06:** VM pbs destroyed, DNS record removed, OMV NFS export + NFS service + shared folder pbs-store deleted (one-off playbook, run and deleted), no storage/job had been created on the hosts, secrets `pbs_tokens`/`pbs_root_password` unset.
- Research Cruise nightly DB backup, alerts/notifications, off-site copy: unresolved, later.

### Next
1. **Arcane GitOps:** short plan before implementation; read-only deploy key, repository connections, per-environment stacks and secrets, then verify a harmless sync using the installed version's semantics.
2. Migrate retained apps from komoda-homelab (step 6), then Research Cruise staging onto zoltan, preserving data and rollback.
3. Arcane backup to S3 (implementation and storage mount still to choose), with a tested restore. Research Cruise scheduled backups and an independent off-site copy remain unresolved.
4. Retire the old guests (step 7) only after migration, replacement health and recovery are verified; decide what happens to tailscale-box and excluded-app data first.

PDM connectivity is complete. Its role includes audit, guest power management and migration privileges, but cross-node remote migration needs broader permissions and remains a later task; dashboard health does not verify it.

### Lessons (do not repeat)
- Proxmox ACLs: a grant on a deeper path **replaces** the inherited one for that path; repeat every needed privilege. Never approve a plan that differs from the expected one.
- Plays must target exact hosts/groups (`hosts: vms` ran OMV setup on a second VM).
- Bash reads scripts while running: don't edit a script the owner is running.
- Long jobs: check Ansible's async limit against the real duration (PBS datastore over NFS ≈ 1 h).

## Starting point

- Working repository: `/home/wojtek/Projects/infra-as-script`, private GitHub repository `VV01T3K/infra-as-script`.
- Inspected HEAD: `main` at `c07dd59`. The user reports GitHub matches it, `new-layout` was deleted, and `old-layout` preserves the previous implementation. Recheck Git status before editing. An existing untracked `report.log` belongs to the user; leave it alone.
- Application reference: `VV01T3K/komoda-homelab`, inspected `main` at `2cb9b50`. A temporary checkout exists at `/tmp/komoda-review.Yfqht2/repo`; fetch a fresh checkout if missing or stale.
- Research Cruise is a separate repository. A local directory exists at `/home/wojtek/Projects/ResearchCruiseApp`; inspect its instructions, status and remote before working there. Its deployment was not inspected in this conversation.
- Evidence so far describes repository configuration, not verified live server state. No database backup, disk contents, tunnel configuration or service health has been verified remotely.

## Agreed target

```text
kestrel — Proxmox, 10.1.0.2
├── dns1 LXC, 10.20.0.54                 keep existing guest and configuration
│   └── Technitium in Docker
└── Main Alpine Docker LXC              name/IP/resources to choose
    ├── Arcane manager/dashboard
    ├── Caddy + certificate-storage Valkey
    ├── Cloudflared
    ├── CrowdSec
    ├── CloudBeaver
    ├── Frog keepalive
    └── Research Cruise staging + database
        deployed from the separate Research Cruise repository

torus — Proxmox, 10.1.0.30
├── dns2 LXC, 10.20.0.55                 keep existing guest and configuration
│   └── Technitium in Docker
├── Main Alpine Docker LXC              name/IP/resources to choose
│   ├── Arcane agent
│   └── Future S3-compatible service, managed through Arcane
└── OpenMediaVault VM
    ├── OS disk on internal storage
    └── Newly connected external HDD for shares and backups
```

Keep DNS exactly as deployed: dedicated LXCs, with Docker inside. The user explicitly reversed the earlier DNS consolidation idea. Existing Arcane agents on DNS guests may need their manager URL/TLS trust updated, but this is not a DNS redesign.

Move the Arcane dashboard into kestrel's main Docker LXC. Retire its separate guest only after state migration and agent reconnection are verified. Applications are concentrated on kestrel initially; automatic application failover is outside scope. Prefer FTL race names for the new Docker guests, consistent with the original naming preference.

### Application selection

Retain Caddy, Cloudflared, CrowdSec, CloudBeaver, Frog keepalive, and the Valkey required by the retained Caddy configuration. Keep Caddy during this migration.

Exclude Homepage, Gitea and its runner, n8n and its runners, Qdrant, Open WebUI, llama, both Uptime Kuma deployments, Excalidraw, IT-Tools, Beszel, HyperDX/ClickStack, Authelia and its dedicated Valkey. Exclusion means no new deployment; preserve existing data during migration. Old AdGuard/Unbound and Komodo are superseded by Technitium and Arcane.

Remove Authelia forward-auth, snippets and dependencies from the retained proxy configuration. Routes that previously depended on Authelia, especially CloudBeaver, must remain private until replacement access controls exist. A hostname containing `lab` is not itself an access restriction. Preserve intentional public app/tunnel routing separately.

Traefik and Pangolin are deferred. The eventual Traefik change needs a feature comparison against the actual Caddy setup, including certificate coordination, CrowdSec and response rewriting.

### Storage decisions

- One external HDD is currently connected to torus, according to the user. Its identity, contents, filesystem and health are unknown.
- OMV runs in a separate VM. Its installation documentation excludes LXC/container installation: https://docs.openmediavault.org/en/8.x/installation/.
- Pass the identified data disk to OMV with stable device identity and exclusive ownership. Keep the VM OS disk on internal storage. Proxmox and OMV must not mount the same data filesystem concurrently.
- Keep AirDisk in its existing torus backup role during migration. Inventory identifies serial `QA7202W000653P1109`; model, interface, capacity and health remain unverified. No SSD caching or repurposing now.
- Kestrel's existing backup disk is recorded as serial `S32XJ9AH421216`, Seagate 1 TB. The user expects the Research Cruise database backup there. Treat that as a lead, not evidence that a usable backup exists.
- Keep the live Research Cruise database on kestrel's internal storage; send backups to torus. Confirm database size and available capacity first.
- Start with one HDD, without RAID. A second HDD, redundancy arrangement, and an independent backup destination are later decisions. OMV advises against production RAID over USB: https://docs.openmediavault.org/en/latest/administration/storage/raid.html.
- The future S3 service belongs in torus's Docker LXC under Arcane. OMV owns its backing disks. Choose the S3 implementation before choosing its storage mount; support for network filesystems varies. S3 setup is deferred.

## Implementation sequence and completion checks

### 1. Fix destructive storage handling and access reconciliation

The user supplied an automated review. Its five code conditions were independently confirmed by source inspection; its claimed tests have not been rerun. Implement focused fixes before broad provisioning runs.

| Finding | Location | Required result |
|---|---|---|
| Missing Proxmox storage entry can trigger wiping a disk that already contains backups; torus permanently has `wipe: true` | `stages/2-host/main.yml`, backup-disk block; `inventory/hosts.yml` | Normal setup discovers and mounts existing storage without formatting. Destructive initialization is a separate explicit operation bound to exact disk identity. An existing filesystem is never erased by an ordinary rerun or host reinstall recovery. |
| Firewall only sets `policy_in DROP` when disabled | `stages/2-host/main.yml`, firewall block | Reconcile and verify enablement and policy independently. Include policy changes in rollback handling and fresh-connection checks. |
| Any SSH key commented `root@...` survives retirement | `stages/1-access/main.yml`, key reconciliation | Preserve the actual Proxmox-owned key material and repo-authorized keys. Remove retired keys regardless of comment, accounting for actual host/cluster key ownership. |

Completion: targeted regression checks reproduce the old failures and pass with the fixes, including missing storage metadata with an existing filesystem, enabled firewall with ACCEPT policy, and an unauthorized `root@old-laptop` key. Inspect the resulting diff and verify idempotent reruns. Perform destructive-path tests against disposable fixtures, never backup disks.

### 2. Secure management connections

- Arcane currently publishes HTTP and agents use HTTP/WebSocket. Add verified HTTPS for browser and agent connections before supplying Git/application credentials. Consult the installed version and native TLS documentation: https://getarcane.app/docs/networking/tls. Update all affected API callers, URLs and trust configuration. Keep manager bootstrap independent of application GitOps.
- UniFi's provider in `network/main.tf` uses an IP URL and `allow_insecure = true`; its comment says the certificate is for `unifi.local`. Establish a trusted certificate and matching connection hostname, then remove insecure verification. Confirm the provider's supported trust mechanism.

Completion: intended clients successfully connect with certificate verification enabled; wrong/untrusted certificates are rejected. Agents reconnect and the management workflow still works.

The broad Personal-network administration policy and desk-port VLAN trunk were flagged for review, not approved for automatic restriction. Inspect current usage before changing either. Preserve working administrator access.

### 3. Inspect disks and recoverability

Identify disks by serial, capacity, transport, filesystem, mount use and health. Distinguish the new HDD from AirDisk and kestrel's backup disk. Locate the Research Cruise backup, determine its format/date/database engine version, preserve the original, and test a restore into isolated temporary storage. Avoid starting duplicate application workers or external integrations during restore tests.

Completion: record exact disk assignments and a verified restore result. If the backup is absent or unusable, report that specifically and preserve the old environment while locating another source. Formatting or erasing existing data requires explicit authorization for the identified disk; the plan alone is not that authorization.

### 4. Provision the new Docker hosts and move Arcane

Extend the inventory and existing stages, keeping the working DNS guests. Stage 3 currently treats every member of `guests` as an Alpine LXC and stage 4 uses `pct` plus Alpine commands. Model the OMV VM separately so it is not processed as an LXC. Choose new guest IDs, IPs and resource allocations from available capacity.

Preserve Arcane's data and encryption key when moving the manager; reconcile environment registrations and agents without losing their state. Retain old guests through cutover. Removing a guest from inventory currently destroys its managed resource, so inspect every OpenTofu plan before applying.

Completion: both new Docker LXCs boot reliably; Arcane manages its local environment and intended remote environments; existing DNS still resolves through both nodes. Plans contain no unintended DNS replacement or old-guest destruction.

### 5. Configure GitOps and storage/backup automation

Ansible generates/preserves a read-only GitHub deploy key, stores the private half through SOPS, registers the public half with the appropriate repository, and configures Arcane through its supported API. Declare repository connections, per-environment stack mappings and secret variables in code. Confirm the installed Arcane version's GitOps semantics rather than assuming every push immediately deploys. Plan separate repository access for Research Cruise; verify GitHub deploy-key reuse restrictions.

Provision OMV using the disk assignments established above. Configure required shares and backups with explicit schedules, retention, failure reporting and tested restores. Include database-consistent Research Cruise backups in its migration. Preserve enough recovery material outside the OMV VM to rebuild access to its disks. A further independent copy needs a destination beyond torus; record it as unresolved if unavailable.

Completion: Arcane can fetch the intended private repositories without write permission; a harmless stack change syncs as intended. Backup jobs produce usable artifacts and a test restore succeeds. Document actual recovery steps, not just storage creation.

### 6. Migrate retained apps, then Research Cruise staging

Migrate applications with their volumes/bind-mounted data and validate them individually. `komoda-homelab` is a source of app definitions, not a topology to reproduce:

- Existing Caddy stacks reuse container names and ports 80/443. Consolidate their routes into kestrel's proxy configuration.
- Caddy uses Docker labels, Cloudflare DNS wildcard certificates, Valkey-backed certificate storage, CrowdSec and custom response-rewrite snippets. The build includes more modules than basic proxying. Keep only behaviour needed by retained apps.
- Cloudflared uses a token and the `cloudflare` Docker network; hostname/origin mappings are not declared in its Compose file. Inspect remote tunnel configuration and verify each retained route at cutover.
- CloudBeaver references SQL Server host `researchcruiseapp-db`, database `ResearchCruiseApp`, and external network `researchcruiseapp-network`. This is a clue to the old deployment, not verification of the live database or backup.
- Data is split between Docker volumes and local bind mounts. Copying Compose files alone does not migrate it.

Research Cruise code and Compose remain in its own repository. Inspect its deployment workflow and configuration, restore its database, and verify staging behaviour before switching the deployment target and relevant URLs/secrets. Reconcile CloudBeaver connectivity and any old telemetry dependencies, since HyperDX is excluded. Preserve rollback until the new environment and backup process are proven.

Completion: retained app routes and tunnel origins work with intended access restrictions; Research Cruise staging passes application checks against the restored database; a subsequent deployment from its own repository reaches the new staging environment successfully.

### 7. Retire replaced infrastructure

Retire the separate Arcane guest and old `komoda`, `internum`, `externum` guests only after confirming their actual host placement, retained data, replacement health and recovery paths. Verify live placement instead of relying on old README addresses. Excluded-app data needs an explicit retention/deletion decision before destroying its last copy.

## Proposed repository shape

Adapt names to existing conventions; these are intended responsibilities, not a requirement to create empty scaffolding.

```text
infra-as-script/
├── HANDOFF.md
├── inventory/hosts.yml
├── network/
├── stages/
│   ├── 0-install/
│   ├── 1-access/
│   ├── 2-host/
│   ├── 3-guests/                 # LXC and separate VM provisioning
│   ├── 4-setup/
│   └── 5-services/               # DNS, Arcane, GitOps, storage/backup setup
├── services/
│   └── <kestrel-lxc>/
│       ├── caddy/                # Compose, Dockerfile, needed snippets, Valkey
│       ├── cloudflared/
│       ├── crowdsec/
│       ├── cloudbeaver/
│       └── frog-keepalive/
├── secrets/*.sops.yaml
├── keys/
└── scripts/

ResearchCruiseApp/                # Separate repo; existing deployment files
```

Each retained app gets its own directory and `compose.yaml`, with accompanying configuration where needed. Runtime data stays outside Git. Add `services/<torus-lxc>/<s3-service>/` only when implementing S3 later.

## Validation and reporting

Use the current `mise.toml` commands and secret wrappers. `mise run check` currently runs Ansible lint and OpenTofu formatting checks, not full validation or behavioural tests. Also validate both OpenTofu roots, check changed shell scripts, validate rendered Compose without exposing secrets, and run targeted regression checks for the fixes. The user's review reports earlier validation success; rerun relevant checks for the implementation.

SOPS uses hardware-backed recipients and operational commands may require YubiKey interaction. Keep plaintext credentials out of logs and committed files. Preserve encrypted state/plan enforcement, verified Proxmox TLS, temporary SSH agents and the no-SSH-server LXC management model.

Record completed phases, actual guest/disk assignments, tests run, live cutovers and unresolved items as work progresses. Distinguish code implemented from live deployment verified. The user prefers routine reversible work to proceed without repeated permission requests; reserve questions for missing facts and genuinely destructive actions. This handoff was the only requested artifact in the authoring turn; it does not claim any live changes have happened.

## Progress

### Step 1 — DONE 2026-10-05, commit `752f034` (not pushed)

- `stages/2-host/main.yml` backup disk: the `wipe` flag is gone (also from `inventory/hosts.yml`). With the storage `backup` missing, a disk holding exactly one Linux filesystem (ext2/3/4, xfs, btrfs; on the disk or a partition) is mounted as it is; anything else stops with a description of the contents and changes nothing. Disk found by exact serial match from `lsblk --json` (the old substring match is gone). Erasing is only `-e initialize_backup_disk=<serial>`, which must equal the inventory serial, needs the storage to be absent and nothing on the disk mounted.
- `stages/2-host/main.yml` firewall: `enable` and `policy_in` are checked on their own (policy must be explicitly `DROP`); either one being wrong arms the undo timer and is fixed. After the timer is stopped, a fresh read of the options must show enable=1, policy_in=DROP (a failure there stops the run, but the firewall stays on).
- `stages/1-access/main.yml` keys: keeps keys whose data is in `keys/*.pub` or this host's `/root/.ssh/id_*.pub`; the `root@*` comment exception is gone. Lines with options are matched on any field. Stops without changes if the host is in a Proxmox cluster (`/etc/pve/corosync.conf`) or has no own root key.
- Regression checks (throwaway harness in `/tmp/p1test`, runs the real task text from old commit vs new code on localhost with fake command output; nothing ran against disks or hosts): old code wiped the AirDisk-like fixture when the storage entry was missing, new code mounts it (correct UUID even with a look-alike serial); empty disk, two filesystems, LVM, partition table without filesystem, missing serial, wrong/blocked initialize all stop with nothing changed; initialize with the right serial runs wipe+format. Firewall: old code ignored enabled+ACCEPT, new code fixes it (also for unset policy); correct settings → no changes. Keys: old code kept `root@old-laptop` and a stale `root@torus`, new code removes both and keeps fleet, YubiKey, own key; re-run unchanged. `mise run check` and `--syntax-check` pass.
- Live runs 2026-10-05 from the Personal network: `mise run host torus|kestrel --tags firewall,backup-disk` → changed=0 on both (firewall already on/DROP, the new final check passed; storage `backup` exists so the disk part was skipped). `mise run access torus|kestrel --tags retire` → key step unchanged on both (each host's own root key matches its authorized entry; no retired keys present); only the local marker `secrets/<m>/stage-1.done` was rewritten.

### Open items found along the way

- **Remote admin over Tailscale doesn't work, by design of stage 2's firewall.** Away from home, traffic to 10.1.0.x goes through `tailscale-box` (CT 105 on torus, subnet router for 10.0.0.0/24, 10.1.0.0/24, 10.20.0.0/24), which forwards it from its own Infra address; that address isn't in `admin_from`, so SSH/8006 time out. Run repo commands from the Personal network. Allowing remote admin would mean adding tailscale-box's single address to the admin list (gives every tailnet device admin reach); undecided.
- **`tailscale-box` is not in the agreed target.** Decide keep/move/replace before step 7 retires the old guests on torus.
- **Step 2 revised (owner's suggestion, 2026-10-05):** Arcane HTTPS goes through Caddy (Cloudflare DNS wildcard cert for `*.lab.wsiwiec.com`; agents use `https://arcane.lab.wsiwiec.com`, WebSocket via Caddy). Conditions: Caddy and Arcane in the same LXC (plain HTTP hop stays inside the guest), Arcane no longer publishes 3552, Caddy + its Valkey deployed by stage 5 (Ansible), not by Arcane GitOps. So this merges into step 4. The router is NOT put behind Caddy (circular dependency, and Caddy would face the same `unifi.local` cert); checked 2026-10-05: the provider (filipowm/unifi 1.1.0) has no CA option, only `allow_insecure`; UniFi OS 4.1+ accepts uploaded certificates (UI: Control Plane → Console → Certificates, plus an API used by tools like unifi-cert). **Owner decided: keep `allow_insecure = true` for now (unresolved, accepted).** Options for later: own name-constrained CA with an IP-SAN cert uploaded once + SSL_CERT_FILE for `mise run network`, or Let's Encrypt with automated upload (needs a console-level router account).
- **Names (owner, 2026-10-05):** kestrel's main Docker LXC = `zoltan`, torus's = `engi`.

### Step 4 (part 1: zoltan, engi, Caddy, Arcane move) — DONE 2026-10-05, commit `f90bba3` (not pushed)

- Inventory: `zoltan` (kestrel, 2010, 10.20.0.10, 4 cores / 8 GB / 100 GB) and `engi` (torus, 2020, 10.20.0.20, 2 cores / 2 GB / 16 GB); groups `proxy` and `arcane_manager` = zoltan; `arcane_host: arcane.lab.wsiwiec.com`. The old guest `arcane` stays listed (deleting it from the inventory would destroy it) until step 7.
- Stage 4 also installs `docker-cli-buildx` (compose needs it to build Caddy's image).
- Stage 5 part `proxy` (zoltan): Caddy 2.11.6 built with caddy-docker-proxy v2.13.1 + caddy-dns/cloudflare v0.2.4 (image `local/caddy:<versions>`), base `Caddyfile` with the `*.lab.wsiwiec.com` wildcard via Cloudflare DNS; routes from Docker labels on network `caddy`. **No Valkey** (owner agreed: one Caddy, certificates in a volume). Caddy 2.11 has no `auto_https prefer_wildcard` any more; subdomains under a managed wildcard use it by default (verified: only the wildcard is ordered). `-e caddy_acme_staging=true` switches to Let's Encrypt staging. Needs `cloudflare_api_token` in `secrets/services.sops.yaml` (owner chose to reuse the old Caddy token; roll it in Cloudflare at step 7).
- Arcane manager on zoltan: port only on 127.0.0.1, APP_URL `https://arcane.lab.wsiwiec.com`, Caddy labels. One-time move (temporary tasks in the Arcane play, delete in step 7): on kestrel via `pct exec`, stop the old Arcane (stays stopped, rollback), copy volume `arcane_data` + `/opt/arcane/projects` into zoltan, compare sha256 of every file, then write marker `/opt/arcane/.moved-from-arcane`; without the marker a re-run redoes the copy. Agents (all guests except zoltan and the old `arcane`): `MANAGER_API_URL=https://arcane.lab.wsiwiec.com`, name pinned by `extra_hosts` (guests use the router's DNS). Arcane v2.14.0 agents verify TLS with system roots (source checked). Technitium: `arcane` → zoltan, plus `zoltan`, `engi`.
- Offline checks: lint, syntax, `tofu validate`; templates rendered with fake secrets; compose files pass `docker compose config`; Caddy image built locally with podman (modules present), Caddyfile `caddy validate` with networking off; move script run against two Alpine containers through a fake `pct` (stale volume replaced, owner/mode kept, marker written, tampered copy detected). **Incident:** one local Caddy test reached production Let's Encrypt for ~25 s (1 account, 1 order for the wildcard, no certificate, no validation attempted since the fake token was rejected by Cloudflare) — no effect on issuance limits; local tests since then never contact ACME, and the first live run uses staging.
- Live 2026-10-05: `mise run guests` = 2 to add, 0 change, 0 destroy (zoltan 2010, engi 2020 created); `mise run setup zoltan|engi` OK (engi's first attempt failed only because the owner's VPN cut the home network: community.proxmox 2.0.0 then raises the `_raise_paramiko_connect_exception` AttributeError instead of a connection error). `mise run services --tags proxy …` built Caddy and got the wildcard certificate; `mise run services`: Arcane data moved (7 files, checksums identical, old Arcane stopped), Arcane up on zoltan, admin login OK, environment created for engi only (dns1/dns2 kept theirs), agents on dns1/dns2/engi redeployed with the HTTPS URL, Technitium: arcane → 10.20.0.10, zoltan, engi added, old arcane → .60 removed.
- Checked from the laptop: `https://arcane.lab.wsiwiec.com` 200 with a verified certificate (`*.lab.wsiwiec.com`, Let's Encrypt YE2, valid to 2027-01-03), http → 308 https, unrouted names closed, 10.20.0.10:3552 and 10.20.0.60:3552 closed, names resolve.
- **Bug found and fixed (mise.toml):** tasks forwarding `[ansible_args]...` passed them shell-quoted, so `-e caddy_acme_staging=true` reached Ansible as `'caddy_acme_staging=true'` and was ignored → the "staging" run actually got the one production certificate (fine: one issued certificate, nothing failed). `install`, `access`, `host`, `services` now run through `eval`; verified with the real task definition that `-e initialize_backup_disk=<serial>` arrives intact (the step 1 erase command was affected too; it would only have failed safely).
- Re-run of `mise run services`: changed=0 everywhere. Owner's dashboard screenshot: dns1, dns2, engi online (heartbeat now), manager at https://arcane.lab.wsiwiec.com, UI in English.
- **Arcane preferences in code (owner, 2026-10-05), run and visible in the UI, commit after `f90bba3`:** user `arcane` locale `en` + timeFormat `24h` (PUT /api/users/{id}); global settings `enableGravatar=false`, `autoUpdate=false` (PUT /api/environments/0/settings); `ANALYTICS_DISABLED=true` in the compose file (no heartbeat to checkin.getarcane.app). Values live in the Arcane play's vars; a re-run sets UI changes back. Comparison tested with fake API answers. Arcane's UI language otherwise comes from a cookie, then the browser; the user's locale is applied at login.

### Step 3 — DONE 2026-10-06 (commit `22bfa2b`)

`mise run inspect-storage` (operations/inspect-storage.yml, read only) found:

| Machine | Disk | Model | Serial | Bus | SMART | Use |
|---|---|---|---|---|---|---|
| torus | sda 1 TB | Seagate ST1000LM014 SSHD | `W380WY6S` | USB | PASSED, 16,741 h, 0/0/0 bad sectors | **new HDD** for OMV; no partitions/filesystem seen by lsblk (wipefs check added, not run yet) |
| torus | nvme0n1 256 GB | AirDisk | `QA7202W000653P1109` | NVMe | PASSED, 11 h, 0% used, 54 °C | storage `backup` (18%: the 4 move archives of 2026-10-04) |
| torus | nvme1n1 256 GB | Samsung PM981 | `S425NA0M403712` | NVMe | PASSED, 1% used | system; local-lvm 80% full (old guests) |
| kestrel | sda 1 TB | ST1000LM024 HN-M101MBB | `S32XJ9AH421216` | USB | PASSED, 16,241 h, 0/0/0 | storage `backup` (15%, 135 GB of archives, 770 GB free) |
| kestrel | nvme0n1 512 GB | Lexar NM620 | `QDK662R021245P112W` | NVMe | PASSED, **16% used after 1,710 h** | system; cause unknown (likely the old write-heavy guests); inspection now also shows total TB written and GB/day since boot |

Research Cruise: live on externum (CT 301, torus), DB container + staging backend/frontend running; SQL Server 2022 CU23 16.0.4236.2; `ResearchCruiseApp.mdf` 72 MB, log written today. **No native backup exists** (no .bak/.bacpac anywhere; the Komodo `xbackup/xrestore-cruisedb` stacks are 232-byte placeholders). Only whole-container vzdumps of 301: kestrel HDD 2026-01-05 (x2), 2026-01-06, 2026-10-04; torus AirDisk 2026-10-04. kestrel's HDD also holds an unidentified CT **601** archive (31 GB, 2026-10-04) and old 100, 102–105, 201, 305 archives.

Written: `operations/research-cruise-backup.yml` (`mise run research-cruise-backup`): row counts + `BACKUP … WITH COPY_ONLY, CHECKSUM` + `RESTORE VERIFYONLY` inside externum's DB container (sa password stays in the container), file pulled to torus `/mnt/pve/backup/research-cruise/` and removed from externum, second copy on kestrel (sha256 compared), restore into a throwaway `mssql/server:2022-CU23-ubuntu-22.04` on zoltan with `--network none`, `DBCC CHECKDB`, row counts compared, temp server and files always removed; local transit copy in build/ deleted. Tested end to end on the laptop against a real CU23 server with a fake `pct`.
- 2026-10-06: second inspection: the new HDD `W380WY6S` has **no signatures at all** (wipefs empty) → blank. Write rates since boot: kestrel Lexar 15 GB/day (total 12.14 TB written), torus Samsung **119 GB/day** (6.22 TB, 1%), torus AirDisk 27 GB/day (move archives). The heavy writer moved with the old guests to torus; per-guest (`pvesh … /lxc` diskwrite) and per-container (`docker stats` BlockIO) numbers added to the inspection to pin it down (suspect: HyperDX/ClickHouse on externum).
- First `research-cruise-backup` run (2026-10-05 21:58 UTC): backup + VERIFYONLY OK, `ResearchCruiseApp-20261005-2158Z.bak` (15.8 MB) on torus and kestrel `backup/research-cruise/`, sha256 equal. Restore test interrupted by the owner while SQL Server was still starting (~50 s), so cleanup was skipped; the local copy in build/ was deleted by hand. Playbook now clears leftovers (container, folder, local copy) at the start of each run, waits up to 5 min and shows the container's status and log if SQL Server never answers. `ansible.cfg` `[colors] debug = normal`: retry lines were invisible in the owner's terminal theme.
- Second `research-cruise-backup` run: the temporary SQL Server on zoltan was **ready after 5 s** (its log, read through Arcane), yet the readiness check kept failing, and no login attempt ever reached the server (no error 18456). Cause not yet known; suspect the password never reached `docker run` via `environment:` through the pct_remote connection (first use of `environment:` on a guest). Changes: password now goes through a root-only `--env-file` (`/opt/research-cruise-restore-test.env`, deleted with the server); the wait is one loop inside zoltan (60 × 5 s, Ansible's per-retry reconnect made "5 min" ≈ 15 min); on failure it prints sqlcmd's last error, whether the password is set in the container, the status and log tail. Also fixed: the restore step asked for /bin/bash, which Alpine guests don't have (now busybox sh, `set -euo pipefail` works there).
- Cause found (owner ran sqlcmd in the container through Arcane): `TCP Provider: Error code 0x2AFA` = name lookup failed. With `--network none` the container has only loopback, and the ODBC driver's lookup of "localhost" returns nothing there (podman on the laptop behaved differently, so the local test missed it). Fix: `sqlcmd -S 127.0.0.1` (also used for externum's server, for consistency).
- **Step 3 DONE 2026-10-06 (00:34 local):** `research-cruise-backup` passed: `ResearchCruiseApp-20261005-2234Z.bak` (15 MB, sha256 `8d632381dcc336142b9cbd45d9e41a419f1c59334088c17c5e8848430cc6cf51`) on torus and kestrel `/mnt/pve/backup/research-cruise/`, made by SQL Server 16.0.4236 (database version 957); restored into a throwaway CU23 server on zoltan, DBCC CHECKDB no errors, 65 tables / 1,217 rows, counts identical to live; temp server, files and local transit copy removed. Earlier runs left three more verified backups (2158Z and two around 22:1x/22:2x UTC) on both disks, ~15 MB each; kept.
- Write culprit (inspect-storage-3): **externum 155 GB/day** (old guests have no cgroup delegation, so per-container numbers show 0); internum's Komodo MongoDB 7.6 GB in 1.4 days; Arcane agents ~0.7–1 GB/day each (engi more right after start); dns1 guest 14 GB/day vs ~1.3 GB from its containers (suspect Docker's never-rotated json-file logs). Proposed: stop HyperDX for an hour as a test (owner to decide, watch externum's Disk IO graph in Proxmox), and Docker `local` log driver (rotated) in stage 4.
- Komodo on externum (owner's screenshot): `xbackup-cruisedb` is tagged "Auto-Job" (its real command lives in Komodo's stack settings; no .bak was ever found, so it either failed or wrote elsewhere: ask owner); unknown UI-defined stack `vitask` (DOWN).
- Owner 2026-10-06: stopped HyperDX and Uptime Kuma on externum (Komodo) as a wear test, result pending (Proxmox Disk IO graph of 301); `xbackup-cruisedb` never worked (ignore); `vitask` can be forgotten.
- Docker log rotation (owner OK), code done, not run: stage 4 writes `/etc/docker/daemon.json` `{"log-driver": "local"}` and restarts Docker once per guest (throttle 1, also for the old `arcane` guest: its stopped Arcane stays stopped); stage 5's compose task re-creates a project once when its containers still use another log driver (detection tested with a fake docker).
- **Wear culprit confirmed 2026-10-06:** externum's Disk IO graph wrote ~1.8–2 MB/s (≈ 160 GB/day, matches the counters), stepped down to ~1.35 MB/s around 00:22 and fell to ~0.1 MB/s (≈ 8 GB/day) at ~00:41 after the owner stopped HyperDX and Uptime Kuma in Komodo. Both are excluded from the new setup; keep them stopped. (internum's Uptime Kuma and Komodo MongoDB still run.)
- Docker log rotation run: `mise run setup` (all guests, Docker restarted once each), `mise run services` (Caddy, Arcane, agents, both Technitium nodes re-created once). Re-run: changed=0 everywhere. Committed.

### Step 4 part 2 (OpenMediaVault VM) — DONE 2026-10-06 (commits `4115d35`, `5f8e121`)

Owner's choices: Debian 13 cloud image + Ansible install (OMV's "on Debian" guide), and USB passthrough of the whole HDD via a Proxmox USB mapping.
- Inventory: group `vms` (not in `guests`): `nas` on torus, 2040, 10.20.0.40, 2 cores / 2 GB / 8 GB, `usb: [nas-hdd]`; image `debian-13-genericcloud-amd64-20261001-2618.qcow2` pinned by sha512 (Debian doesn't sign per-build images); SSH with the fleet key, `StrictHostKeyChecking=accept-new` into secrets/known_hosts. torus `usb_mappings: { nas-hdd: { disk_serial: W380WY6S } }`.
- Stage 2 new part `vm-support`: `local` content = backup,import,iso,vztmpl; USB mappings made from the disk serial (udev ID_USB_VENDOR_ID:ID_USB_MODEL_ID), extra mappings removed, a mapping whose disk is already in a VM is kept; role OpenTofu + `Mapping.Use` (no root needed for the VM). Logic tested with fake command outputs.
- Stage 3: `proxmox_download_file.vm_image` (content import) + `proxmox_virtual_environment_vm.vm` (x86-64-v2-AES, virtio-scsi-single, disk imported and grown, serial console, usb mapping usb3, cloud-init root + keys/*.pub, router DNS, stop_on_destroy, `ignore_changes = [disk[0].import_from]` so a newer image never rebuilds an existing VM). `tofu validate` OK.
- Stage 4 play "Set up the VMs" (`hosts: … :&vms`; the LXC play is now `:&guests`, so `mise run setup nas` only hits the VM play): wait for SSH, apt dist-upgrade, reboot if required, root password for the Proxmox console made once and saved to `secrets/nas.sops.yaml`.
- Stage 5 part `nas`: OMV 8 "synchrony" per the guide (systemd-resolved first, keyring, sources, apt install with the guide's options, `omv-confdbadm populate`), SSH keys only via `Ssh set` (fresh OMV allows passwords), network handed to OMV (`Network setEthernetIface` static, same address; cloud-init network disabled, its netplan file removed, `omv-salt deploy run systemd-networkd` async), web UI user `admin` password = `nas_admin_password` in services.sops.yaml, web UI check on http://10.20.0.40/. DNS record `nas`. Data disk filesystem and shares: later (explicit, by serial).
- Live 2026-10-06: `host torus --tags vm-support,api-token` OK (local already allowed import; mapping nas-hdd = 0bda:9201, a Realtek USB-SATA bridge; role + Mapping.Use). `guests`: 2 added (image, VM 2040). `setup nas` OK (secrets/nas.sops.yaml). `services --tags nas,dns`: DNS `nas` added; OMV play failed at fact gathering with `/usr/bin/python3.14 not found`: run_once + delegate_to localhost in tasks/save-secrets.yml pushed the laptop's Python path onto the hosts; fixed by `ansible_python_interpreter: "{{ ansible_playbook_python }}"` on those two tasks (as stage 4 already does).
- Re-run: OMV package installed, then `omv-confdbadm populate` crashed in `40netplan.sh`: **OMV 8 bug** (since 2026-01-22, still in master): importing netplan `nameservers` sets `dnsservers`, the model property is `dnsnameservers`. Workaround: before populate, disable cloud-init networking and move `/etc/netplan/50-cloud-init.yaml` to `/root/50-cloud-init.yaml.before-omv`; populate guarded by marker `/etc/openmediavault/.populated-by-infra-as-script`. Network handover now compares OMV's eth0 settings (method/address/gateway) and corrects an existing entry with its own uuid. Worth reporting upstream.
- 2026-10-06: OMV installed and reachable (http://nas.lab.wsiwiec.com, SSH keys only verified, re-run changed=0), **but the USB HDD was not visible in the VM**: Debian's "genericcloud" image runs the cloud kernel, built with `# CONFIG_USB_SUPPORT is not set`. Switched `vm_image` to `debian-13-generic-amd64-20261001-2618.qcow2` (normal kernel, also cloud-init). The image only seeds new VMs (`ignore_changes`), so `nas` must be rebuilt: `mise run guests` now takes tofu options, e.g. `mise run guests '-replace=proxmox_virtual_environment_vm.vm["nas"]'` (tested with fakes). Console password moved from stage 4 (only set when no saved file existed → a rebuilt VM never got it) to stage 5 (`nas_root_password` in services.sops.yaml, set every run); `secrets/nas.sops.yaml` (never committed) deleted.
- Rebuild attempt: the old VM 2040 was already gone (owner removed it after the stuck reboot: Proxmox "Reboot" timed out on the genericcloud VM). Deleting the replaced image failed: `403 Permission check failed (/storage/local, Datastore.Allocate)`. Owner chose: allow deleting only on `local`. Stage 2 api-token now data-driven: `api_roles` (OpenTofu on /, new OpenTofuLocalFiles = Datastore.Allocate) and `api_acls` (`/`→OpenTofu, `/storage/local`→OpenTofuLocalFiles); grants compared as "path|role", missing added, others removed (tested with fake pvesh data).

### INCIDENT 2026-10-06: all LXC guests destroyed by stage 3

- Cause (mine): the new grant `/storage/local → OpenTofuLocalFiles` had only `Datastore.Allocate`. In Proxmox a grant on a deeper path **replaces** the inherited one for that path, so the token lost Audit/AllocateSpace/AllocateTemplate on `local`. The refresh then got 403 listing files, OpenTofu took the Alpine template (and the image) as gone, and because `template_file_id` forces replacement it planned to rebuild every LXC: "9 to add, 5 to destroy" (expected 2/0/1). It was approved with "yes": **dns1, dns2, zoltan, engi and the old arcane guest were destroyed**; the downloads then failed (403), so nothing was created.
- Lost for good: Arcane's database (both copies), Technitium logs/stats. Rebuildable from the repo: everything else. Untouched: Research Cruise backups, old guests on torus (komoda/internum/externum/tailscale-box), hosts, router. Home DNS (Technitium) down until rebuilt.
- Fixes: OpenTofuLocalFiles = Datastore.Allocate + AllocateSpace + AllocateTemplate + Audit (comment explains the override); `overwrite_unmanaged = true` on both download resources (files exist on disk, not in state); old guest `arcane` and the one-time Arcane move tasks removed (nothing left to move); **`scripts/tofu-apply.sh`** now runs `guests` and `network`: plan to a file, discard keys typed meanwhile, if anything is destroyed list it and require `destroy <n>` (plain "yes" never applies a destroying plan), then apply exactly that plan (tested with a fake tofu: no changes, add+yes, add+other, destroy+yes, destroy+"destroy 2").
- Recovery order: `host torus|kestrel --tags api-token` → `guests` (expect 8 to add, 0 destroy) → `setup` → `services --tags dns` (DNS back first) → `services`.
- Recovery 2026-10-06: api-token on both hosts OK; `guests` 8 added / 0 destroyed; `setup` OK for dns1/dns2/zoltan/engi; nas refused: stale host key (re-recorded by a run against the old VM after it was first removed). Removed again; inventory comment explains forgetting a rebuilt VM's key.
- services run after recovery: DNS cluster rebuilt (all records), Caddy/Arcane/agents OK; nas failed again with /usr/bin/python3.14 (leak not pinned down even with the save-secrets fix; delegated discovery isn't propagated, run_once facts are copied to all play hosts). Fix: `ansible_python_interpreter: /usr/bin/python3` for group vms.
- **Recovered 2026-10-06:** OMV installed on the rebuilt nas; the HDD shows in OMV as /dev/sdb (ST1000LM014-SSHD-8GB, W380WY6S, 931.51 GiB). Full `mise run services`: changed=0 on all hosts. Committed `4115d35` (not pushed). Then added: stage 5 applies OMV's pending changes (`Config isDirty` / `applyChanges`); OMV's install enabled Debian backports, 33 updates pending → `mise run setup nas`. Not run yet.
- 2026-10-06: `setup nas` installed the updates (no restart needed); `services --tags nas` applied OMV's pending changes (changed=1). isDirty needs '{}' as parameter; committed.
- 2026-10-06: re-run changed=0 for nas. Pushed up to 5f8e121.

### Step 5 part one (storage + backups) — chunk 1 DONE (`5014757`); PBS/backups DROPPED 2026-10-06

Owner's decisions: Proxmox Backup Server (PBS) with its datastore on an OMV share (S3 later as off-site copy through PBS; PVE's vzdump itself can't write to S3, PBS ≥ 4.2 supports S3 datastores officially); Proxmox Datacenter Manager (PDM 1.x, Debian 13 repo) to see torus/kestrel/pbs in one UI, allowed to manage guests (start/stop/migrate); a personal SMB share `wojtek` with NAS user `wojtek`; no alerts for now (unresolved). Planned guests: VM `pbs` (torus, 2041, 10.20.0.41, 2/2 GB/8 GB), VM `pdm` (kestrel, 2011, 10.20.0.11, 2/2 GB/10 GB). Owner asked about Debian LXCs: PBS needs NFS (unprivileged LXCs can't mount it; a host bind mount needs root, which the OpenTofu token isn't); PDM could be an LXC but needs a Debian template + Debian path in stage 4 → recommended VMs for both, owner's answer pending.
- Chunk 1 (code, not run): `stages/5-services/tasks/nas-storage.yml` (included in the nas play): data disk found by serial (`data_disk: W380WY6S` on nas in the inventory), formatted only with `-e format_nas_disk=<serial>` through OMV's `FileSystemMgmt create` (background job, waited for), mounted through `setMountPoint` + applyChanges, shared folders `pbs-store` (700) and `wojtek` (770, user wojtek rw), user `wojtek` (password `nas_user_password` in services.sops.yaml, created once), SMB on + share `wojtek` (no guests). Tested against fake lsblk/omv-confdbadm/omv-rpc (blank without flag stops; with flag formats + sets up; all in place = no calls).
- Chunk 1 run 2026-10-06: OMV's first background format did finish (it was still running when my loop stopped waiting); format now runs in the foreground with OMV's options and a still-running-mkfs guard. Mounted, user wojtek, folders pbs-store + wojtek, privileges, SMB on + share wojtek, changes applied. SMB answers (share list visible anonymously, as Samba allows by default; access needs the login). Committed.
- Owner chose **PDM as a Debian LXC** (chunk 3: needs a Debian template in stage 3 and a Debian path in stage 4). Owner connected the SMB share (Nautilus bookmark `smb://nas.lab.wsiwiec.com/wojtek` added to ~/.config/gtk-3.0/bookmarks).
- Chunk 2 (code, not run): inventory VM `pbs` (torus 2041, 10.20.0.41, `backup: false`); OMV NFS on + export of pbs-store to 10.20.0.41/32 (`rw,subtree_check,secure` + `no_root_squash`); DNS `pbs`. Stage 5 part `pbs`: Proxmox keyring (sha256 136673be… verified) + `pbs.sources` (trixie, pbs-no-subscription), `proxmox-backup-server` + nfs-common, enterprise source disabled if present, root password `pbs_root_password`, systemd mount `/mnt/datastore` = nas:/pbs-store (NFS 4.2), owner backup, datastore `store`, GC daily, prune job daily-prune (7/4/3), verify job weekly-verify (sat 04:00, outdated after 30 d), user `pve@pbs` with a token per Proxmox machine (secrets `pbs_tokens`, remade if lost), ACL DatastoreBackup, cert fingerprint. Part `backups` (hosts proxmox): storage `pbs` with the machine's token + fingerprint, job `nightly` 02:30 snapshot for the machine's inventory guests (torus 2020,2040,2055; kestrel 2010,2054). Router: "Allow Internal to Infra" covers Management → pbs:8007. Tested offline: token/fingerprint parsing, guest lists.
- **Mistake 2026-10-06:** the OMV play was `hosts: vms`; with the new VM pbs it installed OpenMediaVault on pbs (and handed its network to OMV) before failing at "find the data disk". Fixed: `hosts: nas`. pbs to be rebuilt (`-replace`, then `ssh-keygen -R 10.20.0.41`). Also: datastore create uses `--reuse-datastore true` when the share already has `.chunks`; tokens are remade when missing in PBS (tokenid list) or in the secrets.
- tofu-apply.sh now forgets the known_hosts entry of every VM it creates (rebuilt VM = new host key); tested with a fake tofu (it removed pbs's old entry). PBS datastore prepared on nas (65,536 folders, owner 34, 0755/0750/0644 exactly as PBS's verify_chunkstore checks; 0.5 s locally vs ~1 h over NFS), PBS mounts folder 0755, create uses --reuse-datastore. Tested in a scratch folder.
- **2026-10-06: PBS dropped by the owner** (see "Dropped / deferred" at the top). The PBS run had installed PBS and taken over the prepared datastore on pbs, but adding storage "pbs" on the hosts failed (output hidden by no_log; not investigated). Code reverted to before PBS, keeping: OMV play `hosts: nas`, tofu-apply.sh forgetting new VMs' host keys. Cleanup done (see the top). Also fixed: OMV `setSettings` (NFS/SMB) must not get the `shares` list that `getSettings` returns.

### PDM (step after the PBS drop) — deployed 2026-10-07; combined commit `8e20bcf`, network access fixed below

The entries below are a chronological log; earlier "not run yet" notes describe intermediate states, superseded by the final deployment and verification entries.
- Stage 3: per-guest `os` (default alpine) with `lxc_templates` {alpine, debian-13-standard_13.6-1 (sha512 from the signed aplinfo-pve-9.dat)}; downloads keyed "<node>/<os>" (`moved` blocks from the old node keys); containers `ignore_changes = [operating_system[0].template_file_id]` (a template only seeds a new guest; would have prevented the incident). `tofu console` check: downloads kestrel/alpine, kestrel/debian, torus/alpine; only pdm is debian.
- Inventory: guest `pdm` (kestrel, 2011, 10.20.0.11, 2 cores/2 GB/10 GB, os debian); proxmox var `api_from: [pdm]`.
- Stage 2 firewall: one rule per api_from guest (ACCEPT tcp 8006 from its address, comment "infra-as-script: API for <guest>"), stale ones removed first (highest pos first; new rules go to position 0). Tested with fake rule lists.
- Stage 4: `group_by os_<os>`; the Alpine play runs on os_alpine, a new Debian play (python3 via raw, apt dist-upgrade) on os_debian.
- Stage 5: prepare play also on proxmox hosts + group_by; Arcane agents only on `os_alpine:!arcane_manager`. Part `pdm`: on each Proxmox machine role PDM (Sys/VM/Datastore/SDN/Pool/Mapping.Audit, VM.PowerMgmt, VM.Migrate), user pdm@pve, token `pdm` (privsep 0; remade if missing in PVE or in the secrets → `pdm_tokens`), API cert fingerprint (pveproxy-ssl.pem or pve-ssl.pem). On pdm: keyring + pdm-no-subscription source, `proxmox-datacenter-manager-container-meta`, root password `pdm_root_password`, remotes torus/kestrel via `proxmox-datacenter-manager-admin remote add|update` (nodes "<address>,fingerprint=<fp>", authid pdm@pve!pdm). DNS `pdm`. PDM's own wizard would create a root token; this uses the role instead. Remote migration between the two machines would need more rights (later).
- Run order: `mise run host torus --tags firewall`, same for kestrel → `mise run guests` (expect 2 to add: kestrel/debian template + pdm; 2 moved; 0 destroy) → `mise run setup pdm` → `mise run services --tags dns,pdm` → https://pdm.lab.wsiwiec.com:8443 (root, Linux PAM).
- PDM run 2026-10-07: firewall rules on both hosts OK; `guests` 2 added (kestrel/debian template, pdm), 2 moved, 0 destroyed; `setup pdm` OK; `services --tags dns,pdm`: DNS pdm added, new secrets saved, then torus/kestrel failed with /usr/bin/python3.14 (third time the laptop's interpreter leaked onto hosts after a secrets save; a faithful local repro of save-secrets does not leak, cause still unknown). Fix: `ansible_python_interpreter: /usr/bin/python3` for proxmox and guests too (vms already) — nothing is discovered any more; stage 0/4 laptop plays keep their own play var.
- 2026-10-07 (owner): web UIs without ports through Caddy, code written, not run: OMV web UI HTTPS-only with OMV's own self-signed cert (CN/SAN nas.lab.wsiwiec.com, `CertificateMgmt create` + `WebGui setSettings`); new last play "Caddy routes to other guests' web UIs" (tags proxy/nas/pdm) reads each backend's cert (PDM `/etc/proxmox-datacenter-manager/auth/api.pem`, OMV `/etc/ssl/certs/openmediavault-<ref>.crt`) and writes `/opt/caddy/backends/<name>.{pem,caddy}` (reverse_proxy https with `tls_trust_pool file` + `tls_server_name` = first DNS SAN), Caddyfile `import /etc/caddy/backends/*.caddy` (empty glob = warning), Caddy restarted on change, routes checked from the laptop with certificate verification. DNS: `pdm` and new `omv` → zoltan; `nas` stays direct (SMB). Tested: rendered route from a real cert validates in caddy:2.11.6. Run: `mise run services --tags dns,proxy,nas,pdm`.
- 2026-10-07 (owner): **CLIProxyAPI** (AI subscriptions behind one OpenAI/Claude-compatible API), code written, not run. Docker on zoltan behind Caddy, not its own LXC (the community-scripts LXC is only the release binary + systemd; here it gets Caddy's certificate, Docker's log rotation and stage 5's secrets for free, and no OpenTofu plan). Stage 5 part `cliproxy` (group `cliproxy` = zoltan, `cliproxy_host` = cliproxy.lab.wsiwiec.com, DNS → zoltan): image `eceasy/cli-proxy-api:v8.0.16`, config.yaml written by stage 5 (v8 layout; client key `cliproxy_api_key`, `trusted-proxies` = Caddy network's subnet read from Docker, panel never auto-updated), panel key `cliproxy_management_key` via MANAGEMENT_PASSWORD (never written into config.yaml), OAuth tokens in volume `auths`; check from the laptop: /v1/models with the key. Tested locally with podman on the real image: config loads and is not rewritten, /v1/models 401 without key / 200 with it, management 401 wrong key / 200 right key, panel 200, OAuth redirect_uri is `http://localhost:<port>/callback` (paste the failed redirect URL back into the panel; no callback ports published). Run: `mise run services --tags dns,proxy,nas,pdm,cliproxy`.
- 2026-10-07: `services --tags dns,proxy,nas,pdm,cliproxy` failed on pdm at apt update: 401 from `enterprise.proxmox.com/debian/pdm`. The PDM package (1.1.7, checked in the .deb) ships `/etc/apt/sources.list.d/pdm-enterprise.sources` as a conffile; the first run installed it, so every later apt update fails. Fix: stage 5 writes that file with `Enabled: false` before installing (dpkg keeps it on install/upgrade: force-confold). Not run yet.
- 2026-10-07: next failure on pdm, "Add or update each Proxmox machine as a remote": `remote list --output-format json` gives each node as a property string (`nodes: Vec<PropertyString<NodeUrl>>` in pdm-api-types), not an object. Fix: hostname and fingerprint parsed out of "[hostname=]<address>[,fingerprint=<fp>]" (tested on all orders/forms), fingerprint compared case-insensitively. Not run yet.
- 2026-10-07: `services --tags dns,proxy,nas,pdm,cliproxy`: CLIProxyAPI deployed on zoltan, check from the laptop passed. Then "Caddy routes" stopped at a paramiko host-key prompt for 10.20.0.40: in its loop delegating to pdm then nas, nas (no ansible_connection) reused the pct connection type of the pdm item (reproduced locally with core 2.21.4). Fix: `ansible_connection: ssh` for group vms. Not for proxmox: stage 0/4 plays there use `connection: local`, which a host variable would override. Not run yet.
- 2026-10-07 (owner): CLIProxyAPI routing `fill-first` + `session-affinity: true` (subscriptions' 5-hour windows start one after another; a thread keeps its account and prompt cache). Not run yet. Idea for later: a scheduled one-token request per subscription before the working day starts its 5-hour window early; needs a way to send a request to one chosen subscription (per-credential model prefix, or the management API's upstream call), not checked yet.
- 2026-10-07: **Arcane CPU reporting fixed and deployed**. Docker inside LXC saw the physical node's `/proc/cpuinfo` and `/proc/stat`; dns1 preflight confirmed guest cpuinfo = 1, Docker cpuinfo = 4, affinity = CPU 0. Manager and agent templates now bind both guest files read-only into the same paths. `arcane_version` aligned to v2.15.0 (already running everywhere). Applied through the authenticated Arcane browser/API using temporary `docker:cli` helpers because the fleet SSH key remained locked: each helper checked guest CPU count against inventory, backed up `/opt/<arcane|arcane-agent>/compose.yaml` as `compose.yaml.before-cpu-mounts-20261007` (root-only), validated the edited Compose, then recreated only Arcane with `--no-deps --pull never --wait`. All helpers exited 0; all helper containers and newly pulled docker:cli images removed. Live dashboard verified zoltan 4, dns1 1, dns2 1, engi 2 CPUs; all 8 service containers running, both Technitium containers uninterrupted. Checked read-only mounts via container inspection. `mise run check` passed, both templates rendered with dummy secrets and parsed, targeted `git diff --check` passed. No SSH key was loaded by this session.
- 2026-10-07: PDM run failed once on `apt update`: the PDM package had added Proxmox's paid source (401 without subscription); now every `enterprise.proxmox.com` source on the guest is turned off before and after the install. Final run: changed=0, routes verified from the laptop (pdm/omv HTTP 200, cert OK, via zoltan), SMB on nas unaffected.
- **Another session edited this repo in parallel** (finished; committed together in `8e20bcf`): CLIProxyAPI on zoltan (`cliproxy.lab.wsiwiec.com`, inventory group `cliproxy`, secrets cliproxy_*, play "CLIProxyAPI"), Arcane v2.14.0 → v2.15.0, `/proc/cpuinfo` + `/proc/stat` mounts in the Arcane templates. These changes are committed, not outstanding. Continue to stage only intended files and coordinate one writer at a time.

### PDM network access and closeout — verified 2026-10-07

- PDM's dashboard initially loaded indefinitely: host-level API rules existed, but UniFi blocked Infra → Internal connections. `network/main.tf` now has `unifi_firewall_zone_policy.infra_to_proxmox_api`, sourced from inventory `api_from`; it permits 10.20.0.11 → 10.1.0.2/10.1.0.30 on TCP 8006 only, with automatic return traffic. The existing UniFi device type/icon `dev_id_override = 5254` is preserved for both machines instead of reset by the plan.
- Owner's final apply output at 2026-10-07 14:37 UTC: `Apply complete! Resources: 1 added, 0 changed, 0 destroyed.` Updated network state remains encrypted.
- Owner supplied a PDM 1.1.7 dashboard screenshot (refresh 2026-10-07 17:04:41 Europe/Warsaw): all remotes reachable, kestrel and torus listed, 2 nodes online, 1 VM and 9 LXCs running, none stopped. No backup-server nodes is expected after dropping PBS. The no-subscription notice is not a connection failure. The agent did not log in to PDM or exercise guest power/migration operations.
- Closeout checks: `mise run check` passed (Ansible lint: 0 failures, 0 warnings; both OpenTofu formatting checks); `tofu validate` passed for network and stage 3; encrypted network-state envelope confirmed without decryption. The first lint attempt failed on this harness's non-blocking stderr, not a code finding; rerunning with blocking subprocess I/O passed. No further infrastructure apply was run.
