import os
import sys
import md5
import unittest
import appdirs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'opendir_dl'))
import opendir_dl
from . import ThreadedHTTPServer
from . import TestWithConfig

"""
Just makes sure the code doesn't throw exceptions. Code cleanup required before
proper unit tests can be written.
"""

class BaseCommandTest(TestWithConfig):
    def test_flags(self):
        instance = opendir_dl.commands.BaseCommand()
        instance.arguments["--example"] = True
        self.assertTrue(instance.has_flag("example"))
        self.assertFalse(instance.has_flag("not-there"))

    def test_database_interaction(self):
        instance = opendir_dl.commands.BaseCommand()
        instance.config = self.config
        self.assertFalse(instance.db_connected())
        instance.db_connect()
        self.assertTrue(instance.db_connected())
        instance.db_disconnect()
        self.assertFalse(instance.db_connected())

class CommandIndexTest(TestWithConfig):
    def test_no_args(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            instance = opendir_dl.commands.IndexCommand()
            instance.config = self.config
            instance.arguments["<resource>"] = [server.url]
            instance.run()

    def test_quick_index(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            instance = opendir_dl.commands.IndexCommand()
            instance.config = self.config
            instance.arguments["--quick"] = True
            instance.arguments["<resource>"] = [server.url]
            instance.run()

    def test_index_404status(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            url = "%s/test_resources/missing_file.txt" % server.url
            instance = opendir_dl.commands.IndexCommand()
            instance.config = self.config
            instance.arguments["<resource>"] = [url]
            instance.run()

class CommandDatabaseListTest(TestWithConfig):
    def test_list(self):
        instance = opendir_dl.commands.DatabaseListCommand()
        instance.config = self.config
        instance.run()

class CommandDatabaseDeleteTest(TestWithConfig):
    def test_create_and_delete_database(self):
        # Create a database to be deleted
        instance1 = opendir_dl.commands.DatabaseCreateCommand()
        instance1.config = self.config
        instance1.arguments["<name>"] = ["test1"]
        instance1.run()
        # Delete the database we just made
        instance2 = opendir_dl.commands.DatabaseDeleteCommand()
        instance2.config = self.config
        instance2.arguments["<name>"] = ["test1"]
        instance2.run()

    def test_attempt_delete_default(self):
        instance = opendir_dl.commands.DatabaseDeleteCommand()
        instance.config = self.config
        instance.arguments["<name>"] = ["default"]
        with self.assertRaises(ValueError) as context:
            instance.run()

class CommandDatabaseCreateTest(TestWithConfig):
    def test_attempt_bad_type(self):
        instance = opendir_dl.commands.DatabaseCreateCommand()
        instance.config = self.config
        instance.arguments["--type"] = "notavalidtype"
        instance.arguments["--resource"] = "default"
        instance.arguments["<name>"] = ["test2"]
        with self.assertRaises(ValueError) as context:
            instance.run()
        expected_error = "Database type must be one of: 'url', 'filesystem', 'alias'. Got type '{}'.".format(instance.arguments["--type"])
        self.assertEqual(str(context.exception), expected_error)

    def test_incomplete_alias(self):
        resource = "nonreal_database"
        expected_error = "Cannot create alias to database- no database named '%s'." % resource
        instance = opendir_dl.commands.DatabaseCreateCommand()
        instance.config = self.config
        instance.arguments["--type"] = "alias"
        instance.arguments["--resource"] = resource
        instance.arguments["<name>"] = ["alias_name"]
        with self.assertRaises(ValueError) as context:
            instance.run()
        self.assertEqual(str(context.exception), expected_error)

class CommandSearchTest(TestWithConfig):
    def test_no_args(self):
        instance = opendir_dl.commands.SearchCommand()
        instance.config = self.config
        instance.arguments["--db"] = "test_resources/test_sqlite3.db"
        instance.run()

class CommandDownloadTest(TestWithConfig):
    def assert_file_exists(self, file_path):
        self.assertTrue(os.path.exists(file_path))

    def assert_files_match(self, file_path1, file_path2):
        file_1 = open(file_path1)
        file_2 = open(file_path2)
        md5_1 = md5.new(file_1.read()).digest()
        md5_2 = md5.new(file_2.read()).digest()
        self.assertEqual(md5_1, md5_2)

    def test_no_args(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            instance = opendir_dl.commands.DownloadCommand()
            instance.config = self.config
            instance.arguments["<index>"] = ["{}test_resources/test_sqlite3.db".format(server.url)]
            instance.run()
            # Make sure the file was actually downloaded
            self.assert_file_exists("test_sqlite3.db")
            # Make sure the two files are exactly the same
            self.assert_files_match("test_sqlite3.db", "test_resources/test_sqlite3.db")
            os.remove("test_sqlite3.db")

    def test_no_index(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            # Download the file
            instance = opendir_dl.commands.DownloadCommand()
            instance.config = self.config
            instance.arguments["<index>"] = ["{}test_resources/example_file.txt".format(server.url)]
            instance.arguments["--no-index"] = True
            instance.run()
            # Make sure the file was actually downloaded
            self.assert_file_exists("example_file.txt")
            # Make sure the two files are exactly the same
            self.assert_files_match("example_file.txt", "test_resources/example_file.txt")
            os.remove("example_file.txt")
            # Check our database to make sure an index wasn't created
            db_wrapper = opendir_dl.databasing.DatabaseWrapper.from_default(self.config)
            search = opendir_dl.utils.SearchEngine(db_wrapper.db_conn, ["example_file.txt"])
            num_results = len(search.query())
            self.assertEqual(num_results, 0)

    def test_bad_status(self):
        with ThreadedHTTPServer("localhost", 8000) as server:
            # This references path test_resources/test_404_head.txt which does not exist (causing status 404)
            instance = opendir_dl.commands.DownloadCommand()
            instance.config = self.config
            instance.arguments["--db"] = "{}test_resources/test_sqlite3.db".format(server.url)
            instance.arguments["<index>"] = [13]
            instance.run()
            # Make sure the file was not created
            self.assertFalse(os.path.exists("test_404_head.txt"))

    #def test_search(self):
    #    with ThreadedHTTPServer("localhost", 8000) as server:
    #        instance = opendir_dl.commands.DownloadCommand()
    #        instance.config = self.config
    #        instance.values = ["example_file"]
    #        instance.flags = ["search"]
    #        instance.options["db"] = "%stest_resources/test_sqlite3.db" % server.url
    #        instance.run()
    #        self.assertTrue(os.path.exists("example_file.txt"))
    #        os.remove("example_file.txt")
