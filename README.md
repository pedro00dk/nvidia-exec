# NVidia eXec - `nvx`

`nvx` is a script to run programs on nvidia prime setups with power management. `nvx` is simple to install and configure, and supports both Xorg and Wayland environments.

Note: `nvx` is experimental and require recent versions of nvidia drivers, gnome, and mesa patches to work.

## Installation

This package is currently only available for Arch Linux on the _Arch User Repository_.

Installing the package the package:

```shell
$ git clone https://aur.archlinux.org/nvidia-exec.git
$ cd nvidia-exec
$ makepkg -si
$ ...
```

### After the installation

Once the package is installed, the configuration file at `/etc/nvx.conf` can also be edited for extra tuning, such as adding extra devices and modules to load and unload. Refer to the configuration file for documentation on the available options.

The `nvx.service` should also be enabled, it prevents nvidia modules from loading and turn off the GPU during boot.

```shell
$ sudo systemctl enable nvx
```

### Other distributions

For users that may want to create a package for their preferred distributions, the following is where files are usually placed.

-   **nvx** -> _/usr/bin/nvx_ - Script that handles the gpu and run programs.
-   **nvx.service** -> _/usr/lib/systemd/system/nvx.service_ - Service that turns off gpu during boot.
-   **nvx-modprobe.conf** -> /usr/lib/modprobe.d/nvx.conf - Blacklisted modules.
-   **nvx-options.conf** -> /etc/nvx.conf - Tune nvx options.

The following dependencies are required:

-   **python**
-   **lshw** - https://linux.die.net/man/1/lshw
-   **lsof** - https://linux.die.net/man/8/lsof
-   **Nvidia proprietary drivers**

## Usage

Run `nvx start [program]`.

-   `start [command]`: Turn on the gpu, load modules if necessary, and run [command]. When [command] exits, the gpu is turned off if there are no other 'nvx start' processes. During turn off, processes using the gpu not started with 'nvx start' are killed.

-   `off`: Attempt to kill processes using the GPU, unload modules and turn off the gpu. If npx start is running, it is no-op.
-   `status`: Print the GPU status.
-   `ps`: Print the processes using the GPU.
-   `kill`: Attempt to kill processes using the GPU reported by nvx ps.
-   `dev`: Print the GPU related devices if the GPU is on.

### Examples

-   `nvx start bash`: Starts a new shell, and commands ran on it will run the GPU.
-   `nvx start %command%`: Turns on the GPU before starting a steam game.
    -   Some games don't work when started like this, starting steam with the GPU should work: `nvx start steam`

## Troubleshooting

### GPU is still turned on after system boot:

The `nvx.service` tries to turn off the GPU during the boot process. If there are other services trying to use the GPU at the same time, `nvx.service` is likely to hang and fail.

Most commonly, that will be caused by nvidia service daemons such as:

-   `nvidia-persistenced.service`
-   `nvidia-powerd.service`

These services can be disabled through systemd (e.g. `systemctl disable nvidia-persistenced.service`).

Note that the other nvidia services will not run during boot and do not need to be disabled:

-   `nvidia-hibernate.service`
-   `nvidia-resume.service`
-   `nvidia-suspend.service`

### GPU turn off process of `nvx start [program]` hangs:

#### Hangs due to other processes:

When a program is started using `nvx start [program]`, the GPU is enabled system-wide. Other processes might see that the GPU is enabled and start using the device.

When the program executed using `nvx start` stops. The script will try to kill all processes using the GPU in order to turn it off. Some programs might not get killed or reattach to the device files immediately after their processes using the GPU are killed, preventing the GPU from powering off.

You can check process using the GPU with the `nvx ps` command and attempt to kill them again with `nvx kill` or manually closing the applications.

#### Hangs with no apparent cause:

If the `nvx start` command hangs during GPU turn off and there are no other processes using the GPU, that might be caused by a `modeset=1` option set to the `nvidia-drm` kernel module. That option might be set in a file like `/etc/modprobe.d/nvidia.conf`, via GRUB or any other means to set kernel module parameters. By removing the `nvidia-drm modeset=1` parameter, the `nvx start` should stop hanging. `modeset=1` is also a default option on `/etc/nvx.conf` so it should also be removed in the configuration file.
