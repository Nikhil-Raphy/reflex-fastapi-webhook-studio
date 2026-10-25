"""Refuse replay connections to any address outside the public internet, checked when the socket opens."""

import asyncio
import ipaddress
import socket
from typing import TYPE_CHECKING, override

import httpcore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    type Resolver = Callable[[str, int], Awaitable[list[str]]]
    """Turns a host and port into IP addresses."""

NOT_ALLOWED = "target address not allowed"


class TargetNotAllowedError(httpcore.ConnectError):
    """The target host resolves to an address that a replay may not reach."""


async def resolve(host: str, port: int) -> list[str]:
    """Look up the IP addresses of a host.

    Args:
        host: A host name or IP address.
        port: The port, which the lookup needs.

    Returns:
        The addresses, in the order the resolver gave them, each once.
    """
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public(address: str) -> bool:
    """Check that an IP address belongs to the public internet.

    IPv6 forms that carry an IPv4 address inside (mapped, 6to4 and Teredo) are judged by the IPv4 address too.

    Args:
        address: The IP address, with an optional IPv6 scope.

    Returns:
        Whether every address it stands for is global.
    """
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    inner: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            inner.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            inner.append(ip.sixtofour)
        if ip.teredo is not None:
            inner.extend(ip.teredo)
    return all(each.is_global for each in inner)


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Resolves the host when httpcore connects, refuses unless every address is public, then connects to it.

    httpcore still passes the host name to TLS, so SNI and the certificate check use the name, not the address.
    Checking at connect time also defeats DNS rebinding, since no second lookup happens.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None, resolver: Resolver = resolve) -> None:
        """Wrap a network backend.

        Args:
            inner: The backend that opens sockets.
            resolver: Looks up addresses; tests pass a fake one.
        """
        self._inner = inner or httpcore.AnyIOBackend()
        self._resolve = resolver

    @override
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Open a TCP connection to a checked address of the host.

        Args:
            host: The host name or IP address.
            port: The port.
            timeout: The most seconds to spend connecting.
            local_address: The local address to bind, if any.
            socket_options: Socket options to set.

        Returns:
            The connection.

        Raises:
            TargetNotAllowedError: If any address of the host is not public.
            httpcore.ConnectError: If the host has no address or no address answers.
        """
        try:
            async with asyncio.timeout(timeout):
                addresses = await self._resolve(host, port)
        except (OSError, TimeoutError) as error:
            msg = f"Could not look up {host}."
            raise httpcore.ConnectError(msg) from error
        if not addresses:
            msg = f"{host} has no address."
            raise httpcore.ConnectError(msg)
        if not all(is_public(address) for address in addresses):
            raise TargetNotAllowedError(NOT_ALLOWED)
        failure: httpcore.ConnectError | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore.ConnectError as error:
                failure = error
        raise httpcore.ConnectError(str(failure)) from failure

    @override
    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Refuse, since a Unix socket is never on the public internet.

        Args:
            path: The socket path.
            timeout: Not used.
            socket_options: Not used.

        Raises:
            TargetNotAllowedError: Always.
        """
        raise TargetNotAllowedError(NOT_ALLOWED)

    @override
    async def sleep(self, seconds: float) -> None:
        """Wait, as the inner backend does.

        Args:
            seconds: How long to wait.
        """
        await self._inner.sleep(seconds)
