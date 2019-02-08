#!/usr/bin/python
#
# DM36x firmware packaging utility
# (C) Copyright, LKC Technologies, Inc.
# 
# This script creates firmware update packages and images for TI
# DM36x-based platforms that boot off of SD/MMC cards.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import struct
import string
import getopt
import zipfile
import hashlib
import sys

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

BLOCK_SIZE = 512

class MBR(object):
    FS_TYPE_LINUX = 0x83
    FS_TYPE_FAT32 = 0x0b
    
    STORAGE_NUM_HEADS = 255
    STORAGE_NUM_SECTORS = 63
    
    def __init__(self):
        self.mbr = bytearray(512)
        
        # DiskID (supposed to be unique, but doesn't matter for firmware image
        self.mbr[440] = 0x11;
        self.mbr[441] = 0x22;
        self.mbr[442] = 0x33;
        self.mbr[443] = 0x44;
        
        # MBR signature
        self.mbr[510] = 0x55;
        self.mbr[511] = 0xaa;
        
    def lba_to_head(self, x):
        return (x / self.STORAGE_NUM_SECTORS) % self.STORAGE_NUM_HEADS
    
    def lba_to_sector(self, x):
        return ((x % self.STORAGE_NUM_SECTORS) + 1)
    
    def lba_to_cylinder(self, x):
        return x / (self.STORAGE_NUM_SECTORS * self.STORAGE_NUM_HEADS)
    
    def lba_to_chs(self, x):
        return (self.lba_to_cylinder(x), self.lba_to_head(x), self.lba_to_sector(x))
    
    def calc_partition(self, mbr_offset, start, count, type):
        start_chs = self.lba_to_chs(start)
        last_chs = self.lba_to_chs(start + count - 1)
        
        self.mbr[mbr_offset + 0] = 0  # Not bootable
        self.mbr[mbr_offset + 1] = start_chs[1]
        self.mbr[mbr_offset + 2] = (((start_chs[0] >> 2) & 0xc0) | start_chs[2]);
        self.mbr[mbr_offset + 3] = (start_chs[0] & 0xff);
        self.mbr[mbr_offset + 4] = type;
        self.mbr[mbr_offset + 5] = last_chs[1];
        self.mbr[mbr_offset + 6] = (((last_chs[0] >> 2) & 0xc0) | last_chs[2]);
        self.mbr[mbr_offset + 7] = (last_chs[0] & 0xff);

        # LBA of start in little endian
        self.mbr[mbr_offset + 8] = (start & 0xff);
        self.mbr[mbr_offset + 9] = ((start >> 8) & 0xff);
        self.mbr[mbr_offset + 10] = ((start >> 16) & 0xff);
        self.mbr[mbr_offset + 11] = ((start >> 24) & 0xff);

        # Number of sectors
        self.mbr[mbr_offset + 12] = (count & 0xff);
        self.mbr[mbr_offset + 13] = ((count >> 8) & 0xff);
        self.mbr[mbr_offset + 14] = ((count >> 16) & 0xff);
        self.mbr[mbr_offset + 15] = ((count >> 24) & 0xff);
        
    def partition(self, index, start, count, type):
        part_offsets = [446, 462, 478, 494]
        self.calc_partition(part_offsets[index], start, count, type)
        

UBL_MAGIC_NUM = 0xA1ACED00
UBL_ENTRY_POINT = 0x00000100
UBL_LOAD_ADDRESS = 0x00000000

UBOOT_MAGIC_NUM = 0xA1ACED66
UBOOT_LOAD_ADDRESS = 0x81080000
UBOOT_ENTRY_POINT = UBOOT_LOAD_ADDRESS

def build_rbl_descriptor(magic, entry_point, num_blocks, start_block, load_address):
    """ Build an RBL descriptor. 
    
        This is the structure that RBL looks for for information on how to
        boot UBL. UBL borrows it to figure out the same thing for U-boot."""
    header = struct.pack('<IIIII', magic, entry_point, num_blocks, start_block, load_address)
    descriptor = bytearray(128 * 4)
    descriptor[0:len(header)] = header
    return descriptor

