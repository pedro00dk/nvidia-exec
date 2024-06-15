#!/usr/bin/python

from typing import Any
import json
import logging as log
import os
import re
import socket
import subprocess
import sys


LOGGER_PATH = "/var/log/nvx.log"
CONFIG_PATH = "/etc/nvx.conf"
UNIX_SOCKET = "/tmp/nvx.sock"


log.basicConfig(
    level=log.DEBUG,
    encoding="utf-8",
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[log.StreamHandler(), log.FileHandler(LOGGER_PATH, delay=True)],
)


def read(path: str):
    """
    Shorthand for reading a file and returning its lines as a list of strings.
    """
    try:
        with open(path, "r") as file:
            return file.read()
    except:
        log.warning(f"could not read file {path}")
        return ""


def write(path: str, content: str):
    """
    Shorthand for writing a string to a file.
    """
    with open(path, "w") as file:
        file.write(content)


class Config:
    """
    NVX configuration sourced from CONFIG_PATH.
    """

    def __init__(self, path: str):
        log.info(f"config init - path: {path}")
        lines = [line.strip() for line in read(path).splitlines() if len(line) > 0 and not re.match(r"^\s*#|^$", line)]
        config: dict[str, str] = {line[:line.index('=')]: line[line.index('=') + 1:].strip() for line in lines}
        self.kernel_modules = [v.strip() for v in config.get("kernel_modules", "").split(",")]
        self.device_classes = [v.strip() for v in config.get("device_classes", "").split(",")]
        self.device_vendors = [v.strip() for v in config.get("device_vendors", "").split(",")]
        self.egl_vendor_path = config.get("egl_vendor_path", "").strip()
        self.egl_vendor_apply = config.get("egl_vendor_apply", "") == "true"
        self.kill_on_off = config.get("kill_on_off", "") == "true"

    def __repr__(self):
        return f'{Config.__name__}({', '.join(f"{k}: {v}" for k, v in self.__dict__.items())})'

    def load_kernel_modules_sequence(self):
        return [module for module in self.kernel_modules if module != "nouveau"]

    def unload_kernel_modules_sequence(self):
        return [module.split()[0] for module in self.kernel_modules[::-1]]

    def match_device(self, device: dict[str, Any]):
        class_: str = device.get("class", "").lower()
        vendor: str = device.get("vendor", "").lower()
        return class_ in self.device_classes and any(v in vendor for v in self.device_vendors)

    def apply_egl_changes(self):
        if self.egl_vendor_path == "":
            return
        log.info("apply egl vendor override")
        target = read(self.egl_vendor_path)
        if self.egl_vendor_apply:
            target = target.replace('"ICD"', '"-ICD"')
        else:
            target = target.replace('"-ICD"', '"ICD"')
        write(self.egl_vendor_path, target)


class Pci:
    """
    PCI devices and processes manager.
    """

    class Device:
        name: str
        bus: str
        bridge: str

        def __repr__(self):
            return f'{Config.__name__}({', '.join(f"{k}: {v}" for k, v in self.__dict__.items())})'

    def __init__(self, config: Config):
        log.info("pci init")
        self.config = config

    def pci_rescan(self):
        log.info("pci rescan")
        write("/sys/bus/pci/rescan", "1")

    def pci_devices(self) -> list[Device]:
        log.info("pci devices")
        lshw_cmd = """
            lshw \
                -disable cpuid -disable cpuinfo -disable device-tree -disable dmi -disable isapnp -disable memory \
                -disable network -disable pcmcia -disable scsi -disable spd -disable usb \
                -json
        """
        result = subprocess.run(lshw_cmd, shell=True, capture_output=True)
        if result.returncode != 0:
            log.warning(f"lshw error - code: {result.returncode}, stderr: {result.stderr}")
            return []

        def find(parent: dict[str, Any] | None, child: dict[str, Any], matches: list[Pci.Device]):
            if parent is not None and self.config.match_device(child):
                device = Pci.Device()
                matches.append(device)
                device.name = f"{child['vendor']} - {child['product']}"
                device.bus = child["businfo"][4:]
                device.bridge = parent["businfo"][4:]
            for grandchild in child.get("children", []):
                find(child, grandchild, matches)
            return matches

        devices = find(None, json.loads(result.stdout), [])
        log.info(f"devices: {devices}")
        return devices

    def turn_on(self):
        log.info(f"turn on")
        self.pci_rescan()
        for device in self.pci_devices():
            log.info(f"turn on device {device.name} - {device.bus} - {device.bridge}")
            write(f"/sys/bus/pci/devices/{device.bridge}/power/control", "on")
            write(f"/sys/bus/pci/devices/{device.bus}/power/control", "on")

    def turn_off(self):
        log.info(f"turn off")
        for device in self.pci_devices():
            log.info(f"turn off device {device.name} - {device.bus} - {device.bridge}")
            write(f"/sys/bus/pci/devices/{device.bus}/remove", "1")
            write(f"/sys/bus/pci/devices/{device.bridge}/power/control", "auto")

    def load_modules(self):
        log.info("load modules")
        for module in self.config.unload_kernel_modules_sequence():
            log.info(f"load module {module}")
            result = subprocess.run(f"modprobe {module}", shell=True, capture_output=True)
            level = result.returncode == 0 and log.INFO or log.WARNING
            log.log(level, f"result: {result.returncode} {result.stderr}")

    def unload_modules(self):
        log.info("unload modules")
        for module in self.config.unload_kernel_modules_sequence():
            log.info(f"unload module {module}")
            result = subprocess.run(f"modprobe --remove {module}", shell=True, capture_output=True)
            level = result.returncode == 0 and log.INFO or log.WARNING
            log.log(level, f"result: {result.returncode} {result.stderr}")

    def status(self):
        status = len(self.pci_devices()) > 0 and "on" or "off"
        log.info(f"status: {status}")
        return status

    def ps(self):
        lsof = subprocess.run(f"lsof /dev/nvidia*", shell=True, capture_output=True)
        usages = lsof.stdout.decode("utf-8").splitlines()[1:]
        processes = {usage.split()[1]: usage.split()[0] for usage in usages}
        log.info(f"ps: {processes}")
        return processes

    def kill(self):
        processes = self.ps()
        for pid, name in processes.items():
            log.info(f"kill process {name} - {pid}")
            subprocess.run(f"kill {pid}", shell=True)


