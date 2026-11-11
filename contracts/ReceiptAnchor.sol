// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.26;

/// Records that a Merkle root of receipt digests existed at a given time.
/// Holds hashes and timestamps only. A root can be written once and never altered, and
/// only the operator address set at deployment may write.
contract ReceiptAnchor {
    struct Anchor {
        uint64 timestamp;
        uint64 blockNumber;
    }

    address public immutable operator;
    mapping(bytes32 => Anchor) public anchors;

    event Anchored(bytes32 indexed root, uint32 leafCount, uint64 timestamp);

    constructor() {
        operator = msg.sender;
    }

    function anchor(bytes32 root, uint32 leafCount) external {
        require(msg.sender == operator, "not operator");
        require(root != bytes32(0), "empty root");
        require(anchors[root].timestamp == 0, "already anchored");
        anchors[root] = Anchor(uint64(block.timestamp), uint64(block.number));
        emit Anchored(root, leafCount, uint64(block.timestamp));
    }
}
