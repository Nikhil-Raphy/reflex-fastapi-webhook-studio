"""Tests for the replay guard that checks target addresses when a socket opens."""

from typing import TYPE_CHECKING, override

import httpcore
import pytest

from reflex_fastapi_webhook_studio.security.ssrf import GuardedBackend, TargetNotAllowedError, is_public, resolve

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.security.ssrf import Resolver


class FakeBackend(httpcore.AsyncNetworkBackend):  # pylint: disable=abstract-method  # The guard never asks it for Unix sockets.
    """A network backend that records where it connects, and fails for some addresses."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        """Start with no connections.

        Args:
            failing: Addresses that refuse.
        """
        self.connected: list[str] = []
        self.slept: list[float] = []
        self.failing = failing

    @override
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        """Record the address, then refuse or give a stream.

        Args:
            host: The address.
            port: Not used.
            timeout: Not used.
            local_address: Not used.
            socket_options: Not used.

        Returns:
            A stream that does nothing.

        Raises:
            httpcore.ConnectError: If the address is one that fails.
        """
        self.connected.append(host)
        if host in self.failing:
            msg = "refused"
            raise httpcore.ConnectError(msg)
        return httpcore.AsyncNetworkStream()

    @override
    async def sleep(self, seconds: float) -> None:
        """Record the wait.

        Args:
            seconds: How long.
        """
        self.slept.append(seconds)


def resolver_for(answers: dict[str, list[list[str]]]) -> Resolver:
    """Make a resolver that gives each host its next list of addresses.

    Args:
        answers: For each host, the lists to give, one per lookup.

    Returns:
        The resolver.
    """

    async def lookup(host: str, _port: int) -> list[str]:
        return answers[host].pop(0)

    return lookup


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2001:4860:4860::8888", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("0.0.0.0", False),  # noqa: S104  # The address under test.
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::1", False),
        ("::", False),
        ("fd00::1", False),
        ("fe80::1%eth0", False),
        ("::ffff:127.0.0.1", False),
        ("::ffff:169.254.169.254", False),
        ("2002:7f00:1::", False),
        ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),
    ],
)
def test_given_address_when_checked_then_only_public_ones_pass(address: str, public: bool) -> None:  # noqa: FBT001
    """Given an IPv4 or IPv6 address, when checked, then loopback, private, link-local and shared ones fail.

    IPv4 inside IPv6 (mapped, 6to4 and Teredo) is judged by the IPv4 address too.
    """
    # Given
    candidate = address
    # When
    result = is_public(candidate)
    # Then
    assert result is public


@pytest.mark.anyio
async def test_given_public_host_when_connecting_then_socket_goes_to_the_checked_address() -> None:
    """Given a host with one public address, when httpcore connects, then the socket opens to that address."""
    # Given
    inner = FakeBackend()
    guard = GuardedBackend(inner, resolver_for({"example.com": [["93.184.216.34"]]}))
    # When
    await guard.connect_tcp("example.com", 443)
    # Then
    assert inner.connected == ["93.184.216.34"]


@pytest.mark.anyio
@pytest.mark.parametrize("addresses", [["93.184.216.34", "10.0.0.1"], ["127.0.0.1"], ["::ffff:10.0.0.1"]])
async def test_given_any_private_address_when_connecting_then_refused_before_any_socket(addresses: list[str]) -> None:
    """Given a host where any address is not public, when httpcore connects, then it is refused with no socket."""
    # Given
    inner = FakeBackend()
    guard = GuardedBackend(inner, resolver_for({"mixed.test": [addresses]}))
    # When
    with pytest.raises(TargetNotAllowedError, match="target address not allowed"):
        await guard.connect_tcp("mixed.test", 80)
    # Then
    assert not inner.connected


@pytest.mark.anyio
async def test_given_dns_rebinding_when_second_connect_resolves_private_then_it_is_refused() -> None:
    """Given a name that resolves public, then private, when it connects twice, then the second connect is refused."""
    # Given
    inner = FakeBackend()
    guard = GuardedBackend(inner, resolver_for({"rebind.test": [["93.184.216.34"], ["127.0.0.1"]]}))
    await guard.connect_tcp("rebind.test", 80)
    # When
    with pytest.raises(TargetNotAllowedError):
        await guard.connect_tcp("rebind.test", 80)
    # Then
    assert inner.connected == ["93.184.216.34"]


@pytest.mark.anyio
async def test_given_first_address_refuses_when_connecting_then_next_checked_address_is_tried() -> None:
    """Given two public addresses where the first refuses, when connecting, then the second is used."""
    # Given
    inner = FakeBackend(failing=frozenset({"93.184.216.34"}))
    guard = GuardedBackend(inner, resolver_for({"two.test": [["93.184.216.34", "93.184.216.35"]]}))
    # When
    await guard.connect_tcp("two.test", 80)
    # Then
    assert inner.connected == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.anyio
async def test_given_unreachable_or_unknown_host_when_connecting_then_connect_error() -> None:
    """Given a host whose addresses all refuse, or one with no address, when connecting, then a connect error rises."""
    # Given
    inner = FakeBackend(failing=frozenset({"93.184.216.34"}))
    guard = GuardedBackend(inner, resolver_for({"down.test": [["93.184.216.34"]], "none.test": [[]]}))
    # When / Then
    with pytest.raises(httpcore.ConnectError) as down:
        await guard.connect_tcp("down.test", 80)
    with pytest.raises(httpcore.ConnectError) as none:
        await guard.connect_tcp("none.test", 80)
    assert not isinstance(down.value, TargetNotAllowedError)
    assert "no address" in str(none.value)


@pytest.mark.anyio
async def test_given_lookup_fails_when_connecting_then_connect_error() -> None:
    """Given a resolver that fails, when connecting, then a connect error rises and no socket opens."""

    # Given
    async def failing(_host: str, _port: int) -> list[str]:
        raise OSError

    inner = FakeBackend()
    guard = GuardedBackend(inner, failing)
    # When / Then
    with pytest.raises(httpcore.ConnectError, match="Could not look up"):
        await guard.connect_tcp("broken.test", 80)
    assert not inner.connected


@pytest.mark.anyio
async def test_given_unix_socket_or_wait_when_asked_then_socket_refused_and_wait_passed_on() -> None:
    """Given the guard, when asked for a Unix socket or to wait, then the socket is refused and the wait passed on."""
    # Given
    inner = FakeBackend()
    guard = GuardedBackend(inner)
    # When
    with pytest.raises(TargetNotAllowedError):
        await guard.connect_unix_socket("/run/docker.sock")
    await guard.sleep(0.5)
    # Then
    assert inner.slept == [0.5]


@pytest.mark.anyio
async def test_given_ip_literal_when_resolved_then_it_comes_back_once() -> None:
    """Given an IP address as the host, when resolved by the system resolver, then that address comes back once."""
    # Given
    host = "127.0.0.1"
    # When
    addresses = await resolve(host, 80)
    # Then
    assert addresses == ["127.0.0.1"]
