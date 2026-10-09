# Xyberos P2P Relay Threat Model

**Status:** preliminary engineering threat model; independent cryptographic review
and product-owner decisions are pending.

**Scope reviewed:** the current manually paired, one-to-one HTTPS relay
foundation and the tenant-scoped application wrapper in this repository. This
document describes current code and known limitations; it is not a security
certification, formal protocol analysis, or production approval.

**Review date:** 2026-10-09

## 1. System and security objectives

The P2P path consists of local messaging/storage, a client-side envelope cache
and pinned peer-key configuration, an optional HTTPS relay hosted by an
application, and a separate tenant-scoped app boundary. Peers must be manually
paired and mutually allowlisted by the relay configuration.

The intended security objectives are:

1. Only manually trusted peers can authenticate relay requests and submit
   envelopes for an allowed pair.
2. A relay observer should not learn message bodies or conversation IDs from
   stored envelope payloads.
3. A recipient should detect envelope modification and verify the pinned sender
   signing key before decrypting a message.
4. Repeated synchronization should be safe for already stored message IDs, and
   inbound progress should be resumable through client-persisted cursors.
5. Application access should be scoped by trusted execution tenant,
   configured conversation, and authorized peer.

The implementation does **not** promise availability, anonymity, forward
secrecy, repudiation, managed identity federation, delivery receipts, or recovery
of lost private keys.

## 2. Assets and trust boundaries

| Asset | Location / sensitivity | Current protection |
| --- | --- | --- |
| Message body and conversation ID | Local peer message database; plaintext | No encryption at rest in the current SQLite message store. |
| Signing and encryption private keys | Peer process/configuration | Application supplies and protects persistent keys; identity provider can generate ephemeral keys if omitted. No managed keystore. |
| Peer public-key bundles and pairing policy | Application configuration | Explicit pinned keys and mutual allowed-pair lists; pairing distribution and verification are out of band. |
| Encrypted peer envelopes | Client cache and relay database | Sealed-box ciphertext plus Ed25519 signature; relay stores envelope metadata and payload append-only. |
| Relay routing metadata | Relay database, network, and operator logs | Peer IDs, recipient, timestamps, traffic size/volume, and connection metadata are visible. |
| Sync cursor and local envelope cache | Client database | Persisted for retry and progress; database access/backup controls are application-owned. |
| Tenant/application authorization configuration | Application process | Tenant/conversation/peer mappings are supplied by the application wrapper; this is not a central policy or identity service. |

Trust boundaries:

- **Application to local P2P service:** the raw messaging service is not an
  authorization boundary. Use the tenant-scoped wrapper and secure application
  authentication for exposed operations.
- **Peer to relay:** relay requests use HTTPS in deployment, a timestamped
  nonce-bearing request signature, a trusted peer key, and configured mutual
  pair authorization.
- **Relay to recipient:** the relay is not trusted with plaintext, but it can
  observe metadata, withhold, delay, reorder pages, or refuse service.
- **Pairing to key pinning:** the system trusts the application-provided mapping
  between peer ID and signing/encryption public keys. Correct out-of-band
  fingerprint verification is required; no discovery authority is supplied.
- **Host and backup boundary:** the machine, database, backup service, and
  configuration/secret store are trusted to protect plaintext local data and
  private keys. The current code does not provide that storage protection.

## 3. Adversaries and assumptions

Consider:

- A network attacker who can observe, delay, drop, duplicate, or modify traffic,
  but cannot break correctly configured HTTPS or the underlying cryptography.
- A curious or malicious relay operator with access to relay databases and
  server logs.
- An unpaired peer attempting to impersonate a registered peer or send to an
  unauthorized peer.
- A compromised paired peer that holds valid keys and is allowed by the
  application configuration.
- A local attacker or backup reader who can access client databases or
  configuration.
- An attacker attempting to exhaust relay CPU, storage, or network resources.

Assumptions:

- Production relay URLs use HTTPS with normal certificate validation; the client
  permits cleartext HTTP only for loopback development.
- Peer private keys and trusted peer fingerprints are generated, transferred,
  and stored securely by the application/operator.
- The host OS, Python runtime, PyNaCl/libsodium, cryptographic primitives, and
  TLS implementation are not compromised.
- Security-sensitive deployments do not use the configured development identity
  provider or ephemeral production keys.

Compromise of an endpoint or an already trusted peer is outside what the relay
protocol can prevent. Such a peer can read its own received messages and can send
valid signed content within the configured pair.

## 4. Current controls and residual risk

The project has set a V1 relay retirement date of 2027-03-31. Operators should
treat V1 as a transition-only compatibility path: keep V2 as the default client
protocol, monitor quota rejections during rollout, and disable the V1 route on or
before the retirement date. This gate establishes an operational migration policy;
it does not replace an independent cryptographic review or production approval.

