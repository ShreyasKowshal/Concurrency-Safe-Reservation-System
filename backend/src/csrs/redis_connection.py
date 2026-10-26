"""Bound Redis DNS + TCP connection time; socket timeouts alone do not bound getaddrinfo."""

import ipaddress
import socket
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic

from redis.connection import Connection, SSLConnection


@dataclass
class Resolution:
    done: Event = field(default_factory=Event)
    addresses: list = field(default_factory=list)
    error: OSError | None = None


class BoundedResolver:
    """At most one OS DNS lookup per API client, even if the OS resolver stops responding.

    Waiters time out without spawning more blocked work. The lookup thread is a daemon,
    so shutdown never waits indefinitely on OS DNS. No executor queue accumulates work.
    Successful results are reused for one second and invalidated on TCP failure.
    """

    def __init__(self):
        self.lock = Lock()
        self.pending: Resolution | None = None
        self.cached_until = 0.0
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            self.cached_until = 0

    def invalidate(self):
        with self.lock:
            self.cached_until = 0

    def resolve(self, host, port, family, timeout):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return socket.getaddrinfo(
                host, port, family, socket.SOCK_STREAM, 0, socket.AI_NUMERICHOST
            )
        with self.lock:
            if self.closed:
                raise OSError("Redis resolver is closed")
            result = self.pending
            if result is None or (result.done.is_set() and monotonic() >= self.cached_until):
                result = Resolution()
                self.pending = result

                def lookup():
                    try:
                        result.addresses = socket.getaddrinfo(
                            host, port, family, socket.SOCK_STREAM
                        )
                    except OSError as error:
                        result.error = error
                    finally:
                        with self.lock:
                            if not result.error:
                                self.cached_until = monotonic() + 1
                        result.done.set()

                Thread(target=lookup, name="csrs-redis-dns", daemon=True).start()
        if not result.done.wait(timeout):
            raise TimeoutError("Redis DNS resolution timed out")
        if result.error:
            raise result.error
        return result.addresses


class BoundedConnection(Connection):
    """Keep redis-py's protocol, authentication and TLS behavior; bound its DNS/TCP step."""

    def __init__(self, *args, resolver: BoundedResolver, **kwargs):
        self.resolver = resolver
        super().__init__(*args, **kwargs)

    def _connect(self):
        deadline = monotonic() + self.socket_connect_timeout
        addresses = self.resolver.resolve(
            self.host, self.port, self.socket_type, self.socket_connect_timeout
        )
        failure = OSError("Redis DNS returned no addresses")
        for family, kind, protocol, _, address in addresses:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Redis connection deadline elapsed")
            connection = socket.socket(family, kind, protocol)
            try:
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if self.socket_keepalive:
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    for option, value in self.socket_keepalive_options.items():
                        connection.setsockopt(socket.IPPROTO_TCP, option, value)
                connection.settimeout(remaining)
                connection.connect(address)
                connection.settimeout(self.socket_timeout)
                return connection
            except OSError as error:
                failure = error
                connection.close()
        self.resolver.invalidate()
        raise failure


class BoundedSSLConnection(SSLConnection, BoundedConnection):
    """SSLConnection wraps bounded TCP using the original hostname for certificate checking."""
