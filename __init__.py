# https://manual.calibre-ebook.com/plugins.html#module-calibre.ebooks.metadata.sources.base

from ast import parse
from threading import Thread
import json
import requests
import re
from calibre.ebooks.metadata.sources.base import Source
from calibre.ebooks.metadata.book.base import Metadata

def parse_series_from_string(series_string):
    if series_string is None:
        return None, None
    # String format : '<series_name> <series_index>'
    series_index = re.findall(r'(\d*)$', series_string)[0]
    series_name = series_string[:-len(series_index)].strip()
    if series_index == '':
        series_index = None
    return series_name, series_index

def make_request(base_url, query, timeout):
    try:
        response = requests.get(base_url, params=query, timeout=timeout)
        data = json.loads(response.text)
        return data
    except Exception as e:
        return None

class AladinMetadataSource(Source):
    name = 'Aladin'
    version = (1, 0, 0)
    # minimum_calibre_version = (0, 7, 53)
    description = 'Downloads metadata and covers from Aladin'

    can_be_disabled = True
    author = 'Subin Song'
    supported_platforms = ['windows', 'osx', 'linux']

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'pubdate', 'comments', 'identifier:isbn',
                               'identifier:isbn13', 'identifier:aladin', 'publisher', 'series',
                               'series_index',
                               'languages'])
    has_html_comments = False
    supports_gzip_transfer_encoding = False
    ignore_ssl_errors = True
    cached_cover_url_is_reliable = True
    options = frozenset('api_key')
    config_help_message = '알라딘 OpenAPI Key를 입력하세요.'
    can_get_multiple_covers = False
    auto_trim_covers = False
    prefer_results_with_isbn = True

    def is_configured(self):
        return False

    def customization_help(self, gui=False):
        return '알라딘 OpenAPI Key를 입력하세요.'

    def get_book_url(self, identifiers):
        '''
        Return a 3-tuple or None. The 3-tuple is of the form:
        (identifier_type, identifier_value, URL).
        The URL is the URL for the book identified by identifiers at this
        source. identifier_type, identifier_value specify the identifier
        corresponding to the URL.
        This URL must be browsable to by a human using a browser. It is meant
        to provide a clickable link for the user to easily visit the books page
        at this source.
        If no URL is found, return None. This method must be quick, and
        consistent, so only implement it if it is possible to construct the URL
        from a known scheme given identifiers.
        '''
        # TODO
        return None

    def get_book_url_name(self, idtype, idval, url):
        '''
        Return a human readable name from the return value of get_book_url().
        '''
        return self.name

    def get_cached_cover_url(self, identifiers):
        '''
            Return cached cover URL for the book identified by
            the identifiers dictionary or None if no such URL exists.

            Note that this method must only return validated URLs, i.e. not URLS
            that could result in a generic cover image or a not found error.
            '''
        return None

    def id_from_url(self, url):
        '''
            Parse a URL and return a tuple of the form:
            (identifier_type, identifier_value).
            If the URL does not match the pattern for the metadata source,
            return None.
            '''
        return None

    def identify_results_keygen(self, title=None, authors=None,
                                   identifiers={}):
        '''
            Return a function that is used to generate a key that can sort Metadata
            objects by their relevance given a search query (title, authors,
            identifiers).

            These keys are used to sort the results of a call to :meth:`identify`.

            For details on the default algorithm see
            :class:`InternalMetadataCompareKeyGen`. Re-implement this function in
            your plugin if the default algorithm is not suitable.
            '''
        def keygen(mi):
                return InternalMetadataCompareKeyGen(mi, self, title, authors,
                                                    identifiers)
            return keygen


    def identify(self, log, result_queue, abort, title=None, authors=None,
                    identifiers={}, timeout=30):
        '''
            Identify a book by its Title/Author/ISBN/etc.

            If identifiers(s) are specified and no match is found and this metadata
            source does not store all related identifiers (for example, all ISBNs
            of a book), this method should retry with just the title and author
            (assuming they were specified).

            If this metadata source also provides covers, the URL to the cover
            should be cached so that a subsequent call to the get covers API with
            the same ISBN/special identifier does not need to get the cover URL
            again. Use the caching API for this.

            Every Metadata object put into result_queue by this method must have a
            `source_relevance` attribute that is an integer indicating the order in
            which the results were returned by the metadata source for this query.
            This integer will be used by :meth:`compare_identify_results`. If the
            order is unimportant, set it to zero for every result.

            Make sure that any cover/ISBN mapping information is cached before the
            Metadata object is put into result_queue.

            :param log: A log object, use it to output debugging information/errors
            :param result_queue: A result Queue, results should be put into it.
                                Each result is a Metadata object
            :param abort: If abort.is_set() returns True, abort further processing
                        and return as soon as possible
            :param title: The title of the book, can be None
            :param authors: A list of authors of the book, can be None
            :param identifiers: A dictionary of other identifiers, most commonly
                                {'isbn':'1234...'}
            :param timeout: Timeout in seconds, no network request should hang for
                            longer than timeout.
            :return: None if no errors occurred, otherwise a unicode representation
                    of the error suitable for showing to the user

            '''
        api_key = self.site_customization
        base_url = 'http://www.aladin.co.kr/ttb/api/ItemSearch.aspx'
        if 'isbn13' in identifiers:
            isbn = identifiers['isbn13']
        elif 'isbn' in identifiers:
            isbn = identifiers['isbn']
        else:
            isbn = None

        if isbn:
            query_type = 'Keyword'
            query_string = str(isbn)
        elif title and authors:
            query_type = 'Keyword'
            query_string = title + ' '
            for author in authors:
                query_string += author + ' '
        elif title:
            query_type = 'Title'
            query_string = title
        elif authors:
            query_type = 'Author'
            query_string = ''
            for author in authors:
                query_string += author + ' '
        else:
            return 'No title or author or ISBN found'

        # Construct the query
        query = {
            'TTBKey': api_key,
            'Query' : query_string,
            'Query_Type': query_type,
            'SearchTarget': 'Book',
            'Output': 'js',
            'Version': '20131101'
        }

        results = []

        data = make_request(base_url, query, timeout)
        if data is None:
            return 'Failed to make request'

        results.extend(data['item'])

        query['SearchTarget'] = 'eBook'

        data = make_request(base_url, query, timeout)
        if data is None:
            return 'Failed to make request'

        results = results + data['item']

        isbn_list = []

        for result in results:
            isbn13 = result.get('isbn13', None)
            if isbn13 is not None:
                isbn_list.append((isbn13, 'ISBN13'))
            else:
                itemId = result.get('itemId', None)
                if itemId is not None:
                    isbn_list.append((itemId, 'ItemId'))

        base_url = 'http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx'

        for isbn in isbn_list:
            query = {
                'TTBKey': api_key,
                'ItemId' : isbn[0],
                'ItemIdType' : isbn[1],
                'Output' : 'js',
                'Version' : '20131101'
            }

            data = make_request(base_url, query, timeout)
            if data is None:
                continue

            item = data['item']
            title = item.get('title', None)

            try:
                authors = []
                authors_info = item['bookinfo']['authors']
                for info in authors_info:
                    if info.get('authorType') == 'author':
                        authors.append(info['name'])
            except Exception:
                authors = None

            pubdate = item.get('pubDate', None)
            comments = item.get('description', None)
            id_isbn = item.get('isbn', None)
            id_isbn13 = item.get('isbn13', None)
            id_aladin = item.get('itemId', None)
            publisher = item.get('publisher', None)
            (series, series_index) = parse_series_from_string(item.get('series', None))
            languages = ['Korean']

            mi = Metadata(title, authors)
            mi.comments = comments
            mi.publisher = publisher
            mi.series = series
            mi.series_index = series_index
            mi.languages = languages
            mi.pubdate = pubdate
            mi.identifiers = {'aladin': id_aladin, 'isbn': id_isbn, 'isbn13': id_isbn13}
            mi.source_relevance = 1

            result_queue.put(mi)


        return None


    def download_cover(self, log, result_queue, abort,
                          title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
        '''
            Download a cover and put it into result_queue. The parameters all have
            the same meaning as for :meth:`identify`. Put (self, cover_data) into
            result_queue.

            This method should use cached cover URLs for efficiency whenever
            possible. When cached data is not present, most plugins simply call
            identify and use its results.

            If the parameter get_best_cover is True and this plugin can get
            multiple covers, it should only get the "best" one.
            '''
        pass
