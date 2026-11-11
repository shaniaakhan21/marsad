#!/bin/sh
# Starts validator $NODE_INDEX (1 to 3) of the test network. Node 1 is the bootnode.
set -eu
keys=/opt/besu-setup/network/keys
node_dir=$(ls -d "$keys"/* | sort | sed -n "${NODE_INDEX}p")
boot_dir=$(ls -d "$keys"/* | sort | sed -n 1p)
boot_pub=$(sed 's/^0x//' "$boot_dir/key.pub")

set -- --genesis-file=/opt/besu-setup/network/genesis.json \
  --data-path=/var/lib/besu-data \
  --node-private-key-file="$node_dir/key" \
  --min-gas-price=0 \
  --p2p-host="$NODE_IP" --p2p-port=30303 \
  --rpc-http-enabled --rpc-http-host=0.0.0.0 --rpc-http-port=8545 \
  --rpc-http-api=ETH,NET,QBFT,WEB3 --host-allowlist='*' \
  --profile=ENTERPRISE

if [ "$NODE_INDEX" != "1" ]; then
  set -- "$@" --bootnodes="enode://${boot_pub}@${BOOT_IP}:30303"
fi
exec besu "$@"
