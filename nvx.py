#!/usr/bin/python
import asyncio
import errno
import json
import os
import subprocess
import sys
import time
from typing import Any, Callable


def _collect(
    value: Any,
    produce: Callable[[Any], list[Any]],
    predicate: Callable[[Any], bool],
    transform: Callable[[Any], Any],
    collector: list[Any],
):
    """
    Collect `value` if it satisfies `predicate` and `produce` more elements from it to be collected.

    - `value`: value to be checked and collected if `predicate` is satisfied
    - `predicate`: function to check if `value` should be collected
    - `produce`: function to produce more elements from `value` to be collected
    - `transform`: function to transform `value` before it is collected
    - `collector`: list to collect satisfied `value`s

    - returns: `collector`
    """
    predicate(value) and collector.append(transform(value))
    for child in produce(value):
        _collect(child, produce, predicate, transform, collector)
    return collector


def devices():
    """
    Return nvidia devices and their PCIs data in a JSON object produced by the `lshw` command.
    """
    disables = ["cpuinfo", "device-tree", "dmi", "ide", "isapnp", "memory", "network", "pcmcia", "scsi", "spd", "usb"]
    classes = ["bridge", "display"]
    lshw = subprocess.run(
        [
            "lshw",
            "-json",
            *[arg for disable in disables for arg in ("-disable", disable)],
            *[arg for class_ in classes for arg in ("-class", class_)],
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    devices = _collect(
        json.loads(lshw.stdout),
        lambda x: x if type(x) == list else x.get("children", []) if type(x) == dict else [],
        lambda x: type(x) == dict and x.get("class") == "bridge",
        lambda x: {
            **x,
            "children": [
                c for c in x.get("children", []) if c.get("class") == "display" and "NVIDIA" in c.get("vendor", "")
            ],
        },
        [],
    )
    return [device for device in devices if len(device.get("children")) > 0]


def _pid_exists(pid: int):
    if pid == 0:
        return True
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            return False
        elif err.errno == errno.EPERM:
            return True
        else:
            raise err
    else:
        return True


def _wait_for_process(pid: int):
    while _pid_exists(pid):
        time.sleep(10)


def processes(ctl: bool = False):
    """
    List processes using files provided by the nvidia driver.

    - `ctl`: whether to list processes using only the nvidia driver"s control file (/dev/nvidiactl).

    - returns: list of processes
    """
    lsof = subprocess.run("lsof /dev/nvidia*", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    processes = [
        {"name": p[0].decode(), "pid": int(p[1]), "file": p[-1].decode()}
        for p in (l.split() for l in lsof.stdout.splitlines()[1:])
        if ctl or p[-1] != b"/dev/nvidiactl"
    ]
    return [*{process["pid"]: process for process in processes}.values()]


def kill():
    print("# kill processes")
    ps = processes(ctl=True)
    if not len(ps):
        print("-- no processes found")
    for process in ps:
        print(f"-- kill process {process['name']} -> {process['pid']}")
        subprocess.run(["kill", str(process["pid"])])


def turn_on():
    """
    Turn on the nvidia card.
    """
    print("# turn on\n-- pci rescan")
    with open("/sys/bus/pci/rescan", "w") as f:
        f.write("1")
    for pci in devices():
        name = f"{pci['description']} - {pci['product']}"
        bus = pci["businfo"][4:]
        print(f"-- pci {name} {bus}\n   -- pci power control on")
        with open(f"/sys/bus/pci/devices/{bus}/power/control", "w") as f:
            f.write("on")
        for device in pci["children"]:
            name = f"{device['description']} - {device['product']}"
            bus = device["businfo"][4:]
            print(f"   -- device enable {name} -> {bus}")
            with open(f"/sys/bus/pci/devices/{bus}/power/control", "w") as f:
                f.write("on")


def turn_off():
    """
    Turn off the nvidia card.
    """
    print("# turn off")
    for pci in devices():
        for device in pci["children"]:
            name = f"{device['description']} - {device['product']}"
            bus = device["businfo"][4:]
            print(f"   -- device remove {name} -> {bus}")
            with open(f"/sys/bus/pci/devices/{bus}/remove", "w") as f:
                f.write("1")
        name = f"{pci['description']} - {pci['product']}"
        bus = pci["businfo"][4:]
        print(f"-- pci {name} {bus}\n   -- pci power control auto")
        with open(f"/sys/bus/pci/devices/{bus}/power/control", "w") as f:
            f.write("auto")


def toggle_modules(load: bool, modules: list[str]):
    """
    Toggle kernel `modules` using the `modprobe` command.
    If `load` is `True`, load the modules, otherwise unload them.

    - `load`: whether to load or unload the modules.
    - `modules`: list of modules to be loaded or unloaded in order.
    """
    print(f"# toggle {['load' if load else 'unload']} modules")
    for module in modules:
        print(f"-- module {module}")
        subprocess.run(["modprobe", *([] if load else ["--remove"]), module])


modules = ["nvidia", "nvidia_uvm", "nvidia_modeset", "nvidia_drm"]


async def daemon():
    """
    A
    """
    keep_on = False
    loop = asyncio.get_event_loop()

    async def callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        (action, *arguments) = (await reader.read(-1)).decode().split()
        threaded = False
        match action:
            case "dev":
                writer.write(json.dumps(devices(), indent=4).encode())
            case "status":
                writer.write(b"on" if len(devices()) else b"off")
            case "ps":
                writer.write(json.dumps(processes(), indent=4).encode())
            case "psa":
                writer.write(json.dumps(processes(True), indent=4).encode())
            case "kill":
                kill()
                writer.write(b"done")
            case "on":
                keep_on = True
                turn_on()
                toggle_modules(True, modules)
                writer.write(b"done")
            case "off":
                keep_on = False
                threaded = True
                toggle_modules(False, modules[::-1])
                loop.run_in_executor(None, turn_off)
                writer.write(b"done")
            case "off-kill":
                kill()
                toggle_modules(False, modules[::-1])
                turn_off()
                writer.write(b"done")
            case "notify":

                pid = int(arguments[0])
                print("-- notify")
            case _:
                pass

        if not threaded:
            writer.write_eof()
            await writer.drain()
            writer.close()

    server = await asyncio.start_unix_server(callback, path="/tmp/nvx.socket")
    os.chmod("/tmp/nvx.socket", 0o777)
    print(f"# server started at {server.sockets[0].getsockname()}")
    async with server:
        await server.serve_forever()


async def proxy(action: str, arguments: list[str]):
    reader, writer = await asyncio.open_unix_connection("/tmp/nvx.socket")
    writer.write(f"{action} {' '.join(arguments)}".strip().encode())
    writer.write_eof()
    while not reader.at_eof():
        sys.stdout.buffer.write(await reader.read(256))


action = sys.argv[1] or "help"
arguments = sys.argv[2:]

match action:
    case "boot":
        turn_off()
        asyncio.run(daemon())
    case "daemon":
        asyncio.run(daemon())
    case "start":
        asyncio.run(proxy(action, [str(os.getpid())]))
        subprocess.run(arguments)
    case _:
        asyncio.run(proxy(action, []))

print('end')
