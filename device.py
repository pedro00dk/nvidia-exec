#!/usr/bin/python
import json
import subprocess
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
