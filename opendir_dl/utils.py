import urllib
import tempfile
from datetime import datetime
import httplib2
from bs4 import BeautifulSoup
from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import Integer
from sqlalchemy import DateTime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

MODELBASE = declarative_base()

class RemoteFile(MODELBASE):
    """This represents a remote file
    """
    __tablename__ = "remotefile"
    pkid = Column(Integer, primary_key=True)
    domain = Column(String)
    last_indexed = Column(DateTime)
    name = Column(String)
    url = Column(String)
    content_type = Column(String)
    content_length = Column(Integer)
    last_modified = Column(DateTime)

class PageCrawler(object):
    def __init__(self, db_conn, input_urls):
        """Prepare the PageCrawler

        Required initial values are a database connection to save file entries
        to as well as a list of URLs to search. This list can contain any
        number of URLs.
        """
        self.db_conn = db_conn
        self._quick = False
        self._triage_method = self.triage_standard
        self.reindex = None
        if not isinstance(input_urls, list):
            raise ValueError

        self.url_triage_bucket = input_urls
        self.index_urls = []
        self.file_heads = []

    @property
    def quick(self):
        """Wrapper around bool which sets the triage method

        Setting quick to True will also set the triage_method to triage_quick,
        thus changing the method we triage new URLs. That method results in
        fewer head requests, thus speading the indexing processs. Cool huh!!
        """
        return self._quick

    @quick.setter
    def quick(self, value):
        self._quick = value
        if self._quick:
            self._triage_method = self.triage_quick
        else:
            self._triage_method = self.triage_standard

    def crawl(self):
        """Watches the URL lists and delegates work to threads
        """
        while len(self.url_triage_bucket) + len(self.index_urls) + len(self.file_heads) > 0:
            self._triage_method()

            while len(self.index_urls) > 0:
                url = self.index_urls.pop(0)
                triage_bucket = get_urls(url)
                self.url_triage_bucket += triage_bucket

            self.save_heads()

    def triage_standard(self):
        """Handles the URLs that are dumpped into self.url_triage_bucket
        """
        while len(self.url_triage_bucket) > 0:
            # Continue popping URLs from the bucket until the bucket is empty
            url = self.url_triage_bucket.pop(0)
            # Get the head information about the URL. This will be necessary
            # for deciding what to do with the resource (crawl it/database it)
            head = http_head(url)
            if head.get('status', None) != '200':
                continue
            if is_html(head) and "last-modified" not in head.keys():
                # If the content type is "text/html", and does not have a
                # "last-modified" date, then it's a page we want to crawl. If
                # the page has a "last-modified" date, it is a static file
                # rather than one that was generated as part of the directory.
                # Append the url to the index_urls list for another method to
                # handle.
                self.index_urls.append(url)
            else:
                # The content type indicates it is some sort of file, so we
                # should add it to the database. Here we're attaching the URL
                # to the dictionary containing the head request data. The key
                # is prefixed with "oddl_" to prevent any collision with data
                # that may already be in the dictionary (unlikely, but just
                # in case)
                head['oddl_url'] = url
                self.file_heads.append(head)

    def triage_quick(self):
        """Triages URLs without making HEAD requests
        """
        while len(self.url_triage_bucket) > 0:
            url = self.url_triage_bucket.pop(0)
            if url[-1] == "/":
                # We think this might be another directory index to look at
                self.index_urls.append(url)
            else:
                # This might be just a file, don't get any information about
                # it and just add the data we have about it to the file_heads
                file_dict = {'oddl_url': url}
                self.file_heads.append(file_dict)

    def save_heads(self):
        """Saves file entries that are queued up in self.file_heads

        This will remove each entry in file_heads and save it to the database.
        """
        while len(self.file_heads) > 0:
            # For each head entry, pop it from the list, clean the values
            # associated with it (domain/name/last_modified), and then make the
            # RemoteFile object.
            head = self.file_heads.pop(0)
            domain = url_to_domain(head['oddl_url'])
            name = url_to_filename(head['oddl_url'])
            last_modified = clean_date_modified(head)
            # Now create the RemoteFile object
            file_entry = RemoteFile(url=head['oddl_url'], domain=domain, \
                name=name, content_type=head.get('content-type', None), \
                content_length=head.get('content-length', None), \
                last_modified=last_modified, \
                last_indexed=datetime.utcnow())
            # Add the file entry to the database session
            self.db_conn.add(file_entry)
            print "Found file: %s" % head['oddl_url']
        # Now that the looping has finished, commit our new objects to the
        # database. TODO: Depending how how the database session works,
        # threading *might* cause a lot of problems here...
        self.db_conn.commit()

