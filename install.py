# Installer for S3 Synchronizer extension
# Copyright (c) 2018 Jon Otaegi, Bill Madill
# Distributed under the terms of the GNU Public License (GPLv3)

from setup import ExtensionInstaller


def loader():
    return S3Installer()


class S3Installer(ExtensionInstaller):
    def __init__(self):
        super(S3Installer, self).__init__(
            version="0.1",
            name='S3',
            description='Sync everything in the public_html directory to an Amazon S3 bucket',
            author='Jon Otaegi',
            config={
                'StdReport': {
                    'S3': {
                        'skin': 'S3',
                        'access_key': 'REPLACE_WITH_YOUR_S3_ACCESS_KEY',
                        'secret_token': 'REPLACE_WITH_YOUR_SECRET_TOKEN',
                        'bucket': 'REPLACE_WITH_THE_NAME_OF_YOUR_S3_BUCKET', }}},
            files=[('bin/user', ['bin/user/s3.py']),
                   ('skins/S3', ['skins/S3/skin.conf'])],
        )
