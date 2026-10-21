import asyncio
import json
import pytest
from desktop.discovery import start_discovery
from desktop.trust import TrustStore


class Probe(asyncio.DatagramProtocol):
    def __init__(self):
        self.responses = asyncio.Queue()
    def datagram_received(self, data, address):
        self.responses.put_nowait(json.loads(data))


@pytest.mark.asyncio
async def test_discovery_returns_identity_but_no_secret(tmp_path):
    trust = TrustStore(tmp_path / "trust.json")
    token = trust.allow("phone-1234", "手机")
    server = await start_discovery(trust.public_info(8765), host="127.0.0.1", port=0)
    transport, probe = await asyncio.get_running_loop().create_datagram_endpoint(Probe, local_addr=("127.0.0.1", 0))
    try:
        target = server.get_extra_info("sockname")
        transport.sendto(json.dumps({"kind": "bili_remote_discover", "version": 1, "nonce": "test-nonce-123"}).encode(), target)
        response = await asyncio.wait_for(probe.responses.get(), 1)
        assert response["computer_id"] == trust.computer_id
        assert response["nonce"] == "test-nonce-123"
        assert token not in json.dumps(response)
        assert "token" not in response
    finally:
        transport.close()
        server.close()


def test_trust_survives_restart_and_can_be_revoked(tmp_path):
    path = tmp_path / "trust.json"
    first = TrustStore(path)
    token = first.allow("phone-1234", "手机")
    second = TrustStore(path)
    assert second.computer_id == first.computer_id
    assert second.authenticate("phone-1234", token)
    assert not second.authenticate("another-phone", token)
    second.revoke_all()
    assert not TrustStore(path).authenticate("phone-1234", token)


@pytest.mark.asyncio
async def test_computer_broadcasts_without_phone_request_and_stops(tmp_path):
    trust = TrustStore(tmp_path / "trust.json")
    transport, probe = await asyncio.get_running_loop().create_datagram_endpoint(Probe, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    server = await start_discovery(trust.public_info(8765), host="127.0.0.1", port=0, announce_port=port)
    try:
        packet = await asyncio.wait_for(probe.responses.get(), 1)
        assert packet["announce"] is True
        assert packet["computer_id"] == trust.computer_id
        assert "pairing_code" not in packet and "token" not in packet
        server.close()
        await asyncio.sleep(0)
        assert server.task.done()
    finally:
        transport.close()
        server.close()
