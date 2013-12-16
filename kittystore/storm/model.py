# -*- coding: utf-8 -*-

"""
Copyright (C) 2012 Aurelien Bompard <abompard@fedoraproject.org>
Author: Aurelien Bompard <abompard@fedoraproject.org>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or (at
your option) any later version.
See http://www.gnu.org/copyleft/gpl.html  for the full text of the
license.
"""

from __future__ import absolute_import

import datetime
from collections import namedtuple

from zope.interface import implements
from storm.locals import Unicode, RawStr, Int, ReferenceSet, Reference, Proxy
from storm.locals import Storm, Store, And
from storm.expr import Desc
from mailman.interfaces.messages import IMessage
from mailman.interfaces.archiver import ArchivePolicy
from mailman.database.types import Enum

from kittystore import events
from kittystore.utils import get_message_id_hash
from .utils import get_participants_count_between, get_threads_between
from .hack_datetime import DateTime

# pylint: disable-msg=R0902,R0913,R0903
# R0902: Too many instance attributes (X/7)
# R0913: Too many arguments (X/5)
# R0903: Too few public methods (X/2)


__all__ = ("List", "Email", "EmailFull", "Attachment", "Thread", "Category")


class List(Storm):
    # The 'List' name is part of storm's locals
    # pylint: disable-msg=E0102
    """
    An archived mailing-list.
    """
    # When updating this model, remember to update the fake version
    # in test/__init__.py

    __storm_table__ = "list"

    # The following properties are mirrored from Mailman's MailingList instance
    mailman_props = ("display_name", "description", "subject_prefix",
                     "archive_policy", "created_at")

    name = Unicode(primary=True)
    display_name = Unicode()
    description = Unicode()
    subject_prefix = Unicode()
    archive_policy = Enum(ArchivePolicy)
    created_at = DateTime()

    def __init__(self, name):
        self.name = unicode(name)

    def get_recent_dates(self):
        today = datetime.datetime.utcnow()
        #today -= datetime.timedelta(days=400) #debug
        # the upper boundary is excluded in the search, add one day
        end_date = today + datetime.timedelta(days=1)
        begin_date = end_date - datetime.timedelta(days=32)
        return begin_date, end_date

    @property
    def recent_participants_count(self):
        store = Store.of(self)
        begin_date, end_date = self.get_recent_dates()
        return store.cache.get_or_create(
            "list:%s:recent_participants_count" % self.name,
            lambda: get_participants_count_between(store, self.name,
                                                   begin_date, end_date),
            86400)

    @property
    def recent_threads_count(self):
        store = Store.of(self)
        begin_date, end_date = self.get_recent_dates()
        return store.cache.get_or_create(
            "list:%s:recent_threads_count" % self.name,
            lambda: get_threads_between(store, self.name,
                                        begin_date, end_date).count(),
            86400)

    def get_month_activity(self, year, month):
        store = Store.of(self)
        begin_date = datetime.datetime(year, month, 1)
        end_date = begin_date + datetime.timedelta(days=32)
        end_date = end_date.replace(day=1)
        Activity = namedtuple('Activity',
                ['year', 'month', 'participants_count', 'threads_count'])
        participants_count = store.cache.get_or_create(
            "list:%s:participants_count:%s:%s" % (self.name, year, month),
            lambda: get_participants_count_between(store, self.name,
                                                   begin_date, end_date),
            )
        threads_count = store.cache.get_or_create(
            "list:%s:threads_count:%s:%s" % (self.name, year, month),
            lambda: get_threads_between(store, self.name,
                                        begin_date, end_date).count(),
            )
        return Activity(year, month, participants_count, threads_count)

    @events.subscribe_to(events.NewMessage)
    def on_new_message(event): # will be called unbound (no self as 1st argument)
        cache = event.store.db.cache
        l = event.store.get_list(event.mlist.fqdn_listname)
        # recent activity
        begin_date = l.get_recent_dates()[0]
        if event.message.date >= begin_date:
            cache.delete("list:%s:recent_participants_count" % l.name)
            l.recent_participants_count
            cache.delete("list:%s:recent_threads_count" % l.name)
            l.recent_threads_count
        # month activity
        year, month = event.message.date.year, event.message.date.month
        cache.delete("list:%s:participants_count:%s:%s" % (l.name, year, month))
        l.get_month_activity(year, month)


class Email(Storm):
    """
    An archived email, from a mailing-list. It is identified by both the list
    name and the message id.
    """

    implements(IMessage)
    __storm_table__ = "email"
    __storm_primary__ = "list_name", "message_id"

    list_name = Unicode()
    message_id = Unicode()
    sender_name = Unicode()
    sender_email = Unicode()
    user_id = Unicode()
    subject = Unicode()
    content = Unicode()
    date = DateTime()
    timezone = Int()
    in_reply_to = Unicode()
    message_id_hash = Unicode()
    thread_id = Unicode()
    archived_date = DateTime(default_factory=datetime.datetime.now)
    thread_depth = Int(default=0)
    thread_order = Int(default=0)
    # path is required by IMessage, but it makes no sense here
    path = None
    # References
    attachments = ReferenceSet(
                    (list_name,
                     message_id),
                    ("Attachment.list_name",
                     "Attachment.message_id"),
                    order_by="Attachment.counter"
                    )
    thread = Reference((list_name, thread_id),
                       ("Thread.list_name", "Thread.thread_id"))
    full_email = Reference((list_name, message_id),
                     ("EmailFull.list_name", "EmailFull.message_id"))
    full = Proxy(full_email, "EmailFull.full")
    mlist = Reference(list_name, "List.name")

    def __init__(self, list_name, message_id):
        self.list_name = unicode(list_name)
        self.message_id = unicode(message_id)
        self.message_id_hash = unicode(get_message_id_hash(self.message_id))


