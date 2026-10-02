#!/usr/bin/env python3
"""Tiny HTTP/HTTPS forward proxy. Point a device's Wi-Fi "Manual proxy" at this Mac."""
import asyncio
import sys
from urllib.parse import urlsplit

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8888


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(creader, cwriter):
    peer = cwriter.get_extra_info("peername")[0]
    try:
        head = await creader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        cwriter.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    method, target, version = lines[0].split(" ", 2)

    if method == "CONNECT":
        host, _, port = target.rpartition(":")
        port = int(port)
    else:
        url = urlsplit(target)
        host, port = url.hostname, url.port or 80
    print(f"{peer} {method} {host}:{port}", flush=True)

    try:
        ureader, uwriter = await asyncio.wait_for(asyncio.open_connection(host, port), 30)
    except Exception as e:
        print(f"  ! {host}:{port} {e}", flush=True)
        cwriter.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await cwriter.drain()
        cwriter.close()
        return

    if method == "CONNECT":
        cwriter.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await cwriter.drain()
    else:
        # Rewrite absolute URI to origin form and force one request per connection,
        # so a kept-alive client never sends a second host's request down this pipe.
        path = url.path or "/"
        if url.query:
            path += "?" + url.query
        headers = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-connection:", "connection:"))]
        out = f"{method} {path} {version}\r\n" + "\r\n".join(headers) + "\r\nConnection: close\r\n\r\n"
        uwriter.write(out.encode("latin-1"))
        await uwriter.drain()

    await asyncio.gather(pipe(creader, uwriter), pipe(ureader, cwriter))


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    print(f"proxy listening on 0.0.0.0:{PORT}", flush=True)
    async with server:
        await server.serve_forever()


asyncio.run(main())
