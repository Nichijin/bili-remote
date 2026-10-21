import asyncio
import contextlib
import ipaddress
import json
import socket
import time

import psutil

DISCOVERY_PORT = 8766
ANNOUNCEMENT_PORT = 8767


def broadcast_addresses():
    result = {"255.255.255.255"}
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family == socket.AF_INET and entry.netmask and not entry.address.startswith("127."):
                with contextlib.suppress(ValueError):
                    result.add(str(ipaddress.IPv4Interface(f"{entry.address}/{entry.netmask}").network.broadcast_address))
    return result


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, info):
        self.info, self.transport = info, None
        self.last_reply = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        if len(data) > 1024:
            return
        try:
            request = json.loads(data)
            if not isinstance(request, dict) or request.get("kind") != "bili_remote_discover" or request.get("version") != 1:
                return
            nonce = request.get("nonce")
            if not isinstance(nonce, str) or not 8 <= len(nonce) <= 64:
                return
            now = time.monotonic()
            if now - self.last_reply.get(address, 0) < .2:
                return
            if len(self.last_reply) > 1024:
                self.last_reply.clear()
            self.last_reply[address] = now
            self.transport.sendto(json.dumps({**self.info, "nonce": nonce}, ensure_ascii=False).encode(), address)
        except (ValueError, UnicodeDecodeError):
            return


class DiscoveryService:
    def __init__(self, transport, info, host, announce_port):
        self.transport = transport
        self.info = info
        self.host = host
        self.announce_port = announce_port
        self.task = asyncio.create_task(self.announce())

    def get_extra_info(self, name):
        return self.transport.get_extra_info(name)

    async def announce(self):
        data = json.dumps({**self.info, "announce": True}, ensure_ascii=False).encode()
        try:
            while True:
                destinations = broadcast_addresses() if self.host == "0.0.0.0" else {self.host}
                for address in destinations:
                    try:
                        self.transport.sendto(data, (address, self.announce_port))
                    except OSError:
                        pass
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass

    def close(self):
        self.task.cancel()
        self.transport.close()


async def start_discovery(info, host="0.0.0.0", port=DISCOVERY_PORT, announce_port=ANNOUNCEMENT_PORT):
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(info), local_addr=(host, port), allow_broadcast=True)
    return DiscoveryService(transport, info, host, announce_port)
