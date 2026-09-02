#!/usr/bin/env bash
# Generate the mTLS material for a remote connector.
#
# The second VPS is the point of the exercise: connector C runs on separate hardware,
# reaches core across the public internet, and must prove who it is. A bearer token in
# an env var would not — anyone who reads a log or an image layer has it. A client
# certificate is bound to a key that never leaves the institution.
#
# This creates a private CA, a server certificate for core, and one client certificate
# per remote institution. The CA key is the crown jewel: it signs the identities core
# will trust. In deployment it lives offline, not on either VPS.
set -euo pipefail

CERT_DIR="${1:-deploy/certs}"
CORE_DOMAIN="${CORE_DOMAIN:-core.marsad.example}"
DAYS="${DAYS:-825}"

mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

echo "==> CA"
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS" -out ca.crt \
  -subj "/C=AE/O=MARSAD/OU=Federation CA/CN=MARSAD Federation CA" 2>/dev/null

echo "==> core server certificate for ${CORE_DOMAIN}"
openssl genrsa -out core.key 2048 2>/dev/null
openssl req -new -key core.key -out core.csr \
  -subj "/C=AE/O=MARSAD/OU=Core/CN=${CORE_DOMAIN}" 2>/dev/null
cat > core.ext <<EXT
subjectAltName = DNS:${CORE_DOMAIN}, DNS:core, DNS:localhost, IP:127.0.0.1
extendedKeyUsage = serverAuth
EXT
openssl x509 -req -in core.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out core.crt -days "$DAYS" -sha256 -extfile core.ext 2>/dev/null

for institution in "${@:2}"; do
  echo "==> client certificate for ${institution}"
  openssl genrsa -out "${institution}.key" 2048 2>/dev/null
  # CN carries the rotating pseudonym, never the firm's name. Core authorises on this.
  openssl req -new -key "${institution}.key" -out "${institution}.csr" \
    -subj "/C=AE/O=MARSAD/OU=Connector/CN=${institution}" 2>/dev/null
  cat > "${institution}.ext" <<EXT
extendedKeyUsage = clientAuth
EXT
  openssl x509 -req -in "${institution}.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "${institution}.crt" -days "$DAYS" -sha256 -extfile "${institution}.ext" 2>/dev/null
done

rm -f ./*.csr ./*.ext ./*.srl
chmod 600 ./*.key
echo "==> done: $(ls | tr '\n' ' ')"