def build_ubl_descriptor_block(memory_map):
    """ Create the UBL descriptor block. This block consists of the RBL 
        structure repeated throughout the descriptor memory area. """
    ubl_descriptor = build_rbl_descriptor(UBL_MAGIC_NUM, UBL_ENTRY_POINT, memory_map['ubl_count'], memory_map['ubl_start'], UBL_LOAD_ADDRESS)
    
    return ubl_descriptor * memory_map['ubl_sig_count']
    
def build_uboot_descriptor_block(memory_map):
    """ Create the U-Boot descriptor block. This block is read by UBL to figure
        out where the U-Boot binary is. """
    uboot_descriptor = build_rbl_descriptor(UBOOT_MAGIC_NUM, UBOOT_ENTRY_POINT, memory_map['uboot_count'], memory_map['uboot_start'], UBOOT_LOAD_ADDRESS)
    
    return uboot_descriptor * memory_map['uboot_sig_count']
    
def build_uboot_environment_block(memory_map):
    """ This creates an empty U-Boot environment. It is only useful to ensure
        that the one on the SDCard is definitely empty. """
    
    return bytearray(memory_map['uboot_env_count'] * BLOCK_SIZE)

def read_file(filename):
    fh = open(filename, 'rb')
    return bytearray(fh.read())

def sha1(bytes):
    return hashlib.sha1(buffer(bytes)).hexdigest()

