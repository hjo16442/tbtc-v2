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

## Verification recorded

- Bitcoin Regtest PoC workflow #102: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127768
- Solidity workflow #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127759
- Code Format Checks #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066127714
- Solidity docs #60: success — https://github.com/hjo16442/tbtc-v2/actions/runs/46066128139
- Supporting Keep Core multi-operator experiment: https://github.com/hjo16442/keep-core/pull/3. Client CI run #13 passed all 9 jobs. A follow-up test on commit `977cdb04fa4047a6cc1bd841ccc21a100b62151b` exercises 5 independent node objects (one share each) and verifies 4-of-5 group signing both before and after wallet archival using the already-cached signing executors. The Go test step in client CI run #14 completed successfully; Docker/runtime packaging was still running when this report revision was prepared.

## Impact and recovery caveats

The directly demonstrated impact is that a new pending request can be created for a destination wallet that is already Terminated, while the ordinary on-chain sweep-proof route rejects the corresponding proof. The request remains pending until the timeout handler processes it; the timeout clears the pending-request count but does not itself demonstrate restoration of the destination wallet's Bridge accounting.

Protocol documentation describes off-chain coordination with wallet group members as the recovery route for Terminated wallets. The supporting Keep Core experiment demonstrates a local 4-of-5 group-signing session and removal of the wallet from each node's active registry during archival. The follow-up test also demonstrates that executors created before archival can still produce a valid group signature afterward, while those executors remain in memory. This is an important limitation on the interpretation of archival: it is not immediate revocation of already-cached signing capability. It does not prove that a restarted node can reload archived shares, that archived shares can or cannot be manually recovered, nor that the Bridge's on-chain UTXO accounting can be restored.

The local regtest wallet-key spendability check is a Bitcoin-layer check only; it is not proof of threshold-signature recovery or Bridge accounting recovery.

## Suggested remediation for review

Revalidate the destination wallet state when processing the moving-funds proof, before creating a moved-funds sweep request. Define an explicit safe handling path for outputs whose intended destination has become Terminated between commitment and proof submission. Add regression coverage for this state transition and ensure pending-request accounting remains consistent.

## Scope

All tests use local Hardhat fixtures and private Bitcoin regtest. No mainnet or public testnet funds were used. All changes are on the fork; upstream repositories are unchanged.
