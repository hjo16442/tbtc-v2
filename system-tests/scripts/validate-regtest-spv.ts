import { readFileSync } from "fs"
import { BigNumber } from "ethers"
import {
  assembleBitcoinSpvProof,
  validateBitcoinSpvProof,
} from "../../typescript/src/lib/bitcoin/spv"
import type { BitcoinClient } from "../../typescript/src/lib/bitcoin/client"
import { BitcoinNetwork } from "../../typescript/src/lib/bitcoin/network"
import { BitcoinTxHash } from "../../typescript/src/lib/bitcoin/tx"
import { Hex } from "../../typescript/src/lib/utils"

type RegtestEntry = {
  txid: string
  blockHeight: number
  headers: string[]
  txIndex: number
  coinbaseTxid: string
  coinbaseRawTransaction: string
  spvProof: {
    merkleProof: string
    txIndexInBlock: number
    bitcoinHeaders: string
    coinbasePreimage: string
    coinbaseProof: string
  }
}

function merkleBranch(proof: string): Hex[] {
  const normalized = proof.replace(/^0x/, "")
  if (normalized.length % 64 !== 0) {
    throw new Error("Malformed Merkle branch in regtest artifact")
  }

  const branch: Hex[] = []
  for (let offset = 0; offset < normalized.length; offset += 64) {
    branch.push(
      Hex.from(Buffer.from(normalized.slice(offset, offset + 64), "hex").reverse())
    )
  }
  return branch
}

function createBitcoinClient(entry: RegtestEntry): BitcoinClient {
  const coinbaseHash = new BitcoinTxHash(entry.coinbaseTxid)

  return {
    getNetwork: async () => BitcoinNetwork.Unknown,
    findAllUnspentTransactionOutputs: async () => [],
    getTransactionHistory: async () => [],
    getTransaction: async (hash) => ({
      transactionHash: hash,
      inputs: [],
      outputs: [],
    }),
    getRawTransaction: async () => ({
      transactionHex: entry.coinbaseRawTransaction,
    }),
    getTransactionConfirmations: async () => 6,
    getTxHashesForPublicKeyHash: async () => [],
    latestBlockHeight: async () => entry.blockHeight + 5,
    getHeadersChain: async () => Hex.from(entry.headers.join("")),
    getTransactionMerkle: async (hash, blockHeight) => {
      if (blockHeight !== entry.blockHeight) {
        throw new Error("Unexpected block height requested by SPV assembler")
      }
      const isCoinbase = hash.toString() === coinbaseHash.toString()
      return {
        blockHeight,
        merkle: merkleBranch(
          isCoinbase
            ? entry.spvProof.coinbaseProof
            : entry.spvProof.merkleProof
        ),
        position: isCoinbase ? 0 : entry.txIndex,
      }
    },
    broadcast: async () => {
      throw new Error("Broadcast is not used by the SPV proof test")
    },
    getCoinbaseTxHash: async () => coinbaseHash,
  }
}

function equalHex(actual: Hex, expected: string, field: string) {
  const normalizedExpected = expected.replace(/^0x/, "").toLowerCase()
  if (actual.toString().toLowerCase() !== normalizedExpected) {
    throw new Error(field + " differs from the independently generated artifact")
  }
}

async function validateEntry(label: string, entry: RegtestEntry) {
  const txHash = new BitcoinTxHash(entry.txid)
  const client = createBitcoinClient(entry)

  const assembled = await assembleBitcoinSpvProof(txHash, 6, client)
  equalHex(assembled.merkleProof, entry.spvProof.merkleProof, label + " merkleProof")
  equalHex(assembled.bitcoinHeaders, entry.spvProof.bitcoinHeaders, label + " bitcoinHeaders")
  equalHex(assembled.coinbasePreimage, entry.spvProof.coinbasePreimage, label + " coinbasePreimage")
  equalHex(assembled.coinbaseProof, entry.spvProof.coinbaseProof, label + " coinbaseProof")
  if (assembled.txIndexInBlock !== entry.spvProof.txIndexInBlock) {
    throw new Error(label + " transaction index differs from artifact")
  }

  await validateBitcoinSpvProof(
    txHash,
    6,
    BigNumber.from(1),
    BigNumber.from(1),
    client
  )
  process.stdout.write("PASS: " + label + " proof assembled and validated by tBTC TypeScript SPV logic\n")
}

async function main() {
  const fixturePath = process.argv[2]
  if (!fixturePath) {
    throw new Error("Usage: validate-regtest-spv.ts <transactions.json>")
  }
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8"))
  await validateEntry("moving-funds", fixture.movingFunds)
  await validateEntry("moved-funds-sweep", fixture.sweep)
}

main().catch((error) => {
  process.stderr.write((error instanceof Error ? error.stack : String(error)) + "\n")
  process.exitCode = 1
})
