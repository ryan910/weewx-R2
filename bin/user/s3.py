#!/usr/bin/env python
# -*- coding: utf-8 -*-
# S3 Synchronizer plugin for WeeWX
#
# Copyright (c) 2018 Jon Otaegi, Bill Madill, Tom Keffer
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.
#
# See http://www.gnu.org/licenses/

"""This will sync everything in the public_html directory to an Amazon S3 bucket

********************************************************************************
To use this synchronizer, add the following to your weewx.conf:
[StdReport]
    [[S3]]
        skin = S3
        access_key = "YOUR_S3_ACCESS_KEY"
        secret_token = "YOUR_SECRET_TOKEN"
        bucket = "YOUR_S3_BUCKET_NAME"
********************************************************************************
"""

# System imports:
import errno
import os.path
import re
import subprocess
import threading
import time

# WeeWX imports:
from weeutil.weeutil import option_as_list, timestamp_to_string, to_bool
import weewx.manager

try:
    # WeeWX 4 logging
    import weeutil.logger
    import logging

    log = logging.getLogger(__name__)

    def logdbg(msg):
        log.debug(msg)

    def loginf(msg):
        log.info(msg)

    def logerr(msg):
        log.error(msg)

except ImportError:
    # Old-style WeeWX logging
    import syslog

    def logmsg(level, msg):
        syslog.syslog(level, 'S3: %s' % msg)

    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)

    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)

    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)


# Inherit from the base class ReportGenerator
class S3Generator(weewx.reportengine.ReportGenerator):
    """Service to sync everything in the public_html subdirectory to an Amazon S3 bucket"""

    def run(self):
        logdbg("Reading properties from the configuration dictionary")

        try:
            # Get the options from the configuration dictionary.
            if 'HTML_ROOT' in self.skin_dict:
                html_root = self.skin_dict['HTML_ROOT']
            else:
                html_root = self.config_dict['StdReport']['HTML_ROOT']

            local_root = os.path.join(self.config_dict['WEEWX_ROOT'], html_root) + "/"
            access_key = self.skin_dict['access_key']
            secret_token = self.skin_dict['secret_token']
            remote_bucket = self.skin_dict['bucket']

            logdbg("Successfully configured sync from local folder '%s' to remote bucket '%s'" % (local_root, remote_bucket))

        except KeyError as e:
            loginf("Configuration failed - caught exception %s" % e)
            exit(1)

        logdbg("Launch separate thread to handle sync")

        # Start a separate thread to prevent blocking the main loop thread:
        thread = S3SyncThread(self, access_key, secret_token, local_root, remote_bucket)
        thread.start()


class S3SyncThread(threading.Thread):
    """Syncs a directory (and all its descendants) to an Amazon Web Services (AWS) S3 bucket."""

    def __init__(self, service, access_key, secret_token, local_root, remote_bucket):
        threading.Thread.__init__(self)
        self.service = service

        self.access_key = access_key
        self.secret_token = secret_token
        self.local_root = local_root
        self.remote_bucket = remote_bucket

    def run(self):
        start_ts = time.time()

        logdbg("Sync started at %s" % timestamp_to_string(start_ts))

        # Build command
        cmd = ["s3cmd"]
        cmd.extend(["sync"])
        cmd.extend(["--access_key=%s" % self.access_key])
        cmd.extend(["--secret_key=%s" % self.secret_token])
        cmd.extend(["--no-mime-magic"])
        cmd.extend(["--storage-class=STANDARD"])
        cmd.extend([self.local_root])
        cmd.extend(["s3://%s" % self.remote_bucket])

        logdbg("Executing command: %s" % cmd)

        try:
            S3_cmd = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            stdout = S3_cmd.communicate()[0]
            stroutput = stdout.strip()
        except OSError as e:
            if e.errno == errno.ENOENT:
                loginf("S3cmd does not appear to be installed on this system (errno %d, \"%s\")" % (e.errno, e.strerror))
                exit(1)

        logdbg("S3cmd output: %s" % stroutput)
        for line in iter(stroutput.splitlines()):
            logdbg("S3cmd output: %s" % line)

        # S3 output: Generate an appropriate message.
        if stroutput.find(b'Done. Uploaded ') >= 0:
            file_cnt = 0
            for line in iter(stroutput.splitlines()):
                if line.find(b'upload:') >= 0:
                    file_cnt += 1
                if line.find(b'Done. Uploaded ') >= 0:
                    # Get number of bytes uploaded
                    m = re.search(b"Uploaded (\d*) bytes", line)
                    if m:
                        byte_cnt = int(m.group(1))
                    else:
                        byte_cnt = "Unknown"

            # Format message
            try:
                if file_cnt is not None and byte_cnt is not None:
                    S3_message = "Synced %d files (%s bytes) in %%0.2f seconds" % (int(file_cnt), byte_cnt)
                else:
                    S3_message = "Executed in %0.2f seconds"
            except:
                S3_message = "Executed in %0.2f seconds"
        else:
            # Looks like we have an S3cmd error so display a message
            logerr("S3cmd reported errors")
            for line in iter(stroutput.splitlines()):
                logerr("S3cmd error: %s" % line)
            S3_message = "Executed with errors in %0.2f seconds"

        stop_ts = time.time()

        loginf(S3_message % (stop_ts - start_ts))
        logdbg("Sync ended at %s" % timestamp_to_string(stop_ts))