def build_mbr_a(memory_map):
    """ Build an MBR that references the first rootfs partition first. """
    mbr = MBR()
    mbr.partition(0, memory_map['rootfs_a_partition_start'], memory_map['rootfs_a_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(1, memory_map['rootfs_b_partition_start'], memory_map['rootfs_b_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(2, memory_map['working_partition_start'], memory_map['working_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(3, memory_map['debug_partition_start'], memory_map['debug_partition_count'], MBR.FS_TYPE_LINUX)
    return mbr.mbr

def build_mbr_b(memory_map):
    """ Build an MBR that references the second rootfs partition first. """
    mbr = MBR()
    mbr.partition(0, memory_map['rootfs_b_partition_start'], memory_map['rootfs_b_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(1, memory_map['rootfs_a_partition_start'], memory_map['rootfs_a_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(2, memory_map['working_partition_start'], memory_map['working_partition_count'], MBR.FS_TYPE_LINUX)
    mbr.partition(3, memory_map['debug_partition_start'], memory_map['debug_partition_count'], MBR.FS_TYPE_LINUX)
    return mbr.mbr
    
def locate(memory, block_offset, block_count, contents):
    start = block_offset * BLOCK_SIZE
    end = start + block_count * BLOCK_SIZE
    if (len(contents) > end):
        raise Exception('Block size not large enough for contents')
    
    actual_end = min(end, start + len(contents))
    bytes_needed = actual_end - len(memory)
    if bytes_needed > 0:
        memory.extend(bytearray(bytes_needed))
    
    memory[start:actual_end] = contents
    
def build_boot_img(memory_map, args):
    """ Build the boot information block. The returned bytearray is 
        intended to be programmed to the beginning of the SDCard. It contains
        the MBR, various descriptors, bootloaders and u-boot environment. """
    
    memory = bytearray()
    locate(memory, 0, 1, build_mbr_a(memory_map))
    locate(memory, memory_map['ubl_sig_start'], memory_map['ubl_sig_count'], build_ubl_descriptor_block(memory_map))
    locate(memory, memory_map['uboot_sig_start'], memory_map['uboot_sig_count'], build_uboot_descriptor_block(memory_map))
    locate(memory, memory_map['uboot_env_start'], memory_map['uboot_env_count'], build_uboot_environment_block(memory_map))
    locate(memory, memory_map['ubl_start'], memory_map['ubl_count'], read_file(args.ubl_file))
    locate(memory, memory_map['uboot_start'], memory_map['uboot_count'], read_file(args.uboot_file))
    return memory

def build_complete_img(memory_map, args):
    """ Build the image file for use in an SDCard programmer. """
    
    memory = build_boot_img(memory_map, args)
    locate(memory, memory_map['rootfs_a_partition_start'], memory_map['rootfs_a_partition_count'], read_file(args.rootfs_file))
    
    # Zap the debug and working partitions to make sure that they get formatted
    # on first boot
    locate(memory, memory_map['debug_partition_start'], memory_map['debug_partition_count'], bytearray(32 * BLOCK_SIZE))
    locate(memory, memory_map['working_partition_start'], memory_map['working_partition_count'], bytearray(32 * BLOCK_SIZE))
    
    return memory

script_template = """#!/bin/sh

set -e
updatebootloader=$force_bootloader
freshinstall=false
pvopts="-B 32k"
numericprogress=false
archive=
dest=

while [ $$# -gt 0 ]
do
    case "$$1" in
        -a) shift;archive=$$1;;
	-b) updatebootloader=true;;
        -d) shift;dest=$$1;;
        -f) freshinstall=true;;
        -n) numericprogress=true;pvopts="$$pvopts -n";;
        -v)
                echo "$version"
                exit 0;;
        -*)
                echo "arguments:"
                echo "  -a <archive name> (required)"
		echo "  -b update boot loader too"
                echo "  -d <destination> (required)"
                echo "  -f fresh install (on PC)"
                echo "  -n numeric progress"
                echo "  -v print firmware version"
                echo "examples:"
                echo "  First time programming: -a firmware.fw -f -d /dev/sdc"
                echo "  Firmware update: -a firmware.fw -d /dev/mmcblk0"
                exit 1;;
        *) dest=$$1; break;;
    esac
    shift
done

if [ "$$dest" = "" ]
then
    echo Specify a destination
    exit 1
fi
if [ "$$archive" = "" ]
then
    echo Specify the archive name
    exit 1
fi
[ $$numericprogress = false ] || echo 1
if [ ! -w "$$dest" ]
then
    echo Cannot write $$dest
    exit 1
fi
if [ "`mount | grep $$dest`" != "" ]
then
    echo $$dest must not be mounted
    exit 1
fi

$additional_checks

if [ $$freshinstall = true ]
then
    # Verify the SHA-1's of our images before writing them
    if [ "`unzip -p "$$archive" data/boot.img | sha1sum | cut -b 1-40`" != "$boot_img_sha1" ]
    then
        echo "SHA-1 mismatch on data/boot.img"
        exit 1
    fi
    if [ "`unzip -p "$$archive" data/rootfs.img | sha1sum | cut -b 1-40`" != "$rootfs_img_sha1" ]
    then
        echo "SHA-1 mismatch on data/rootfs.img"
        exit 1
    fi
    unzip -p "$$archive" data/boot.img | pv -N boot -s $boot_img_size $$pvopts | dd of=$$dest seek=0 bs=128k 2>/dev/null
    unzip -p "$$archive" data/rootfs.img | pv -N rootfs-a -s $rootfs_img_size $$pvopts | dd of=$$dest seek=$rootfs_a_partition_start 2>/dev/null
    unzip -p "$$archive" data/rootfs.img | pv -N rootfs-b -s $rootfs_img_size $$pvopts | dd of=$$dest seek=$rootfs_b_partition_start 2>/dev/null
    dd if=/dev/zero count=32 2>/dev/null | pv -N debug -s 16384 $$pvopts | dd of=$$dest seek=$debug_partition_count 2>/dev/null
    dd if=/dev/zero count=32 2>/dev/null | pv -N data -s 16384 $$pvopts | dd of=$$dest seek=$working_partition_start 2>/dev/null
else
    case "$$dest" in
    (*mmcblk*) partition2=$${dest}p2;;
    (*)	   partition2=$${dest}2;;
    esac

    tmpdir=`mktemp -d`
    checksumfifo=$$tmpdir/csumfifo
    mkfifo $$checksumfifo
    checksumout=$$tmpdir/csumout

    # Write the image to the software partition that we're not currently
    # using.
    sha1sum $$checksumfifo > $$checksumout &
    unzip -p "$$archive" data/rootfs.img | tee $$checksumfifo | pv -N rootfs -s $rootfs_img_size $$pvopts | dd of=$$partition2 bs=128k 2>/dev/null
    if [ "`cat $$checksumout | cut -b 1-40`" != "$rootfs_img_sha1" ]
    then
            echo "SHA-1 mismatch on rootfs"
            exit 1
    fi

    # Read the block offset numbers of partitions A and B
    part1_blockno=`dd if=$$dest bs=1 skip=454 count=4 2>/dev/null | hexdump -e '"%d"'`
    part2_blockno=`dd if=$$dest bs=1 skip=470 count=4 2>/dev/null | hexdump -e '"%d"'`

    # Update the bootloader
    if [ $$updatebootloader = true ]
    then
        unzip -p "$$archive" data/boot.img | pv -N boot -s $boot_img_size $$pvopts | dd of=$$dest skip=1 seek=1 2>/dev/null
    fi

    # Now that we're done, update the MBR to point to the new code
    if [ $$part1_blockno -gt $$part2_blockno ]
    then
        if [ "`unzip -p "$$archive" data/mbr-a.img | sha1sum | cut -b 1-40`" != "$mbr_a_img_sha1" ]
        then
                echo "SHA-1 mismatch on mbr-a"
                exit 1
        fi
        unzip -p "$$archive" data/mbr-a.img | pv -N mbr-a -s $mbr_a_img_size $$pvopts | dd of=$$dest seek=0 2>/dev/null
    else
        if [ "`unzip -p "$$archive" data/mbr-b.img | sha1sum | cut -b 1-40`" != "$mbr_b_img_sha1" ]
        then
                echo "SHA-1 mismatch on mbr-b"
                exit 1
        fi
        unzip -p "$$archive" data/mbr-b.img | pv -N mbr-b -s $mbr_b_img_size $$pvopts | dd of=$$dest seek=0 2>/dev/null
    fi
    rm -fr $$tmpdir
fi
exit 0
"""

def build_script(memory_map, args, fileinfo):
    template = string.Template(script_template)
    if args.bootloader:
	force_bootloader = "true"
    else:
	force_bootloader = "false"

    if args.additional_checks:
	f = open(args.additional_checks, 'r')
	additional_checks = f.read()
	f.close()
    else:
	additional_checks = ""

    s = template.substitute(version=args.version,
                            mbr_a_img_size=fileinfo['data/mbr-a.img'][0],
                            mbr_b_img_size=fileinfo['data/mbr-b.img'][0],
                            boot_img_size=fileinfo['data/boot.img'][0],
                            rootfs_img_size=fileinfo['data/rootfs.img'][0],
                            boot_img_sha1=fileinfo['data/boot.img'][1],
                            mbr_a_img_sha1=fileinfo['data/mbr-a.img'][1],
                            mbr_b_img_sha1=fileinfo['data/mbr-b.img'][1],
                            rootfs_img_sha1=fileinfo['data/rootfs.img'][1],
                            rootfs_a_partition_start=memory_map['rootfs_a_partition_start'],
                            rootfs_b_partition_start=memory_map['rootfs_b_partition_start'],
                            working_partition_start=memory_map['working_partition_start'],
                            debug_partition_count=memory_map['debug_partition_count'],
			    force_bootloader=force_bootloader,
			    additional_checks=additional_checks)
    return s

def create_firmware_package(memory_map, args):
    mbr_a = build_mbr_a(memory_map)
    mbr_b = build_mbr_b(memory_map)
    bootimg = build_boot_img(memory_map, args)
    rootfs = read_file(args.rootfs_file)
        
    fileinfo = {}
    fileinfo['data/mbr-a.img'] = (len(mbr_a), sha1(mbr_a))
    fileinfo['data/mbr-b.img'] = (len(mbr_b), sha1(mbr_b))
    fileinfo['data/boot.img'] = (len(bootimg), sha1(bootimg))
    fileinfo['data/rootfs.img'] = (len(rootfs), sha1(rootfs))
        
    script = build_script(memory_map, args, fileinfo)
        
    fwzip = zipfile.ZipFile(args.fwfile, 'w', zipfile.ZIP_DEFLATED)
    fwzip.writestr('install.sh', script)
    fwzip.writestr('data/mbr-a.img', buffer(mbr_a))
    fwzip.writestr('data/mbr-b.img', buffer(mbr_b))
    fwzip.writestr('data/rootfs.img', buffer(rootfs))
    fwzip.writestr('data/boot.img', buffer(bootimg))
    fwzip.close()
    
def create_firmware_image(memory_map, args):
    with open(args.imgfile, 'w') as f:
        contents = build_complete_img(memory_map, args)
        f.write(buffer(contents))
        
def load_memory_map(filename):
    config = configparser.ConfigParser()
    result = config.read(filename)
    if result == []:
        raise IOError("Could not open " + filename)
    
    options = config.items('MemoryMap')
    memory_map = {}
    for item in options:
        memory_map[item[0]] = int(item[1])
    
    return memory_map
    
usage = """DM36x Firmware Packager

Arguments:
  -b,--bootloader       Specify to force the bootloader to be programmed
  -f,--fwfile=path      Output path for firmware file
  -g,--imgfile=path     Output path for raw image file
  -v,--version=string   Version to embed into the firmware file
  -c,--config=path      Path to memory map configuration file
  -s,--ubl=path         Path to UBL binary
  -u,--uboot=path       Path to U-Boot binary
  -r,--rootfs=path      Path to Rootfs binary
  -t,--additionalchecks=path Path to script fragment containing validation checks
"""

class Args(object):
    bootloader = None
    fwfile = None
    imgfile = None
    version = 'Unknown'
    config = None
    ubl_file = None
    uboot_file = None
    rootfs_file = None
    
if __name__ == '__main__':
    try:
        opts, optargs = getopt.getopt(sys.argv[1:], "hbf:g:v:c:s:u:r:t:", ["help", "bootloader", "fwfile=", "imgfile=", "version=", "config=", "ubl=", "uboot=", "rootfs=", "additionalchecks="])
    except getopt.GetoptError, err:
        # print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        print(usage)
        sys.exit(2)
    args = Args()
    for o, a in opts:
        if o in ("-b", "--bootloader"):
	    args.bootloader = True
        elif o in ("-f", "--fwfile="):
            args.fwfile = a
        elif o in ("-g", "--imgfile="):
            args.imgfile = a
        elif o in ("-v", "--version="):
            args.version = a
        elif o in ("-c", "--config="):
            args.config = a
        elif o in ("-s", "--ubl="):
            args.ubl_file = a
        elif o in ("-u", "--uboot="):
            args.uboot_file = a
        elif o in ("-r", "--rootfs="):
            args.rootfs_file = a
	elif o in ("-t", "--additionalchecks="):
	    args.additional_checks = a
        elif o in ("-h", "--help"):
            print(usage)
            sys.exit(1)
        else:
            assert False, "unhandled option"
    
    if (args.config == None):
        print("Specify a config file")
        sys.exit(1)
    
    if (args.ubl_file == None):
        print("Specify a UBL binary")
        sys.exit(1)
    
    if (args.uboot_file == None):
        print("Specify a U-Boot binary")
        sys.exit(1)
        
    if (args.rootfs_file == None):
        print("Specify a rootfs binary")
        sys.exit(1)
        
    memory_map = load_memory_map(args.config)
    
    if (args.fwfile != None):
        create_firmware_package(memory_map, args)
    
    if (args.imgfile != None):
        create_firmware_image(memory_map, args)
    
