# Security Report: Moving-funds proof can create a pending sweep request for a Terminated target

## Status

Reproducible local proof of an invalid request lifecycle. This report does not claim theft, permanent loss, or quantified financial impact. No production funds were touched.

## Affected flow

A destination wallet can transition from `Live` to `Terminated` after its previous moved-funds sweep request times out. A source wallet's already-committed moving-funds transaction can subsequently be proven. The proof-processing path creates a new `Pending` moved-funds sweep request for the now-Terminated destination without revalidating the destination's current state.

The normal `submitMovedFundsSweepProof` path then rejects the matching sweep proof because the sweeping wallet must be `Live` or `MovingFunds`.

## Reproduction sequence

1. Set destination wallet B to `Live` and create an older `Pending` moved-funds sweep request for B.
2. Set source wallet A to `MovingFunds`, configure its main UTXO, and submit a moving-funds commitment targeting B while B is Live.
3. Advance beyond the old request's timeout and call `notifyMovedFundsSweepTimeout`; assert B becomes `Terminated`.
4. Submit the valid moving-funds SPV proof for A's already-committed transaction.
5. Assert the new request keyed by the moving-funds tx hash/output index is `Pending`, references B, and B remains `Terminated`.
6. Submit the matching moved-funds sweep proof. It reverts with `Wallet must be in Live or MovingFunds state`.
7. Assert the request remains `Pending`, B's `mainUtxoHash` remains zero, and its pending request count remains one until the timeout path is processed.

## Evidence in this repository

- `solidity/test/bridge/Bridge.MovingFunds.test.ts`: same-target Hardhat end-to-end test using the exact same output/request linkage.
- `.github/workflows/bitcoin-regtest-poc.yml`: private Bitcoin Core 28.0 regtest environment; no public Bitcoin networking.
- `system-tests/scripts/build-regtest-spv-proofs.py`: derives transaction vectors and Merkle/SPV proof material from mined regtest transactions and verifies Merkle roots/header continuity.
- `system-tests/scripts/validate-regtest-spv.ts`: checks the generated proofs using the repository's TypeScript SPV assembly/validation logic.

## Supporting Keep Core experiments

The supporting experiment is in [Keep Core PR #3](https://github.com/hjo16442/keep-core/pull/3), branch `test/multi-operator-terminated-recovery`. It is test evidence about signer archival behavior; it does not itself demonstrate recovery of the tBTC Bridge's on-chain accounting.

The test file `pkg/tbtc/multi_operator_terminated_recovery_test.go` currently contains three relevant tests:

- `TestMultiOperatorSigningAndTerminatedWalletArchival`: five independent node objects each hold exactly one share of a 4-of-5 tECDSA group. A valid group signature is verified before termination. After the wallet is marked Terminated and each node archives it, the active signer registries are empty; already-created, cached signing executors can nevertheless produce another valid group signature while still resident in memory.
- `TestWalletRegistry_ArchivedSignerNotLoadedAfterRestart`: uses the disk persistence backend. The archived share remains on disk and is not loaded into a newly created registry. Manually moving the retained share directory back to the current-storage area makes a fresh registry load it; invoking the normal startup archival routine moves it back out of the active registry and into the archive.
- `TestMultiOperatorArchivedSharesAreRearchivedOnEveryRestart`: repeats the persisted-share lifecycle across five independent operator storage directories, one share per operator. Each fresh registry excludes the archived share; a manual filesystem restore temporarily makes it loadable, but the normal startup archival routine re-archives it because the wallet remains Terminated.

These tests demonstrate that archival is not secure deletion, that the normal registry startup path excludes archived shares, and that manual filesystem restoration alone is not sufficient to keep a Terminated wallet's share active after the normal startup archival check. They do not establish whether an operator could bypass that check by modifying software or runtime behavior, nor do they demonstrate successful threshold signing after a genuine process restart.

## Verification recorded

- Bitcoin Regtest PoC workflow #102: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127768
- Solidity workflow #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127759
- Code Format Checks #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127714
- Solidity docs #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066128139
- Keep Core PR #3 latest commit: `0c423572e4195da5665df2563b83f954a840675d`. All five associated GitHub Actions workflows completed successfully, including the client build/test and client integration-test jobs. The run set includes client workflow run https://github.com/hjo16442/keep-core/actions/runs/46134854073 and Solidity/docs workflows for Random Beacon and ECDSA.

## Impact and recovery caveats

The directly demonstrated impact is that a new pending request can be created for a destination wallet that is already Terminated, while the ordinary on-chain sweep-proof route rejects the corresponding proof. The request remains pending until the timeout handler processes it; the timeout clears the pending-request count but does not itself demonstrate restoration of the destination wallet's Bridge accounting.

Protocol documentation describes off-chain coordination with wallet group members as the recovery route for Terminated wallets. The Keep Core experiments show that active-registry archival does not revoke signing capability already held by cached in-memory executors. The disk-persistence tests show that archived share data remains on disk, is excluded by a fresh registry, and is re-archived by the normal startup archival routine after manual restoration while the wallet remains Terminated. This is evidence about local persistence and registry behavior only; it is not proof that a restarted operator can successfully recover and use the share, nor proof that threshold signing or Bridge accounting can be restored.

The local regtest wallet-key spendability check is a Bitcoin-layer check only; it is not proof of threshold-signature recovery or Bridge accounting recovery.

## Suggested remediation for review

Revalidate the destination wallet state when processing the moving-funds proof, before creating a moved-funds sweep request. Define an explicit safe handling path for outputs whose intended destination has become Terminated between commitment and proof submission. Add regression coverage for this state transition and ensure pending-request accounting remains consistent.

## Scope

All tests use local Hardhat fixtures and private Bitcoin regtest. No mainnet or public testnet funds were used. All changes are on the fork; upstream repositories are unchanged.