class DatabaseWrapper(object):
    default_db_path = 'sqlite3.db'

    def __init__(self, source=None):
        self.db_conn = None
        self.tempfile = None
        if source:
            self.source = source
        else:
            self.source = self.default_db_path

    def query(self, *args, **kwargs):
        # This is meant to be overwritten with a reference to
        # self.db_conn.query that way stuff can just call wrapper.query like
        # normal
        pass

    def is_connected(self):
        """True/False value for if the DatabaseWrapper instance is connected
        """
        return self.db_conn != None

    def connect(self):
        """ Establish the database session given the set values
        """
        database_engine = create_engine('sqlite:///%s' % self.source)
        MODELBASE.metadata.create_all(database_engine)
        MODELBASE.metadata.bind = database_engine
        database_session = sessionmaker(bind=database_engine)
        self.db_conn = database_session()
        setattr(self, 'query', self.db_conn.query)

    @classmethod
    def from_default(cls):
        """Get a default instance of DatabaseWrapper

        This would be used over `DatabaseWrapper()` because this returns an
        object where self.db_conn is already an established database session
        """
        dbw_inst = cls()
        dbw_inst.connect()
        return dbw_inst

    @classmethod
    def from_fs(cls, path):
        """ Gets a database session from a cache of a remote database

        This method will need additional sanitation on the `path` value.
        relative and absolute paths *should* work, but anything referecing `~`
        will need to be expanded first.
        """
        dbw_inst = cls(path)
        dbw_inst.connect()
        return dbw_inst

    @classmethod
    def from_data(cls, data):
        """Get an instance of DatabaseWrapper from the give raw data
        """
        dbw_inst = cls()
        dbw_inst.tempfile = tempfile.NamedTemporaryFile()
        dbw_inst.tempfile.write(data)
        dbw_inst.tempfile.flush()
        dbw_inst.source = dbw_inst.tempfile.name
        dbw_inst.connect()
        return dbw_inst

    @classmethod
    def from_url(cls, url):
        """ Gets a database session from a URL
        """
        http_session = httplib2.Http()
        http_request = http_session.request(url)
        return cls.from_data(http_request[1])

    @classmethod
    def from_unknown(cls, source_string=None):
        """Creates an instance of DatabaseWrapper given an unknown string
        """
        cache_list = [] # TODO: This is a placeholder until cached databases are implemented
        if not source_string:
            # This gets us the default configuration
            return cls.from_default()
        if source_string.startswith("http://"):
            # We were given a URL
            return cls.from_url(source_string)
        elif source_string in cache_list:
            # Load from a cache of remote db
            #return cls.from_cache(source_string)
            pass
        else:
            # We have a fs path
            return cls.from_fs(source_string)

def get_urls(url, http_session=httplib2.Http()):
    """Gets all useful urls on a page
    """
    print "Searching directory: %s" % url
    url_bucket = []
    html = http_session.request(url)[1]
    # Parse the html we get from the site and then itterate over all 'a'
    # dom elements that have an href in them.
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.find_all('a', href=True):
        # Skip this anchor if it's one we should ignore
        if bad_anchor(anchor['href']):
            continue
        # build the full url and add it to the url bucket
        new_url = url + anchor['href']
        url_bucket.append(new_url)
    return url_bucket

def http_head(url, http_session=httplib2.Http()):
    """Returns HEAD request data from the provided URL

    The dict is contains keys and values with data provided by the HEAD
    request response from the web server. The request is made using the
    provided http_session
    """
    head_response = http_session.request(url, 'HEAD')
    return head_response[0]

def http_get(url, http_session=httplib2.Http()):
    """Returns GET request data from the provided URL
    """
    return http_session.request(url)

def make_file_entry(oddl_head):
    domain = url_to_domain(oddl_head['oddl_url'])
    name = url_to_filename(oddl_head['oddl_url'])
    last_modified = clean_date_modified(oddl_head)
    # Now create the RemoteFile object
    file_entry = RemoteFile(url=oddl_head['oddl_url'], domain=domain, \
        name=name, content_type=oddl_head.get('content-type', None), \
        content_length=oddl_head.get('content-length', None), \
        last_modified=last_modified, \
        last_indexed=datetime.utcnow())
    return file_entry

def bad_anchor(anchor):
    """Determines if the provided anchor is one we want to follow
    """
    static_anchors = ["../", "/", "?C=N;O=D", "?C=M;O=A", "?C=S;O=A",\
        "?C=D;O=A"]
    if anchor in static_anchors:
        return True
    if anchor[0] == "#":
        return True
    if anchor[0] == "/":
        return True
    return False

def is_html(head):
    """Determines if resource is of type "text/html"
    The provided dict should be the HEAD of an http request. It is an html
    page if the HEAD contains the key "content-type" and that value starts
    with "text/html"
    """
    value = head.get("content-type", "")
    return value.startswith("text/html")

def url_to_domain(url):
    """Parses the domain name from the given URL
    """
    try:
        # Get the start of the domain name. If a value error is rasied
        # that means there is no protocole prefix and we should assume
        # the domain starts at the first character
        start = url.index("://") + 3
    except ValueError:
        start = 0
    try:
        # Find the end of the domain name. If we can't find the "/", that
        # likely means the url is provided without a URI specified, in
        # which case we should assume the end of the domain is the end
        # of the string
        end = url[start:].index("/") + start
    except ValueError:
        end = len(url)
    return url[start:end]

def url_to_filename(url):
    """Parses the filename from the given URL
    """
    quoted_filename = url.split("/")[-1]
    filename = urllib.unquote(quoted_filename)
    if len(filename) == 0:
        filename = "index.html"
    return filename

def clean_date_modified(head):
    """ Proves a clean representation of the last-modified value in the HEAD

    The provided dict should represent the HEAD received by an http request. If
    the dict contains the key "last-modified", attempt to cast the value to a
    datetime object. Returns None if any of this fails.
    """
    date_string = head.get("last-modified", None)
    # The key wasn't in the dict, so return None
    if not date_string:
        return None
    # Try to make a datetime object out of the provided value
    try:
        return datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S GMT")
    except ValueError:
        return None

def download_url(db_wrapper, url):
    # Make sure we can open the file before downloading the data
    filename = url_to_filename(url)
    wfile = open(filename, 'w')
    # Now download the file
    response = http_get(url)
    head = response[0]
    data = response[1]
    # Write the contents and close the file descriptor
    wfile.write(data)
    wfile.close()
    # Create an index entry for the file
    head['oddl_url'] = url
    file_entry = make_file_entry(head)
    db_wrapper.db_conn.add(file_entry)

def is_url(candidate):
    # A URL will start with either "http://" or "https://"
    if candidate.startswith("http://"):
        return True
    return candidate.startswith("https://")