| Threat | Current controls in code | Residual risk / status |
| --- | --- | --- |
| Untrusted peer impersonates a configured peer | Relay checks peer ID against its configured key registry; request signature covers method, path, timestamp, nonce, and body digest. Client pins peer keys and verifies envelope signatures. | Secure only while keys and their peer-ID association remain trustworthy. Pairing/fingerprint verification is out of band. |
| Unauthorized peer pair | Relay requires known, mutual allowlist entries; client requires target peer in its pinned list; tenant-scoped wrapper checks tenant, conversation, and peer mappings. | Configuration mistakes or bypassing the application wrapper remain application risks. No dynamic revocation or federation. |
| Passive relay reads message content | Message body and conversation ID are inside a sealed-box encrypted payload; envelope is signed. | Relay still learns sender/recipient IDs, message ID, timestamp, ciphertext length, timing, frequency, and network metadata. No traffic-analysis protection. |
| Relay modifies a submitted envelope | Sender signature is checked by relay; recipient verifies signature and checks envelope sender/recipient binding before decrypting. | Relay can still delete, withhold, delay, or selectively serve valid ciphertext. No availability guarantee or cryptographic delivery receipt. |
| Request replay | Signed timestamp and nonce; timestamp window is five minutes; nonce uniqueness is transactionally enforced in the database and old nonce rows are pruned. | Replay protection depends on shared durable database semantics and clock health. Concurrent use of the same nonce should allow at most one request. |
| Duplicate message submission | Relay uses a `(recipient_peer_id, message_id)` uniqueness key and rejects different payloads for an existing key; local store performs matching duplicate checks. | Identical envelope resubmission is idempotent while the deduplication row remains. Retention/deletion behavior is undefined; deleting rows could permit old message IDs to be accepted again. |
| Resource exhaustion | Request bodies and relay responses are limited to 4 MiB; envelope pages are bounded to 100; individual ciphertext is bounded; client has a request timeout. V2 enforces a configurable per-peer request bucket and per-recipient envelope/serialized-payload quotas. The byte quota counts serialized envelope payloads, not total database size. | V1 remains temporarily available without V2 rate or mailbox limits. The project has set a V1 retirement date of 2027-03-31. There is no global storage cap or relay-level concurrent-request cap; hosting-level connection/workload controls remain required. |
| Local database or backup disclosure | No cryptographic storage protection in the message-store implementation. | Local messages are plaintext; filesystem/database access or backups expose content. Envelope cache is encrypted payload, but local private keys may be configured in the same host boundary. |
| Key loss, rotation, or device replacement | Persistent keys can be supplied by the application; public bundles include a fingerprint. | No rotation, revocation, recovery, re-pairing, or key backup protocol. Losing the recipient private key makes stored ciphertext unreadable. Reusing a peer ID with replacement keys needs an explicit safe re-pair process. |
| Compromised peer key | Current signing and encryption keys are long-lived identity keys. | No forward secrecy or ratcheting. A later compromise of a recipient encryption private key can expose archived ciphertext addressed to that key. No automated revocation of a compromised peer. |
| Tenant boundary bypass | App wrapper requires a matching `ExecutionContext` tenant and checks configured conversation and peer lists. | Wrapper configuration is application-supplied; direct raw service access bypasses it. This does not replace HTTP authentication or domain authorization. |
| Malformed/oversized requests | Strict JSON/envelope validation, bounded input size/count, strict peer-ID format, and explicit HTTP errors. | Application/server-level connection, concurrency, and global workload limits remain deployment responsibilities. |
| Relay database tampering or rollback | Database uniqueness and transactions protect normal concurrent insert/replay behavior. | A privileged database attacker can delete or roll back mailbox/nonce state, deny service, or disclose metadata. No tamper-evident audit log or anti-rollback mechanism. |

## 5. Cryptographic properties and claims

Current code uses PyNaCl/libsodium Ed25519 signing and sealed-box public-key
encryption. A signed envelope binds message ID, sender peer ID, recipient peer
ID, creation time, and ciphertext. The relay request signature binds HTTP method,
path, timestamp, nonce, and the request body hash. The recipient checks that
envelope sender and recipient IDs correspond to the pinned peer and local
identity.

These observations describe how the code is composed; they are **not** an
independent review of protocol security. In particular:

- Sealed-box encryption with static recipient keys does not provide forward
  secrecy or post-compromise security.
- A signature proves control of the corresponding pinned signing key; it does
  not prove a human identity or that the key was safely paired.
