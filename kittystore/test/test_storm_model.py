# -*- coding: utf-8 -*-
# pylint: disable=R0904,C0103
# - Too many public methods
# - Invalid name XXX (should match YYY)

import unittest
import email
import string
import random

from mailman.email.message import Message

from kittystore.storm import get_storm_store
from kittystore.storm.model import Email, Thread

from kittystore.test import get_test_file, FakeList, SettingsModule


class TestStormModel(unittest.TestCase):

    def setUp(self):
        self.store = get_storm_store(SettingsModule())
        #self.store = get_storm_store("postgres://kittystore:kittystore@localhost/kittystore_test", True)
        #self.store = get_storm_store("mysql://kittystore:kittystore@localhost/kittystore_test", True)

    def tearDown(self):
        self.store.db.find(Thread).remove()
        self.store.db.find(Email).remove()
        self.store.close()

    def test_starting_message_1(self):
        # A basic thread: msg2 replies to msg1
        ml = FakeList("example-list")
        msg1 = Message()
        msg1["From"] = "sender1@example.com"
        msg1["Message-ID"] = "<msg1>"
        msg1.set_payload("message 1")
        self.store.add_to_list(ml, msg1)
        msg2 = Message()
        msg2["From"] = "sender2@example.com"
        msg2["Message-ID"] = "<msg2>"
        msg2.set_payload("message 2")
        msg2["In-Reply-To"] = msg1["Message-ID"]
        self.store.add_to_list(ml, msg2)
        thread = self.store.db.find(Thread).one()
        self.assertEqual(thread.starting_email.message_id, "msg1")

    def test_starting_message_2(self):
        # A partially-imported thread: msg1 replies to something we don't have
        ml = FakeList("example-list")
        msg1 = Message()
        msg1["From"] = "sender1@example.com"
        msg1["Message-ID"] = "<msg1>"
        msg1["In-Reply-To"] = "<msg0>"
        msg1.set_payload("message 1")
        self.store.add_to_list(ml, msg1)
        msg2 = Message()
        msg2["From"] = "sender2@example.com"
        msg2["Message-ID"] = "<msg2>"
        msg2["In-Reply-To"] = msg1["Message-ID"]
        msg2.set_payload("message 2")
        self.store.add_to_list(ml, msg2)
        thread = self.store.db.find(Thread).one()
        self.assertEqual(thread.starting_email.message_id, "msg1")

    def test_starting_message_3(self):
        # A thread where the reply has an anterior date to the first email
        # (the In-Reply-To header must win over the date sort)
        ml = FakeList("example-list")
        msg1 = Message()
        msg1["From"] = "sender1@example.com"
        msg1["Message-ID"] = "<msg1>"
        msg1["Date"] = "Fri, 02 Nov 2012 16:07:54 +0000"
        msg1.set_payload("message 1")
        self.store.add_to_list(ml, msg1)
        msg2 = Message()
        msg2["From"] = "sender2@example.com"
        msg2["Message-ID"] = "<msg2>"
        msg2["Date"] = "Fri, 01 Nov 2012 16:07:54 +0000"
        msg2.set_payload("message 2")
        msg2["In-Reply-To"] = msg1["Message-ID"]
        self.store.add_to_list(ml, msg2)
        thread = self.store.db.find(Thread).one()
        self.assertEqual(thread.starting_email.message_id, "msg1")

    def test_subject(self):
        ml = FakeList("example-list")
        msg = Message()
        msg["From"] = "sender@example.com"
        msg["Message-ID"] = "<dummymsg>"
        msg["Date"] = "Fri, 02 Nov 2012 16:07:54 +0000"
        msg["Subject"] = "Dummy subject"
        msg.set_payload("Dummy message")
        self.store.add_to_list(ml, msg)
        thread = self.store.db.find(Thread).one()
        self.assertEqual(thread.subject, "Dummy subject")

    def test_thread_no_email(self):
        thread = Thread("example-list", "<msg1>")
        self.store.db.add(thread)
        self.store.flush()

    def test_long_subject(self):
        # PostgreSQL will raise an OperationalError if the subject's index is
        # longer than 2712, but SQLite will accept anything, so we must test
        # with assertions here.
        # We use random chars to build the subject, if we use a single repeated
        # char, the index will never be big enough.
        ml = FakeList("example-list")
        subject = [ random.choice(string.letters + string.digits + " ")
                    for i in range(3000) ]
        subject = "".join(subject)
        msg = Message()
        msg["From"] = "sender@example.com"
        msg["Message-ID"] = "<dummymsg>"
        msg["Date"] = "Fri, 02 Nov 2012 16:07:54 +0000"
        msg["Subject"] = subject
        msg.set_payload("Dummy message")
        self.store.add_to_list(ml, msg)
        msg_db = self.store.db.find(Email).one()
        self.assertTrue(len(msg_db.subject) < 2712,
                "Very long subjects are not trimmed")
