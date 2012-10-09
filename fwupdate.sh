#!/bin/sh

# Helper script for installing firmware update packages
#
# Usage:
#   fwupdate.sh <archive.fw> [arguments to update script]
#
# Examples:
#   fwupdate.sh archive.fw -d /dev/sdb -f
#   fwupdate.sh archive.fw -d /dev/mmcblock0

if [ $# -lt 1 ]
then
	echo "usage: $0 <archive.fw>"
	exit 1
fi

archive="$1"
shift

unzip -p $archive install.sh | sudo sh -s - -a $archive $@