- End-to-end payload encryption does not hide routing metadata, traffic patterns,
  or endpoint plaintext.
- HTTPS protects the network hop to the relay; it does not protect data at rest
  on either peer or relay host.
- No claim of production suitability, anonymity, complete message integrity
  across application semantics, or resistance to malicious endpoints should be
  made before independent review.

## 6. Owner decisions and remaining operational choices

The project owner selected the policies below. They do not constitute security
approval or resolve the remaining deployment and cryptographic review questions.
Do not infer delivery guarantees, mailbox deletion, or key lifecycle behavior.

| Decision | Options to evaluate | Current state |
| --- | --- | --- |
| Relay retention | Indefinite append-only; time-based expiry; recipient acknowledgement followed by expiry; explicit operator deletion | Owner decision: keep append-only with no automatic deletion. This preserves messages until delivery semantics are defined; manual purge remains unspecified. |
| Delivery semantics | Accepted by relay; fetched by peer; merged into local store; acknowledged by an application/user | Cursor tracks client paging progress only; it is not a delivery receipt. |
| Resource controls | Per-peer request rate, concurrent request cap, mailbox byte/count quota, global storage cap, abuse response | Implemented for V2 with configurable defaults of 60 requests/minute, burst 10, 10,000 envelopes, and 256 MiB of serialized envelope payload per recipient (not total database size). At capacity, V2 rejects new envelopes while still returning the inbox page and rejected IDs. V1 bypasses these new limits during transition and is scheduled to retire on 2027-03-31. No separate per-peer concurrent-request cap; hosting-level limits are required. No global storage cap. |
| Local storage protection | OS/database encryption, field/payload encryption, encrypted filesystem or application-managed key store | Owner decision: keep application message-store data plaintext in this phase; require encrypted disks/backups operationally and make no at-rest encryption claim. |
| Key rotation/revocation | Manual re-pair with new peer ID; signed key-transition record; trusted administrative revocation; recovery identity | Owner decision: static pinned keys; manual re-pair with a new peer ID after compromise or device replacement. No in-place rotation. |
| Key recovery and backups | No recovery (lost key means lost access); user-managed encrypted backup; managed recovery authority | Owner decision: no recovery guarantee; lost keys may make messages inaccessible. Any key backup remains application/operator-managed. |
| Operational signals | Aggregate request/rejection/size/storage metrics, audit event policy, alert thresholds | Owner decision: metadata-only structured logs for rate/quota rejection and bounded health data; defer a metrics API. Rejection logs do not include message bodies, ciphertext, or peer IDs. Application-configured bounded readiness probes remain the deployment health mechanism. |
| Protocol transition | Dual-stack compatibility, forced cutoff, client/server rollout order | V2 is the default client protocol. Keep V1 during a transition, announce a retirement date before ending support, and account for V1's temporary lack of quotas/rate limits. The project declares V1 retirement on 2027-03-31 and requires clients to migrate before that date. |
| Supported deployment database | SQLite single-host relay; PostgreSQL or another backend with equivalent transactional semantics | Relay uses the shared `Database` contract; validate the actual backend and concurrency characteristics before multi-worker claims. |

## 7. Required next actions

1. Obtain an independent cryptographic review of the envelope format, signing
   inputs, key separation, pairing, replay behavior, and implementation. Track
   every finding as a code change or owner-accepted risk.
2. Record the intended deployment topology, P2P product status, and a published
   V1 retirement date; until then, account for V1's unmetered transition risk.
3. Continue validating the approved controls under supported database backends,
   deployment topologies, restart, backup/restore, and migration conditions.
4. Version any wire-format, proof, or key-transition change and maintain
   compatibility tests for supported peers.
5. Update the security notes and operational runbook after each approved change.

Until these actions are complete, treat the relay as an experimental reference
foundation for manually paired one-to-one synchronization. Do not expose it as a
general-purpose public messaging service or claim forward secrecy or production
readiness.

## 8. Code references

- [`secure.py`](../xyberos/providers/p2p/secure.py): key providers, envelope,
  encryption, signing, and decryption.
- [`https_relay.py`](../xyberos/providers/p2p/https_relay.py): relay transport,
  request verification, replay nonce storage, mailbox and pagination.
- [`sqlite_message_store.py`](../xyberos/providers/p2p/sqlite_message_store.py):
  local plaintext message store.
- [`sqlite_envelope_cache.py`](../xyberos/providers/p2p/sqlite_envelope_cache.py):
  exact encrypted-envelope retry cache and sync cursor.
- [`application.py`](../xyberos/subsystems/p2p/application.py): tenant-scoped
  application messaging boundary.
- [`deployment.md`](deployment.md): operational deployment and provider
  limitations.
