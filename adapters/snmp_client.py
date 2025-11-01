# adapters/snmp_client.py
from __future__ import annotations
import asyncio
import inspect
import socket
from typing import Any
from puresnmp import Client, V2C, PyWrapper
from puresnmp.exc import Timeout as SnmpTimeout  # <-- important
from settings.logging_setup import flog

DEFAULT_TIMEOUT = 6.0
DEFAULT_RETRIES = 10

_BAD_HOSTS = {"", "-", "n/a", "na", "none", "0.0.0.0"}


def _is_bad_host(host: str) -> bool:
    return host.strip().lower() in _BAD_HOSTS


def make_snmp(host: str, community: str = "public", timeout: float | None = None) -> PyWrapper | None:
    if _is_bad_host(host):
        return None
    client = Client(host, V2C(community))
    client.configure(timeout=timeout or DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES)
    return PyWrapper(client)


async def _collect_async_walk(async_gen) -> list[Any]:
    rows = []
    async for vb in async_gen:
        rows.append(vb)
    return rows


def walk_oid(host: str, base_oid: str, *, community: str = "public", timeout: float | None = None):
    """
    Yield (oid, value) pairs.
    - if puresnmp.walk(...) is async → run it and yield rows
    - if it's sync → just iterate
    - if target doesn't answer / times out → log + yield nothing
    """
    snmp = make_snmp(host, community, timeout)
    if snmp is None:
        return

    try:
        walk_obj = snmp.walk(base_oid)
    except (ValueError, socket.gaierror, OSError) as e:
        flog(f"[SNMP] {host}: failed to start walk on {base_oid}: {e}")
        return

    # async case
    if inspect.isasyncgen(walk_obj):
        try:
            vbs = asyncio.run(_collect_async_walk(walk_obj))
        except (SnmpTimeout, asyncio.TimeoutError, asyncio.CancelledError) as e:
            flog(f"[SNMP] {host}: walk timeout on {base_oid}: {e}")
            return
        except RuntimeError:
            # if already in an event loop
            loop = asyncio.new_event_loop()
            try:
                vbs = loop.run_until_complete(_collect_async_walk(walk_obj))
            except (SnmpTimeout, asyncio.TimeoutError, asyncio.CancelledError) as e:
                flog(f"[SNMP] {host}: walk timeout on {base_oid}: {e}")
                return
            finally:
                loop.close()

        for vb in vbs:
            yield vb.oid, vb.value
        return

    # sync case
    try:
        for vb in walk_obj:
            yield vb.oid, vb.value
    except (SnmpTimeout, ValueError, socket.gaierror, OSError) as e:
        flog(f"[SNMP] {host}: walk failed on {base_oid}: {e}")
        return


def get_scalar(host: str, oid: str, *, community: str = "public", timeout: float | None = None):
    snmp = make_snmp(host, community, timeout)
    if snmp is None:
        return None
    try:
        return snmp.get(oid)
    except (SnmpTimeout, ValueError, socket.gaierror, OSError) as e:
        flog(f"[SNMP] {host}: get {oid} failed: {e}")
        return None
