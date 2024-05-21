#!/usr/bin/python

from typing import Any, NamedTuple
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys


VERSION = "0.2.1"
LOGGER_PATH = "/var/log/nvx.log"
CONFIG_PATH = "/etc/nvx.conf"
UNIX_SOCKET = "/tmp/nvx.sock"

log = logging.getLogger()
log.setLevel(logging.INFO)
if len(sys.argv) == 2 and sys.argv[1] == "daemon":
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(stream_handler)
    file_handler = logging.FileHandler(LOGGER_PATH)
    file_handler.setFormatter(logging.Formatter("%(asctime)s: %(levelname)s %(message)s"))
    log.addHandler(file_handler)


class Config:
    KERNEL_MODULES_BASE = ["nouveau", "nvidia", "nvidia_drm", "nvidia_uvm", "nvidia_modeset"]
    DEVICE_CLASSES_BASE = ["display"]
    DEVICE_VENDORS_BASE = ["nvidia"]
    kernel_modules: list[str]
    device_classes: list[str]
    device_vendors: list[str]

    def __init__(self):
        log.info(f"init config")
        try:
            with open(CONFIG_PATH, "r") as config_file:
                lines = config_file.readlines()
        except Exception as e:
            log.warning(f"could not open config {CONFIG_PATH} - {e}")
            lines: list[str] = []
        lines = [line.strip().lower() for line in lines]
        lines = [line for line in lines if len(line) > 0 and not line.startswith("#")]
        config = {line.split("=")[0]: line.split("=")[1].split(",") for line in lines}
        self.kernel_modules = [*self.KERNEL_MODULES_BASE, *config.get("KERNEL_MODULES", [])]
        self.device_classes = [*self.DEVICE_CLASSES_BASE, *config.get("DEVICE_CLASSES", [])]
        self.device_vendors = [*self.DEVICE_VENDORS_BASE, *config.get("DEVICE_VENDORS", [])]
        log.info(f"kernel modules: {self.kernel_modules}")
        log.info(f"device classes: {self.device_classes}")
        log.info(f"device vendors: {self.device_vendors}")

    def load_modules_sequence(self) -> list[str]:
        return [module for module in self.kernel_modules if module != "nouveau"]

    def unload_modules_sequence(self) -> list[str]:
        return self.kernel_modules[::-1]

    def match_device(self, device: dict[str, Any]) -> bool:
        class_: str = device.get("class", "").lower()
        vendor: str = device.get("vendor", "").lower()
        return class_ in self.device_classes and any(v in vendor for v in self.device_vendors)


class Device(NamedTuple):
    name: str
    bus: str
    bridge: str
    bridge_bus: str


class Devices:
    def __init__(self, config: Config):
        self.config = config

    def list_devices(self) -> list[Device]:
        log.info(f"list devices")
        lshw_cmd = """
        lshw -json \
            -disable cpuid -disable cpuinfo -disable device-tree -disable dmi -disable ide -disable isapnp \
            -disable memory -disable network -disable pcmcia -disable scsi -disable spd -disable usb \
        """
        lshw = subprocess.run(lshw_cmd, shell=True, capture_output=True)
        if lshw.returncode != 0:
            log.warning(f"lshw error {lshw.returncode} stderr: {lshw.stderr}")
            return []

        def find(parent: dict[str, Any] | None, child: dict[str, Any], matches: list[Device]):
            if parent is not None and self.config.match_device(child):
                matches.append(
                    Device(
                        name=f"{child['vendor']} - {child['product']}",
                        bus=child["businfo"][4:],
                        bridge=f"{parent['vendor']} - {parent['product']}",
                        bridge_bus=parent["businfo"][4:],
                    )
                )
            if "children" in child:
                for grandchild in child["children"]:
                    find(child, grandchild, matches)
            return matches

        devices = find(None, json.loads(lshw.stdout), [])
        log.info(f"devices: {devices}")
        return devices

    def pci_rescan(self):
        log.info(f"pci rescan")
        with open("/sys/bus/pci/rescan", "w") as f:
            f.write("1")

    def turn_on(self):
        log.info(f"turn on devices")
        self.pci_rescan()
        for device in self.list_devices():
            log.info(f"setting power control {device.bridge} - {device.bridge_bus}")
            with open(f"/sys/bus/pci/devices/{device.bridge_bus}/power/control", "w") as f:
                f.write("on")
            log.info(f"turning on device {device.name} - {device.bus}")
            with open(f"/sys/bus/pci/devices/{device.bus}/power/control", "w") as f:
                f.write("on")

    def turn_off(self):
        log.info(f"turn off devices")
        for device in self.list_devices():
            log.info(f"turning off device {device.name} - {device.bus}")
            with open(f"/sys/bus/pci/devices/{device.bus}/remove", "w") as f:
                f.write("1")
            log.info(f"setting power control {device.bridge} - {device.bridge_bus}")
            with open(f"/sys/bus/pci/devices/{device.bridge_bus}/power/control", "w") as f:
                f.write("auto")

    def load_modules(self):
        log.info("load modules")
        for module in self.config.unload_modules_sequence():
            result = subprocess.run(["modprobe", module], capture_output=True)
            if result.returncode == 0:
                log.info(f"load module {module}")
            else:
                log.warning(f"load module {module}: {result.returncode} - {result.stderr.decode('utf-8').strip()}")

    def unload_modules(self):
        log.info("unload modules")
        for module in self.config.unload_modules_sequence():
            result = subprocess.run(["modprobe", "--remove", module], capture_output=True)
            if result.returncode == 0:
                log.info(f"unload module {module}")
            else:
                log.warning(f"unload module {module}: {result.returncode}\n{result.stdout}\n{result.stderr}")

    def status(self):
        status = len(self.list_devices()) > 0 and "on" or "off"
        log.info(f"status: {status}")
        return status

    def ps(self):
        lsof = subprocess.run("lsof /dev/nvidia*", shell=True, capture_output=True)
        usages = lsof.stdout.decode("utf-8").splitlines()[1:]
        log.info(f"usages: {usages}")
        processes = {usage.split()[1]: usage.split()[0] for usage in usages}
        log.info(f"processes: {processes}")
        return processes

    def kill(self):
        processes = self.ps()
        for pid, name in processes.items():
            log.info(f"killing process {name} - {pid}")
            subprocess.run(["kill", pid])


