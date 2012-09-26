# Copyright (C) 2001-2011 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301,
# USA.

"""Cleanse a message for archiving."""

import os
import re
import time
import errno
import binascii
import tempfile
from cStringIO import StringIO
from types import IntType, StringType
from mimetypes import guess_all_extensions

from email.Utils import parsedate
from email.Parser import HeaderParser
from email.Generator import Generator
from email.Charset import Charset

#from Mailman import mm_cfg
#from Mailman import Utils
#from Mailman import LockFile
#from Mailman import Message
#from Mailman.Errors import DiscardMessage
#from Mailman.i18n import _
#from Mailman.Logging.Syslog import syslog
#from Mailman.Utils import sha_new

from mailman.utilities.string import websafe, oneline
# TODO: don't do translations here, the system locale has no meaning to the
# web user
from mailman.core.i18n import _

# Path characters for common platforms
pre = re.compile(r'[/\\:]')
# All other characters to strip out of Content-Disposition: filenames
# (essentially anything that isn't an alphanum, dot, dash, or underscore).
sre = re.compile(r'[^-\w.]')
# Regexp to strip out leading dots
dre = re.compile(r'^\.*')

BR = '<br>\n'


def guess_extension(ctype, ext):
    # mimetypes maps multiple extensions to the same type, e.g. .doc, .dot,
    # and .wiz are all mapped to application/msword.  This sucks for finding
    # the best reverse mapping.  If the extension is one of the giving
    # mappings, we'll trust that, otherwise we'll just guess. :/
    all = guess_all_extensions(ctype, strict=False)
    if ext in all:
        return ext
    return all and all[0]


def replace_payload_by_text(msg, text, charset):
    # TK: This is a common function in replacing the attachment and the main
    # message by a text (scrubbing).
    del msg['content-type']
    del msg['content-transfer-encoding']
    #if isinstance(charset, unicode):
    #    # email 3.0.1 (python 2.4) doesn't like unicode
    #    charset = charset.encode('us-ascii')
    #msg.set_payload(text, charset)
    msg.set_payload('TODO: display attachment here and remove message subpart')



class Scrubber(object):
    """
    Scrubs a single message, extracts attachments, and store them in the
    database.
    """

    def __init__(self, mlist, msg, store):
        self.mlist = mlist
        self.msg = msg
        self.store = store


    def scrub(self):
        sanitize = 1 # TODO: implement other options
        outer = True
        charset = None
        #lcset = Utils.GetCharSet(self.mlist.preferred_language)
        #lcset_out = Charset(lcset).output_charset or lcset
        lcset = "utf-8"
        # Now walk over all subparts of this message and scrub out various types
        format = delsp = None
        for part_num, part in enumerate(self.msg.walk()):
            ctype = part.get_content_type()
            # If the part is text/plain, we leave it alone
            if ctype == 'text/plain':
                # We need to choose a charset for the scrubbed message, so we'll
                # arbitrarily pick the charset of the first text/plain part in the
                # message.
                # MAS: Also get the RFC 3676 stuff from this part. This seems to
                # work OK for scrub_nondigest.  It will also work as far as
                # scrubbing messages for the archive is concerned, but pipermail
                # doesn't pay any attention to the RFC 3676 parameters.  The plain
                # format digest is going to be a disaster in any case as some of
                # messages will be format="flowed" and some not.  ToDigest creates
                # its own Content-Type: header for the plain digest which won't
                # have RFC 3676 parameters. If the message Content-Type: headers
                # are retained for display in the digest, the parameters will be
                # there for information, but not for the MUA. This is the best we
                # can do without having get_payload() process the parameters.
                if charset is None:
                    charset = part.get_content_charset(lcset)
                    format = part.get_param('format')
                    delsp = part.get_param('delsp')
                # TK: if part is attached then check charset and scrub if none
                if part.get('content-disposition') and \
                   not part.get_content_charset():
                    self.save_attachment(part, part_num)
                    replace_payload_by_text(part, _("""\
    An embedded and charset-unspecified text was scrubbed...
    Name: %(filename)s
    URL: %(url)s
    """), lcset)
            elif ctype == 'text/html' and isinstance(sanitize, IntType):
