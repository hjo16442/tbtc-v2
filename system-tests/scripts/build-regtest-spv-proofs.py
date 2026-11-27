#!/usr/bin/env python3
"""Build tBTC-compatible SPV proof fields from a two-or-more-tx regtest block."""

import hashlib
import json
import sys


def read_varint(data, offset):
    prefix = data[offset]
    if prefix < 0xFD:
        return prefix, offset + 1
    if prefix == 0xFD:
        return int.from_bytes(data[offset + 1:offset + 3], "little"), offset + 3
    if prefix == 0xFE:
        return int.from_bytes(data[offset + 1:offset + 5], "little"), offset + 5
    return int.from_bytes(data[offset + 1:offset + 9], "little"), offset + 9


def coinbase_preimage(raw_hex):
    raw = bytes.fromhex(raw_hex)
    version = raw[:4]
    offset = 4
    # Skip SegWit marker and flag; tBTC hashes the legacy transaction vectors.
    if raw[offset:offset + 2] == b"\x00\x01":
        offset += 2

    input_start = offset
    input_count, offset = read_varint(raw, offset)
    for _ in range(input_count):
        offset += 36
        script_len, offset = read_varint(raw, offset)
        offset += script_len + 4
    input_vector = raw[input_start:offset]

    output_start = offset
    output_count, offset = read_varint(raw, offset)
    for _ in range(output_count):
        offset += 8
        script_len, offset = read_varint(raw, offset)
        offset += script_len
    output_vector = raw[output_start:offset]

    locktime = raw[-4:]
    return hashlib.sha256(version + input_vector + output_vector + locktime).hexdigest()


def dsha(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def transaction_id(raw_hex):
    return dsha(bytes.fromhex(raw_hex))[::-1].hex()


def validate_header_chain(entry):
    headers = [bytes.fromhex(h) for h in entry["headers"]]
    if len(headers) != 6 or any(len(h) != 80 for h in headers):
        raise ValueError("Expected six consecutive 80-byte headers")
    if headers[0].hex() != entry["blockHeader"]:
        raise ValueError("First proof header is not the transaction block header")
    for previous, current in zip(headers, headers[1:]):
        if current[4:36] != dsha(previous):
            raise ValueError("Bitcoin header chain is not contiguous")


def merkle_branch(txids, tx_index):
    level = [bytes.fromhex(txid)[::-1] for txid in txids]
    index = tx_index
    branch = []
    while len(level) > 1:
        sibling = index ^ 1
        if sibling >= len(level):
            sibling = index
        branch.append(level[sibling].hex())
        next_level = []
        for i in range(0, len(level), 2):
            right = level[i + 1] if i + 1 < len(level) else level[i]
            next_level.append(dsha(level[i] + right))
        index //= 2
        level = next_level
    return "".join(branch), level[0]



def transaction_vectors(raw_hex, txid):
    raw = bytes.fromhex(raw_hex)
    version = raw[:4]
    offset = 4
    if raw[offset:offset + 2] == b"\x00\x01":
        raise ValueError("Regtest protocol transactions must use legacy inputs")

    input_start = offset
    input_count, offset = read_varint(raw, offset)
    if input_count != 1:
        raise ValueError("Expected exactly one transaction input")
    previous_tx_hash = raw[offset:offset + 32]
    previous_output_index = int.from_bytes(raw[offset + 32:offset + 36], "little")
    for _ in range(input_count):
        offset += 36
        script_len, offset = read_varint(raw, offset)
        offset += script_len + 4
    input_vector = raw[input_start:offset]

    output_start = offset
    output_count, offset = read_varint(raw, offset)
    if output_count != 1:
        raise ValueError("Expected exactly one transaction output")
    output_value = int.from_bytes(raw[offset:offset + 8], "little")
    for _ in range(output_count):
        offset += 8
        script_len, offset = read_varint(raw, offset)
        offset += script_len
    output_vector = raw[output_start:offset]
    locktime = raw[-4:]

    return {
        "txInfo": {
            "version": "0x" + version.hex(),
            "inputVector": "0x" + input_vector.hex(),
            "outputVector": "0x" + output_vector.hex(),
            "locktime": "0x" + locktime.hex(),
        },
        "outputValue": output_value,
        "txHashInternal": "0x" + dsha(raw).hex(),
        "firstInput": {
            "txHash": "0x" + previous_tx_hash.hex(),
            "txOutputIndex": previous_output_index,
        },
    }

def build(entry):
    txids = entry["blockTxids"]
    txid = entry["txid"]
    if transaction_id(entry["rawTransaction"]) != txid:
        raise ValueError("Raw transaction does not hash to the supplied txid")
    validate_header_chain(entry)
    coinbase_txid = entry["coinbaseTxid"]
    tx_index = txids.index(txid)
    if coinbase_txid not in txids:
        raise ValueError("Coinbase txid is missing from the block transaction list")
    coinbase_index = txids.index(coinbase_txid)

    tx_proof, root = merkle_branch(txids, tx_index)
    coinbase_proof, coinbase_root = merkle_branch(txids, coinbase_index)
    header = bytes.fromhex(entry["blockHeader"])
    if len(header) != 80 or root != header[36:68] or coinbase_root != header[36:68]:
        raise ValueError("Merkle branch does not match the block header root")
    headers = entry["headers"]
    entry["spvProof"] = {
        "merkleProof": tx_proof,
        "txIndexInBlock": tx_index,
        "bitcoinHeaders": "".join(headers),
        "coinbasePreimage": coinbase_preimage(entry["coinbaseRawTransaction"]),
        "coinbaseProof": coinbase_proof,
    }
    tx_vectors = transaction_vectors(entry["rawTransaction"], txid)
    entry["txInfo"] = tx_vectors["txInfo"]
    entry["outputValue"] = tx_vectors["outputValue"]
    if "sourceMainUtxoValue" in entry:
        entry["sourceMainUtxo"] = {
            **tx_vectors["firstInput"],
            "txOutputValue": entry["sourceMainUtxoValue"],
        }
        del entry["sourceMainUtxoValue"]


def main(path):
    with open(path, "r", encoding="utf-8") as fixture:
        data = json.load(fixture)
    build(data["movingFunds"])
    build(data["sweep"])
    with open(path, "w", encoding="utf-8") as fixture:
        json.dump(data, fixture, indent=2)
        fixture.write("\n")
    print("SPV proof fields generated and Merkle roots verified against block headers")


if __name__ == "__main__":
    main(sys.argv[1])
