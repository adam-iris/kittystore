# -*- coding: utf-8 -*-
"""
Cached values concerning mailing-lists
"""

from urllib2 import HTTPError
import mailmanclient

from kittystore.caching import CachedValue


class MailmanUserCache(CachedValue):

    _mm_client = None
    _user_id_cache = {}

    def _get_mailman_client(self, settings):
        """Only instanciate the mailman client once"""
        if self._mm_client is None:
            self._mm_client = CachedValue._get_mailman_client(self, settings)
        return self._mm_client

    def _get_user_id(self, store, message):
        address = message.sender_email
        if address not in self._user_id_cache:
            mm_client = self._get_mailman_client(store.settings)
            mm_user = mm_client.get_user(address)
            self._user_id_cache[address] = unicode(mm_user.user_id)
        return self._user_id_cache[address]

    def on_new_message(self, store, mlist, message):
        try:
            message.user_id = self._get_user_id(store, message)
        except (HTTPError, mailmanclient.MailmanConnectionError):
            return # Can't refresh at this time

    def refresh(self, store):
        # XXX: Storm-specific
        from kittystore.storm.model import Email
        try:
            for message in store.db.find(Email, Email.user_id == None):
                message.user_id = self._get_user_id(store, message)
        except (HTTPError, mailmanclient.MailmanConnectionError):
            return # Can't refresh at this time