#            if sanitize == 0:
#                if outer:
#                    raise DiscardMessage
#                replace_payload_by_text(part,
#                                 _('HTML attachment scrubbed and removed'),
#                                 # Adding charset arg and removing content-type
#                                 # sets content-type to text/plain
#                                 lcset)
#            elif sanitize == 2:
#                # By leaving it alone, Pipermail will automatically escape it
#                pass
#            elif sanitize == 3:
#                # Pull it out as an attachment but leave it unescaped.  This
#                # is dangerous, but perhaps useful for heavily moderated
#                # lists.
#                self.save_attachment(part, part_num, filter_html=False)
#                replace_payload_by_text(part, _("""\
#An HTML attachment was scrubbed...
#URL: %(url)s
#"""), lcset)
#            else:
                if sanitize == 1:
                    # HTML-escape it and store it as an attachment, but make it
                    # look a /little/ bit prettier. :(
                    payload = websafe(part.get_payload(decode=True))
                    # For whitespace in the margin, change spaces into
                    # non-breaking spaces, and tabs into 8 of those.  Then use a
                    # mono-space font.  Still looks hideous to me, but then I'd
                    # just as soon discard them.
                    def doreplace(s):
                        return s.expandtabs(8).replace(' ', '&nbsp;')
                    lines = [doreplace(s) for s in payload.split('\n')]
                    payload = '<tt>\n' + BR.join(lines) + '\n</tt>\n'
                    part.set_payload(payload)
                    # We're replacing the payload with the decoded payload so this
                    # will just get in the way.
                    del part['content-transfer-encoding']
                    self.save_attachment(part, part_num, filter_html=False)
                    replace_payload_by_text(part, _("""\
    An HTML attachment was scrubbed...
    URL: %(url)s
    """), lcset)
            elif ctype == 'message/rfc822':
                # This part contains a submessage, so it too needs scrubbing
                submsg = part.get_payload(0)
                self.save_attachment(part, part_num)
                subject = submsg.get('subject', _('no subject'))
                subject = oneline(subject, lcset)
                date = submsg.get('date', _('no date'))
                who = submsg.get('from', _('unknown sender'))
                size = len(str(submsg))
                replace_payload_by_text(part, _("""\
    An embedded message was scrubbed...
    From: %(who)s
    Subject: %(subject)s
    Date: %(date)s
    Size: %(size)s
    URL: %(url)s
    """), lcset)
            # If the message isn't a multipart, then we'll strip it out as an
            # attachment that would have to be separately downloaded.  Pipermail
            # will transform the url into a hyperlink.
            elif part.get_payload() and not part.is_multipart():
                payload = part.get_payload(decode=True)
                ctype = part.get_content_type()
                # XXX Under email 2.5, it is possible that payload will be None.
                # This can happen when you have a Content-Type: multipart/* with
                # only one part and that part has two blank lines between the
                # first boundary and the end boundary.  In email 3.0 you end up
                # with a string in the payload.  I think in this case it's safe to
                # ignore the part.
                if payload is None:
                    continue
                size = len(payload)
                self.save_attachment(part, part_num)
                desc = part.get('content-description', _('not available'))
                desc = oneline(desc, lcset)
                filename = part.get_filename(_('not available'))
                filename = oneline(filename, lcset)
                replace_payload_by_text(part, _("""\
    A non-text attachment was scrubbed...
    Name: %(filename)s
    Type: %(ctype)s
    Size: %(size)d bytes
    Desc: %(desc)s
    URL: %(url)s
    """), lcset)
            outer = False
        # We still have to sanitize multipart messages to flat text because
        # Pipermail can't handle messages with list payloads.  This is a kludge;
        # def (n) clever hack ;).
        if self.msg.is_multipart():
            # By default we take the charset of the first text/plain part in the
            # message, but if there was none, we'll use the list's preferred
            # language's charset.
            if not charset or charset == 'us-ascii':
                charset = lcset_out
            else:
                # normalize to the output charset if input/output are different
                charset = Charset(charset).output_charset or charset
            # We now want to concatenate all the parts which have been scrubbed to
            # text/plain, into a single text/plain payload.  We need to make sure
            # all the characters in the concatenated string are in the same
            # encoding, so we'll use the 'replace' key in the coercion call.
            # BAW: Martin's original patch suggested we might want to try
            # generalizing to utf-8, and that's probably a good idea (eventually).
            text = []
            for part in self.msg.walk():
                # TK: bug-id 1099138 and multipart
                # MAS test payload - if part may fail if there are no headers.
                if not part.get_payload() or part.is_multipart():
                    continue
                # All parts should be scrubbed to text/plain by now, except
                # if sanitize == 2, there could be text/html parts so keep them
                # but skip any other parts.
                partctype = part.get_content_type()
                if partctype <> 'text/plain' and (partctype <> 'text/html' or
                                                  sanitize <> 2):
                    text.append(_('Skipped content of type %(partctype)s\n'))
                    continue
                try:
                    t = part.get_payload(decode=True) or ''
                # MAS: TypeError exception can occur if payload is None. This
                # was observed with a message that contained an attached
                # message/delivery-status part. Because of the special parsing
                # of this type, this resulted in a text/plain sub-part with a
                # null body. See bug 1430236.
                except (binascii.Error, TypeError):
                    t = part.get_payload() or ''
                # TK: get_content_charset() returns 'iso-2022-jp' for internally
                # crafted (scrubbed) 'euc-jp' text part. So, first try
                # get_charset(), then get_content_charset() for the parts
                # which are already embeded in the incoming message.
                partcharset = part.get_charset()
                if partcharset:
                    partcharset = str(partcharset)
                else:
                    partcharset = part.get_content_charset()
                if partcharset and partcharset <> charset:
                    try:
                        t = unicode(t, partcharset, 'replace')
                    except (UnicodeError, LookupError, ValueError,
                            AssertionError):
                        # We can get here if partcharset is bogus in come way.
                        # Replace funny characters.  We use errors='replace'
                        t = unicode(t, 'ascii', 'replace')
                    try:
                        # Should use HTML-Escape, or try generalizing to UTF-8
                        t = t.encode(charset, 'replace')
                    except (UnicodeError, LookupError, ValueError,
                            AssertionError):
                        # if the message charset is bogus, use the list's.
                        t = t.encode(lcset, 'replace')
                # Separation is useful
                if isinstance(t, StringType):
                    if not t.endswith('\n'):
                        t += '\n'
                    text.append(t)
            # Now join the text and set the payload
            sep = _('-------------- next part --------------\n')
            # The i18n separator is in the list's charset. Coerce it to the
            # message charset.
            try:
                sep = sep.encode(charset, 'replace')
            except (UnicodeError, LookupError, ValueError,
                    AssertionError):
                pass
            text = sep.join(text)
            del self.msg['content-type']
            del self.msg['content-transfer-encoding']
            self.msg.set_payload(text, charset)
            if format:
                self.msg.set_param('Format', format)
            if delsp:
                self.msg.set_param('DelSp', delsp)
        return text.decode(charset)


    def save_attachment(self, part, counter, filter_html=True):
        # Store name, content-type and size
        # Figure out the attachment type and get the decoded data
        decodedpayload = part.get_payload(decode=True)
        # BAW: mimetypes ought to handle non-standard, but commonly found types,
        # e.g. image/jpg (should be image/jpeg).  For now we just store such
        # things as application/octet-streams since that seems the safest.
        ctype = part.get_content_type()
        # i18n file name is encoded
        #lcset = Utils.GetCharSet(self.mlist.preferred_language)
        lcset = "utf-8"
        filename = oneline(part.get_filename(''), lcset)
        filename, fnext = os.path.splitext(filename)
        # For safety, we should confirm this is valid ext for content-type
        # but we can use fnext if we introduce fnext filtering
        # TODO: re-implement this
        #if mm_cfg.SCRUBBER_USE_ATTACHMENT_FILENAME_EXTENSION:
        #    # HTML message doesn't have filename :-(
        #    ext = fnext or guess_extension(ctype, fnext)
        #else:
        #    ext = guess_extension(ctype, fnext)
        ext = fnext or guess_extension(ctype, fnext)
        if not ext:
            # We don't know what it is, so assume it's just a shapeless
            # application/octet-stream, unless the Content-Type: is
            # message/rfc822, in which case we know we'll coerce the type to
            # text/plain below.
            if ctype == 'message/rfc822':
                ext = '.txt'
            else:
                ext = '.bin'
        # Allow only alphanumerics, dash, underscore, and dot
        ext = sre.sub('', ext)
        # Now base the filename on what's in the attachment, uniquifying it if
        # necessary.
        if not filename:
            filebase = 'attachment'
        else:
            # Sanitize the filename given in the message headers
            parts = pre.split(filename)
            filename = parts[-1]
            # Strip off leading dots
            filename = dre.sub('', filename)
            # Allow only alphanumerics, dash, underscore, and dot
            filename = sre.sub('', filename)
            # If the filename's extension doesn't match the type we guessed,
            # which one should we go with?  For now, let's go with the one we
            # guessed so attachments can't lie about their type.  Also, if the
            # filename /has/ no extension, then tack on the one we guessed.
            # The extension was removed from the name above.
            filebase = filename
        # TODO: bring back the HTML sanitizer feature
        if ctype == 'message/rfc822':
            submsg = part.get_payload()
            # BAW: I'm sure we can eventually do better than this. :(
            decodedpayload = websafe(str(submsg))
        msg_id = self.msg['Message-Id'].strip("<>")
        self.store.add_attachment(
                self.mlist, msg_id, counter, filebase+ext,
                ctype, decodedpayload)
