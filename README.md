# dm36x-packager

This program takes as input a bootloader, u-boot image and root filesystem for a Texas Instruments DM36x-based board and creates a firmware update package. The package is intended for SDCard or eMMC-based boards, but could be modified for other types of persistent memory.

## Theory of operation

The packager assumes a target embedded system where the general mode for
software update is to flash a new root filesystem. This is different from using
a package manager for updates and is intended for small to medium sized
embedded systems that don't need fine grain granularity on what is installed.
In many cases, firmware updates are tested as one whole piece, and it is highly
desirable that the root filesystem bits on deployed systems match those that
were tested.

This update model implies that the root filesystem isn't modified when deployed
or any modifications can be overwritten. Moving user settings off the root
filesystem is not hard to do.

At a high level, the packager bundles the bootloaders, root filesystem, and
update logic needed to flash the firmware to the target hardware. The output is
a normal zip file with the extension .fw. Normal use only updates the root
filesystem, but it is possible to flash the bootloaders if needed. The firmware
update file is itself a shell script that contains all of the logic to flash
the media on the system. This has both the advantage and disadvantage of being
extremely flexible.

While the naive approach of having the target flash the root filesystem that it
is currently running off of won't work, there are other options. Due to the
large size of SDCards and eMMC, this program assumes a system that contains two
copies of the root filesystem. This has the added advantage that the firmware
update can complete the flashing of the root filesystem and then switch which
one gets loaded on the next boot at the very last operation. This minimizes the
time that a system could be bricked by a poorly timed power failure. The
packager updates the Master Boot Record (MBR) to perform the switch. This may
seem scary, but it so far is the simplest way (one write operation/no scripts)
that I've found to make u-boot and Linux switch which root file system it uses.
The kernel image (uImage) is stored in the /boot partition of the root
filesystem.

The program also can create a raw image file (.img) that is suitable for a bulk
programmer. This file is a binary dump of the parts of the firmware that must
be written to the SDCard. It only zeros out the beginning of the working
partition so that the firmware can detect that it must be formated. This is to
save time when running the bulk programmer as the entire SDCard does not need
to be written.

## SDCard/eMMC Layout

The primary bootloader (RBL) on DM36x devices dictates some of the Flash
layout. This program has made additional choices. Actual Flash offsets are in
config.h. The following table is the general layout:

    |---------------------|
    | MBR                 |
    |---------------------|
    | UBL signature       |
    |---------------------|
    | U-boot signature    |
    |---------------------|
    | U-boot environment  |
    |---------------------|
    | UBL                 |
    |---------------------|
    | U-boot              |
    |---------------------|
    | Root filesystem A   |
    |---------------------|
    | Root filesystem B   |
    |---------------------|
    | Debug partition     |
    |---------------------|
    | Working partition   |
    |---------------------|
    
The working and debug partitions can be used however the firmware application
wants. The packager only uses their offsets to build the MBR and to erase them
when formatting the entire image. In my use, the working partition is mounted
in /mnt on the device and is where all application-specific files are stored.
The debug partition is mounted on the device's /root so that it's easy to store
test programs, logs, and other files during debug sessions.

## Firmware update packager command line

The following options are supported:

    -f,--fwfile=path      Output path for firmware file
    -g,--imgfile=path     Output path for raw image file
    -v,--version=string   Version to embed into the firmware file
    -c,--config=path      Path to memory map configuration file
    -s,--ubl=path         Path to UBL binary
    -u,--uboot=path       Path to U-Boot binary
    -r,--rootfs=path      Path to Rootfs binary

The config, ubl, uboot, and rootfs paths are all required. Either or both the
--fwfile and --imgfile options should be passed to create a .fw file or a raw
.img file.  

## Installing a firmware update package

The firmware update package mostly knows how to update the system thanks
to the embedded shell script. To make the process easier, the fwupdate.sh
script can be used to extract and run the install script. A few additional
options are supported:

    -d destination
    -f fresh install
    -n show numeric progress
    -v print the firmware version

Examples:

    fwupdate.sh archive.fw -d /dev/mmcblock0 -n

This commandline would be run on the device to update /dev/mmcblock0 with the
new firmware. The update script will print out the numbers 1 to 100 to report
progress.

    fwupdate.sh archive.fw -d /dev/sdb -f

This commandline could be run on a PC with an SDCard attached via a USB reader.
It programs the entire contents of the SDCard. It is similar to programming the
card with the .img file. 

## To do

 1. Add support for signing firmware updates
 2. Add some safety mechanisms as running shell scripts as root on a PC is a little scary