class EmailFull(Storm):
    """
    The full contents of an archived email, for storage and post-processing
    reasons.
    """
    __storm_table__ = "email_full"
    __storm_primary__ = "list_name", "message_id"

    list_name = Unicode()
    message_id = Unicode()
    full = RawStr()
    email = Reference((list_name, message_id),
                     ("Email.list_name", "Email.message_id"))

    def __init__(self, list_name, message_id, full):
        self.list_name = unicode(list_name)
        self.message_id = unicode(message_id)
        self.full = full


class Attachment(Storm):

    __storm_table__ = "attachment"
    __storm_primary__ = "list_name", "message_id", "counter"

    list_name = Unicode()
    message_id = Unicode()
    counter = Int()
    name = Unicode()
    content_type = Unicode()
    encoding = Unicode()
    size = Int()
    content = RawStr()
    # reference to the email
    email = Reference((list_name, message_id),
                      (Email.list_name, Email.message_id))


class Thread(Storm):
    """
    A thread of archived email, from a mailing-list. It is identified by both
    the list name and the thread id.
    """

    __storm_table__ = "thread"
    __storm_primary__ = "list_name", "thread_id"

    list_name = Unicode()
    thread_id = Unicode()
    date_active = DateTime()
    category_id = Int()
    emails = ReferenceSet(
                (list_name, thread_id),
                (Email.list_name, Email.thread_id),
                order_by=Email.date
             )
    emails_by_reply = ReferenceSet(
                (list_name, thread_id),
                (Email.list_name, Email.thread_id),
                order_by=Email.thread_order
             )
    category_obj = Reference(category_id, "Category.id")
    mlist = Reference(list_name, "List.name")
    _starting_email = None

    def __init__(self, list_name, thread_id, date_active=None):
        self.list_name = unicode(list_name)
        self.thread_id = unicode(thread_id)
        self.date_active = date_active

    @property
    def _starting_email_req(self):
        """ Returns the request to get the starting email.
        If there are no results with in_reply_to IS NULL, then it's
        probably a partial import and we don't have the real first email.
        In this case, use the date.
        """
        return self.emails.order_by(Email.in_reply_to != None, Email.date)

    @property
    def starting_email(self):
        """Return (and cache) the email starting this thread"""
        if self._starting_email is None:
            self._starting_email = self._starting_email_req.first()
        return self._starting_email

    @property
    def last_email(self):
        return self.emails.order_by(Desc(Email.date)).first()

    @property
    def participants(self):
        """Set of email senders in this thread"""
        p = []
        for sender in self.emails.find().config(distinct=True
                        ).order_by().values(Email.sender_name, Email.sender_email):
            p.append(sender)
        return p

    @property
    def email_ids(self):
        return list(self.emails.find().order_by().values(Email.message_id))

    @property
    def email_id_hashes(self):
        return list(self.emails.find().order_by().values(Email.message_id_hash))

    def __len__(self):
        return self.emails_count

    def replies_after(self, date):
        return self.emails.find(Email.date > date)

    def _get_category(self):
        if not self.category_id:
            return None
        return self.category_obj.name
    def _set_category(self, name):
        if not name:
            self.category_id = None
            return
        store = Store.of(self)
        category = store.find(Category, Category.name == name).one()
        if category is None:
            category = Category(name)
            store.add(category)
            store.flush()
        self.category_id = category.id
    category = property(_get_category, _set_category)

    @property
    def emails_count(self):
        store = Store.of(self)
        return store.cache.get_or_create(
            "list:%s:thread:%s:emails_count" % (self.list_name, self.thread_id),
            self.emails.count())

    @property
    def participants_count(self):
        store = Store.of(self)
        return store.cache.get_or_create(
            "list:%s:thread:%s:participants_count"
                % (self.list_name, self.thread_id),
            lambda: len(self.participants))

    @property
    def subject(self):
        store = Store.of(self)
        return store.cache.get_or_create(
            "list:%s:thread:%s:subject"
                % (self.list_name, self.thread_id),
            lambda: self.starting_email.subject)

    @events.subscribe_to(events.NewMessage)
    def on_new_message(event): # will be called unbound (no self as 1st argument)
        cache = event.store.db.cache
        cache.delete("list:%s:thread:%s:emails_count"
                     % (event.message.list_name, event.message.thread_id))
        event.message.thread.emails_count
        cache.delete("list:%s:thread:%s:participants_count"
                     % (event.message.list_name, event.message.thread_id))
        event.message.thread.participants_count

    @events.subscribe_to(events.NewThread)
    def on_new_thread(event): # will be called unbound (no self as 1st argument)
        event.store.db.cache.set(
                "list:%s:thread:%s:subject"
                % (event.thread.list_name, event.thread.thread_id),
                event.thread.starting_email.subject)

    def __storm_pre_flush__(self):
        """Auto-set the active date from the last email in thread"""
        if self.date_active is not None:
            return
        email_dates = list(self.emails.order_by(Desc(Email.date)
                                ).config(limit=1).values(Email.date))
        if email_dates:
            self.date_active = email_dates[0]
        else:
            self.date_active = datetime.datetime.now()


class Category(Storm):
    """
    A thread category
    """

    __storm_table__ = "category"

    id = Int(primary=True)
    name = Unicode()
    threads = ReferenceSet(id, Thread.category_id)

    def __init__(self, name):
        self.name = unicode(name)
