#!/usr/bin/env python
# -*- coding: utf-8 -*-
# S3 Synchronizer plugin for weeWX
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
import syslog
import threading
import time

# Weewx imports:
from weeutil.weeutil import option_as_list, timestamp_to_string, to_bool
import weewx.manager

# Inherit from the base class ReportGenerator
class S3Generator(weewx.reportengine.ReportGenerator):
    """Service to sync everything in the public_html subdirectory to an Amazon S3 bucket"""

    def run(self):
        # Determine how much logging is desired
        log_success = to_bool(self.skin_dict.get('log_success', True))

        if log_success:
            syslog.syslog(syslog.LOG_INFO, """reportengine: S3Generator""")

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

            if log_success:
                syslog.syslog(syslog.LOG_INFO, "s3generator: successfully configured sync from local folder '%s' to remote bucket '%s'" % (local_root, remote_bucket))

        except KeyError, e:
            syslog.syslog(syslog.LOG_ERR, "s3generator: configuration failed - caught exception %s" % e)

        syslog.syslog(syslog.LOG_DEBUG, "s3generator: launch separate thread to handle sync")

        # start the thread that captures the pressure value
        thread = S3SyncThread(self, access_key, secret_token, local_root, remote_bucket, log_success)
        thread.start()

class S3SyncThread(threading.Thread):
    """Syncs a directory (and all its descendants) to an Amazon Web Services (AWS) S3 bucket."""

    def __init__(self, service, access_key, secret_token, local_root, remote_bucket, log_success):
        threading.Thread.__init__(self)
        self.service = service

        self.access_key = access_key
        self.secret_token = secret_token
        self.local_root = local_root
        self.remote_bucket = remote_bucket
        self.log_success = log_success

    def run(self):
        start_ts = time.time()

        if self.log_success:
            syslog.syslog(syslog.LOG_INFO, "s3generator: sync started at %s" % timestamp_to_string(start_ts))

        # Build command
        cmd = ["/usr/local/bin/s3cmd"]
        cmd.extend(["sync"])
        cmd.extend(["--access_key=%s" % self.access_key])
        cmd.extend(["--secret_key=%s" % self.secret_token])
        cmd.extend(["--no-mime-magic"])
        cmd.extend(["--storage-class=REDUCED_REDUNDANCY"])
        cmd.extend([self.local_root])
        cmd.extend(["s3://%s" % self.remote_bucket])

        syslog.syslog(syslog.LOG_DEBUG, "s3generator: executing command: %s" % cmd)

        try:
            S3_cmd = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            stdout = S3_cmd.communicate()[0]
            stroutput = stdout.strip()
        except OSError, e:
            if e.errno == errno.ENOENT:
                syslog.syslog(syslog.LOG_ERR, "s3generator: s3cmd does not appear to be installed on this system. (errno %d, \"%s\")" % (e.errno, e.strerror))
            raise

        if weewx.debug == 1:
            syslog.syslog(syslog.LOG_DEBUG, "s3generator: s3cmd output: %s" % stroutput)
            for line in iter(stroutput.splitlines()):
                syslog.syslog(syslog.LOG_DEBUG, "s3generator: s3cmd output: %s" % line)

        # S3 output: Generate an appropriate message.
        if stroutput.find('Done. Uploaded ') >= 0:
            file_cnt = 0
            for line in iter(stroutput.splitlines()):
                if line.find('upload:') >= 0:
                    file_cnt += 1
                if line.find('Done. Uploaded ') >= 0:
                    # Get number of bytes uploaded
                    m = re.search(r"Uploaded (\d*) bytes", line)
                    if m:
                        byte_cnt = int(m.group(1))
                    else:
                        byte_cnt = "Unknown"

            # Format message
            try:
                if file_cnt is not None and byte_cnt is not None:
                    S3_message = "sync'd %d files (%s bytes) in %%0.2f seconds" % (int(file_cnt), byte_cnt)
                else:
                    S3_message = "executed in %0.2f seconds"
            except:
                S3_message = "executed in %0.2f seconds"
        else:
            # Looks like we have an s3cmd error so display a message
            syslog.syslog(syslog.LOG_ERR, "s3generator: s3cmd reported errors")
            for line in iter(stroutput.splitlines()):
                syslog.syslog(syslog.LOG_ERR, "s3generator: s3cmd error: %s" % line)
            S3_message = "executed in %0.2f seconds"

        stop_ts = time.time()
        if self.log_success:
            syslog.syslog(syslog.LOG_INFO, "s3generator: " + S3_message % (stop_ts - start_ts))
            syslog.syslog(syslog.LOG_INFO, "s3generator: sync ended at %s" % timestamp_to_string(stop_ts))