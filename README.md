# NVidia eXec - `nvx`

`nvx` is a script to run programs on Pascal and older (<= 10 series) nvidia optimus setups with power management. `nvx`
tries to be extremely simple to install and use, and supports both Xorg and Wayland environments.

Note: This script is highly experimental and require very recent versions of nvidia drivers and gnome patches to work.

## Usage

The script requires `sudo` to toggle the GPU and modules. You might be asked to input your password before the program
starts (to initialize the device), and after the program finishes (to cleanup resources).

1. run `nvx start [program]`
2. that is it

`nvx start` may be called multiple times, its is only going to initialize the devices in the first call and clean
resources when the last call ends.

## All actions

-   automatic gpu management:

    -   `start [command]` - Turn on the gpu, load modules if necessary, and run [command]. When [command] exits, the gpu
        is turned off if there are no other 'nvx start' processes. During turn off, processes using the gpu not started
        with 'nvx start' are killed.

-   manual gpu management:

    -   `on` - Turn on the gpu and load modules. If the gpu is already started, it tries to turn on again it and reload
        all modules. Effectively, it does nothing.
    -   `off` - Unload modules and turn off the gpu. If the gpu is already off, it tries to turn off again it and unload
        all modules. Effectively, it does nothing. If there are processes using the gpu, the turn off process might hang
        indefinitely. Use 'nvx ps' to check with processes are running to finish them. 'nvx kill' can be used as well,
        but it might not be able to kill all processes.
    -   `off-boot` - Same as 'off', but it does not unload modules.
    -   `off-kill` - Same as 'off', but it also attempts to kill processes using the gpu.
    -   `status` - Print the status of the gpu.
    -   `ps` - Print the processes using the gpu.
    -   `psx` - Print 'nvx start' processes.
    -   `kill` - Attempts to kill all processes using the gpu. These are the same processes reported by 'nvx ps'.
    -   `dev` - Print the pci display devices that contain nvidia cards. Only works if the gpu is on.

## Installation

Currently, this package is only available for Arch Linux on the _Arch User Repository_.

Installing the package the package:

```shell
$ git clone https://aur.archlinux.org/nvidia-exec.git
$ cd nvidia-exec
$ makepkg -si
$ ...
```

You may also install the package using an AUR helper:

```shell
$ paru -Sa nvidia-exec
$ ...
$ # or
$ yay -Sa nvidia-exec
$ ...
$ # or whatever helper you might use
```

### After the installation

Once the package is installed, its systemd service must be enabled:

```
$ sudo systemctl enable nvx
```

The `nvx.service` prevents nvidia modules from loading and turn off the graphics card during boot.

It is not necessary to handle files, configurations, PCI buses, etc, all that is done automatically.

The `nvx.service` might still fail and hang indefinitely if there are other Nvidia service daemons enabled during boot
such as:

-   `nvidia-persistenced.service`
-   `nvidia-powerd.service`

Note that the following services do not run on boot are not likely to stop `nvx` from turning off the gpu.

-   `nvidia-hibernate.service`
-   `nvidia-resume.service`
-   `nvidia-suspend.service`

### Files and Dependencies

For other users that may want to create a package to their preferred systems, the following is where I place the files
on Arch Linux.

-   **nvx** -> _/usr/bin/nvx_ - Script that handles the gpu and run programs.
-   **nvx.service** -> _/usr/lib/systemd/system/nvx.service_ - Service that turns off gpu during boot.
-   **modprobe.conf** -> /usr/lib/modprobe.d/nvx.conf - Blacklisted modules.

Required dependencies:

-   **jq** - https://stedolan.github.io/jq/
-   **lshw** - https://linux.die.net/man/1/lshw
-   **lsof** - https://linux.die.net/man/8/lsof
-   **Nvidia proprietary drivers**
