# TEST LEDGER ONLY. All three validator keys are generated at build time and live in one
# image, which is what makes it runnable with one command and useless as a real ledger.
# In a pilot each custodian generates its own key and runs its own node.
FROM hyperledger/besu:24.12.2
COPY deploy/besu/qbft-config.json /opt/besu-setup/qbft-config.json
COPY deploy/besu/start.sh /opt/besu-setup/start.sh
USER root
RUN besu operator generate-blockchain-config \
      --config-file=/opt/besu-setup/qbft-config.json \
      --to=/opt/besu-setup/network --private-key-file-name=key \
    && chmod -R a+rX /opt/besu-setup
ENTRYPOINT ["sh", "/opt/besu-setup/start.sh"]
