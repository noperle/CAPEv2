# Copyright (C) 2015 Optiv, Inc. (brad.spengler@optiv.com)
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

from __future__ import absolute_import
from __future__ import print_function
import os
import tempfile
import logging

from lib.cuckoo.common.config import Config
from lib.cuckoo.common.objects import File
from lib.cuckoo.common.exceptions import CuckooDemuxError

try:
    from sflock import unpack
    from sflock.unpack.office import OfficeFile
    from sflock.abstracts import File as sfFile
    from sflock.exception import UnpackException
    HAS_SFLOCK = True
except ImportError:
    print("You must install sflock\n"
          "sudo apt-get install p7zip-full rar unace-nonfree cabextract\n"
          "pip3 install -U sflock")
    HAS_SFLOCK = False

log = logging.getLogger(__name__)
cuckoo_conf = Config()
tmp_path = cuckoo_conf.cuckoo.get("tmppath", "/tmp").encode('utf8')

demux_extensions_list = [
    "", ".exe", ".dll", ".com", ".jar", ".pdf", ".msi", ".bin", ".scr", ".zip", ".tar", ".gz", ".tgz", ".rar", ".htm",
    ".html", ".hta", ".doc", ".dot", ".docx", ".dotx", ".docm", ".dotm", ".docb", ".mht", ".mso", ".js", ".jse",
    ".vbs", ".vbe", ".xls", ".xlt", ".xlm", ".xlsx", ".xltx", ".xlsm", ".xltm", ".xlsb", ".xla", ".xlam", ".xll",
    ".xlw", ".ppt", ".pot", ".pps", ".pptx", ".pptm", ".potx", ".potm", ".ppam", ".ppsx", ".ppsm", ".sldx", ".sldm",
    ".wsf", ".bat", ".ps1", ".sh", ".pl",
]

whitelist_extensions = ("doc", "xls", "ppt", "pub", "jar")

# list of valid file types to extract - TODO: add more types
VALID_TYPES = ["PE32", "Java Jar", "Outlook", "Message"]
VALID_LINUX_TYPES = ["Bourne-Again", "POSIX shell script", "ELF", "Python"]


def options2passwd(options):
    password = False
    if "password=" in options:
        fields = options.split(",")
        for field in fields:
            try:
                key, value = field.split("=", 1)
                if key == "password":
                    # sflock requires password to be bytes object for Py3
                    if isinstance(value, str):
                        value = value.encode('utf8')
                    password = value
                    break
            except:
                pass

    return password


def demux_office(filename, password):
    retlist = []
    basename = os.path.basename(filename)
    target_path = os.path.join(tmp_path, b"cuckoo-tmp/msoffice-crypt-tmp")
    if not os.path.exists(target_path):
        os.mkdir(target_path)
    decrypted_name = os.path.join(target_path, basename)

    if HAS_SFLOCK:
        ofile = OfficeFile(sfFile.from_path(filename))
        d = ofile.decrypt(password)
        with open(decrypted_name, "w") as outs:
            outs.write(d.contents)
        # TODO add decryption verification checks
        if "Encrypted" not in d.magic:
            retlist.append(decrypted_name)
    else:
        raise CuckooDemuxError("MS Office decryptor not available")

    if not retlist:
        retlist.append(filename)

    return retlist


def is_valid_type(magic):
    # check for valid file types and don't rely just on file extentsion
    VALID_TYPES.extend(VALID_LINUX_TYPES)
    for ftype in VALID_TYPES:
        if ftype in magic:
            return True
    return False

def demux_sflock(filename, options):
    retlist = []
    # only extract from files with no extension or with .bin (downloaded from us) or .zip extensions
    ext = os.path.splitext(filename)[1]
    if ext != "" and ext != ".zip" and ext != ".bin":
        return retlist
    try:
        password = b"infected"
        tmp_pass = options2passwd(options)
        if tmp_pass:
            password = tmp_pass

        try:
            unpacked = unpack(filename, password=password)
        except UnpackException:
            unpacked = unpack(filename)

        if unpacked.package in whitelist_extensions:
            return [filename]
        if unpacked.children:
            for sf_child in unpacked.children:
                base, ext = os.path.splitext(sf_child.filename)
                ext = ext.lower()
                if ext in demux_extensions_list or is_valid_type(sf_child.magic):
                    target_path = os.path.join(tmp_path, b"cuckoo-sflock")
                    if not os.path.exists(target_path):
                        os.mkdir(target_path)
                    tmp_dir = tempfile.mkdtemp(dir=target_path)
                    try:
                        path_to_extract = os.path.join(
                            tmp_dir, sf_child.filename)
                        open(path_to_extract, "wb").write(sf_child.contents)
                        retlist.append(path_to_extract)
                    except Exception as e:
                        log.error(e, exc_info=True)
    except Exception as e:
        log.error(e)

    return retlist


def demux_sample(filename, package, options):
    """
    If file is a ZIP, extract its included files and return their file paths
    If file is an email, extracts its attachments and return their file paths (later we'll also extract URLs)
    """
    # sflock requires filename to be bytes object for Py3
    if isinstance(filename, str):
        filename = filename.encode('utf8')
    # if a package was specified, then don't do anything special
    if package:
        return [filename]

    # don't try to extract from office docs
    magic = File(filename).get_type()

    # if file is an Office doc and password is supplied, try to decrypt the doc
    if "Microsoft" in magic:
        ignore = ["Outlook", "Message", "Disk Image"]
        if any(x in magic for x in ignore):
            pass
        elif "Composite Document File" in magic or "CDFV2 Encrypted" in magic:
            password = False
            tmp_pass = options2passwd(options)
            if tmp_pass:
                password = tmp_pass
            if password:
                return demux_office(filename, password)
            else:
                return [filename]

    # don't try to extract from Java archives or executables
    if "Java Jar" in magic:
        return [filename]
    if "PE32" in magic or "MS-DOS executable" in magic:
        return [filename]
    if any(x in magic for x in VALID_LINUX_TYPES):
        return [filename]

    retlist = list()
    if HAS_SFLOCK:
        # all in one unarchiver
        retlist = demux_sflock(filename, options)

    # if it wasn't a ZIP or an email or we weren't able to obtain anything interesting from either, then just submit the
    # original file
    if not retlist:
        retlist.append(filename)
    else:
        if len(retlist) > 10:
            retlist = retlist[:10]

    return retlist