class Daemon:
    """
    NVX daemon that listens to commands on a unix socket.
    """

    def __init__(self, config: Config, pci: Pci):
        log.info("daemon init")
        self.config = config
        self.pci = pci
        self.started_processes = 0
        self.pci_callables = [p for p in dir(self.pci) if not p.startswith("__") and callable(getattr(self.pci, p))]

    def start(self):
        log.info("daemon start")
        try:
            os.remove(UNIX_SOCKET)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.error(f"could not remove {UNIX_SOCKET}")
            raise e
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(UNIX_SOCKET)
        os.chmod(UNIX_SOCKET, 0o777)
        server.listen(1)
        log.info(f"server started at {UNIX_SOCKET}")
        while True:
            client, addr = server.accept()
            log.info(f"client connected {addr}")
            client.sendall(self.handle(client.recv(1024).decode("utf-8")).encode("utf-8"))

    def handle(self, command: str):
        log.info(f"handle {command}")
        if command.startswith("__") and command[2:] in self.pci_callables:
            return str(getattr(self.pci, command[2:])())
        if command == "dev":
            return str(self.pci.pci_devices())
        if command == "status":
            return self.pci.status()
        if command == "on":
            if self.started_processes > 0:
                return "busy"
            self.pci.turn_on()
            self.pci.load_modules()
            return self.pci.status()
        if command == "off":
            if self.started_processes > 0:
                return "busy"
            if self.config.kill_on_off:
                self.pci.kill()
            self.pci.unload_modules()
            self.pci.turn_off()
            return self.pci.status()
        if command == "ps":
            return str(self.pci.ps())
        if command == "kill":
            self.pci.kill()
            self.started_processes = 0
            return str(self.pci.ps())
        if command == "start":
            self.handle("on")
            self.started_processes += 1
            return self.pci.status()
        if command == "end":
            self.started_processes = max(self.started_processes - 1, 0)
            self.handle("off")
            return self.pci.status()
        return "unknown"


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "daemon":
        log.info(f"NVX - config: {CONFIG_PATH}, log: {LOGGER_PATH}, socket: {UNIX_SOCKET}")
        config = Config(CONFIG_PATH)
        pci = Pci(config)
        daemon = Daemon(config, pci)
        log.info(f"NVX - config: {config}, pci: {pci}, daemon: {daemon}")
        config.apply_egl_changes()
        pci.turn_off()
        daemon.start()
        sys.exit()

    if len(sys.argv) >= 2:
        action = sys.argv[1]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(UNIX_SOCKET)
        except Exception as e:
            print(f"could not connect to {UNIX_SOCKET}")
            raise e
        sock.sendall(action.encode("utf-8"))
        result = sock.recv(1024).decode("utf-8")
        if action != "start":
            print(result)
            sys.exit()

        env = os.environ.copy()
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
        process = subprocess.run(" ".join(sys.argv[2:]), shell=True, env=env)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(UNIX_SOCKET)
        except Exception as e:
            print(f"could not connect to socket {UNIX_SOCKET}")
        sock.sendall("end".encode("utf-8"))
        sock.recv(1024).decode("utf-8")
        sys.exit(process.returncode)

    print(
        """
Usage: nvx [start|on|off|status|ps|kill|dev]

-- automatic gpu management:
    start [command]
        Turn on the gpu, load modules if necessary, and run [command].
        When [command] exits, the gpu is turned off if there are no other 'nvx start' processes.
        During turn off, processes using the gpu not started with 'nvx start' are killed.

-- manual gpu management
    on
        Turn on the gpu and load modules.
        If npx start is running, it is no-op.

    off
        Attempt to kill processes using the GPU, unload modules and turn off the gpu.
        If npx start is running, it is no-op.

    status
        Print the GPU status.

    ps
        Print the processes using the GPU.

    kill
        Attempt to kill processes using the GPU reported by nvx ps.

    dev
        Print the GPU related devices if the GPU is on.
"""
    )
    sys.exit(1)