class Daemon:
    running_processes = 0

    def __init__(self, config: Config, devices: Devices):
        self.config = config
        self.devices = devices

    def start(self):
        log.info("daemon init")
        try:
            os.remove(UNIX_SOCKET)
        except OSError as e:
            log.error(f"could not remove socket {UNIX_SOCKET} - {e}")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(UNIX_SOCKET)
        os.chmod(UNIX_SOCKET, 0o777)
        server.listen(1)
        log.info(f"server started at socket {UNIX_SOCKET}")
        while True:
            client, addr = server.accept()
            log.info(f"client connected {addr}")
            result = self.handler(client.recv(1024).decode("utf-8"))
            client.sendall(result.encode("utf-8"))

    def handler(self, command: str):
        log.info(f"daemon handler {command}")
        if command == "dev":
            return str(self.devices.list_devices())
        if command == "status":
            return self.devices.status()
        if command == "on":
            if self.running_processes > 0:
                return "busy"
            self.devices.turn_on()
            self.devices.load_modules()
            return self.devices.status()
        if command == "off":
            if self.running_processes > 0:
                return "busy"
            self.devices.kill()
            self.devices.unload_modules()
            self.devices.turn_off()
            return self.devices.status()
        if command == "ps":
            return str(self.devices.ps())
        if command == "kill":
            self.devices.kill()
            self.running_processes = 0
            return str(self.devices.ps())
        if command == "start":
            if self.running_processes == 0:
                self.devices.turn_on()
                self.devices.load_modules()
            self.running_processes += 1
            return self.devices.status()
        if command == "end":
            self.running_processes -= 1
            if self.running_processes == 0:
                self.devices.kill()
                self.devices.unload_modules()
                self.devices.turn_off()
            return self.devices.status()
        return "unknown command"


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "daemon":
        log.info(f"NVX {VERSION} config: {CONFIG_PATH} log: {LOGGER_PATH}")
        config = Config()
        devices = Devices(config)
        daemon = Daemon(config, devices)
        devices.turn_off()
        daemon.start()
    elif len(sys.argv) >= 2:
        action = sys.argv[1]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(UNIX_SOCKET)
        except Exception as e:
            print(f"could not connect to socket {UNIX_SOCKET} - {e}")
            raise e
        sock.sendall(action.encode("utf-8"))
        result = sock.recv(1024).decode("utf-8")
        if action != "start":
            print(result)
        else:
            command = " ".join(sys.argv[3:])
            env = os.environ.copy()
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            process = subprocess.Popen(
                command, shell=True, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, env=env
            )
            returncode = process.wait()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(UNIX_SOCKET)
            except Exception as e:
                print(f"could not connect to socket {UNIX_SOCKET} - {e}")
                raise e
            sock.sendall(b"end")
            sock.recv(1024).decode("utf-8")
            sys.exit(returncode)
    else:
        print(
            """
Usage: nvx [start|on|off|off-boot|off-kill|status|ps|psx|kill|dev]

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
