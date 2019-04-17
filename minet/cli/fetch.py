# =============================================================================
# Minet Fetch CLI Action
# =============================================================================
#
# Action reading an input CSV file line by line and fetching the urls found
# in the given column. This is done in a respectful multithreaded fashion to
# optimize both running time & memory.
#
import os
import csv
import sys
import json
import certifi
import mimetypes
from io import StringIO
from os.path import join
from collections import Counter
from urllib3 import PoolManager, Timeout
from tqdm import tqdm
from quenouille import imap_unordered
from tld import get_fld
from uuid import uuid4
from ural import ensure_protocol, is_url, get_domain_name

from urllib3.exceptions import (
    HTTPError,
    ClosedPoolError,
    ConnectTimeoutError,
    MaxRetryError,
    ReadTimeoutError,
    ResponseError
)

from minet.utils import guess_encoding
from minet.cli.utils import custom_reader, DummyTqdmFile

mimetypes.init()

OUTPUT_ADDITIONAL_HEADERS = ['line', 'status', 'error', 'filename', 'encoding']

# TODO: make this an option!
SPOOFED_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.119 Safari/537.36'

def max_retry_error_reporter(error):
    if isinstance(error, (ConnectTimeoutError, ReadTimeoutError)):
        return 'timeout'

    if isinstance(error.reason, ResponseError) and 'redirect' in repr(error.reason):
        return 'too-many-redirects'

    return 'max-retries-exceeded'

ERROR_REPORTERS = {
    MaxRetryError: max_retry_error_reporter,
    UnicodeEncodeError: 'headers-encoding'
}


def fetch(http, url):

    # TODO: probably need to do redirects myself to avoid ClosedPoolError
    try:
        r = http.request(
            'GET',
            ensure_protocol(url),
            headers={
                'User-Agent': SPOOFED_UA
            }
        )

        return None, r

    except ClosedPoolError:

        # TODO: this is a clunky workaround
        return fetch(http, url)

    # TODO: when urllib3 updates and release #1487, we'll need to change that
    except (HTTPError, UnicodeEncodeError) as e:
        return e, None


def worker(job):
    """
    Function using the urllib3 http to actually fetch our contents from the web.
    """
    http, line, url = job

    error, result = fetch(http, url)

    if error:
        return error, url, line, result, None, None

    # Forcing urllib3 to read data in thread
    data = result.data

    # Solving mime type
    (mimetype, _) = mimetypes.guess_type(url)

    if mimetype is None:
        mimetype = 'text/html'

    exts = mimetypes.guess_all_extensions(mimetype)

    if not exts:
        ext = '.html'
    else:
        ext = max(exts, key=len)

    # Solving encoding
    is_xml = ext == '.html' or ext == '.xml'

    encoding = guess_encoding(result, data, is_xml=is_xml, use_chardet=True)

    info = {
        'mime': mimetype,
        'ext': ext,
        'encoding': encoding
    }

    return error, url, line, result, data, info


def fetch_action(namespace):

    # Do we need to fetch only a single url?
    if namespace.file is sys.stdin and is_url(namespace.column):
        namespace.file = StringIO('url\n%s' % namespace.column)
        namespace.column = 'url'

    input_headers, pos, reader = custom_reader(namespace.file, namespace.column)
    filename_pos = input_headers.index(namespace.filename) if namespace.filename else None

    selected_fields = namespace.select.split(',') if namespace.select else None
    selected_pos = [input_headers.index(h) for h in selected_fields] if selected_fields else None

    # First we need to create the relevant directory
    if not namespace.contents_in_report:
        os.makedirs(namespace.output_dir, exist_ok=True)

    # Loading bar
    loading_bar = tqdm(
        desc='Fetching pages',
        total=namespace.total,
        dynamic_ncols=True,
        unit=' urls'
    )

    # Reading output
    output_headers = (input_headers if not selected_pos else [input_headers[i] for i in selected_pos])
    output_headers += OUTPUT_ADDITIONAL_HEADERS

    if namespace.contents_in_report:
        output_headers.append('raw_content')

    if namespace.output is None:
        output_file = DummyTqdmFile(sys.stdout)
    else:
        output_file = open(namespace.output, 'w')

    output_writer = csv.writer(output_file)
    output_writer.writerow(output_headers)

    # Creating the http pool manager
    http = PoolManager(
        cert_reqs='CERT_REQUIRED',
        ca_certs=certifi.where(),
        num_pools=namespace.threads * 2,
        maxsize=1, # NOTE: should be the same as group_parallelism,
        timeout=Timeout(connect=2.0, read=7.0)
    )

    # Generator yielding urls to fetch
    def payloads():
        for line in reader:
            url = line[pos].strip()

            if not url:

                # TODO: write report line all the same!
                loading_bar.update()
                continue

            yield (http, line, url)

    # Streaming the file and fetching the url using multiple threads
    multithreaded_iterator = imap_unordered(
        payloads(),
        worker,
        namespace.threads,
        group=get_domain_name,
        group_parallelism=1,
        group_buffer_size=25,
        group_throttle=namespace.throttle
    )

    errors = 0
    status_codes = Counter()

    for i, (error, url, line, result, data, info) in enumerate(multithreaded_iterator):

        content_write_flag = 'wb'

        # Updating stats
        if error is not None:
            errors += 1
        else:
            if result.status >= 400:
                status_codes[result.status] += 1

        postfix = {'errors': errors}

        for code, count in status_codes.most_common(1):
            postfix[str(code)] = count

        loading_bar.set_postfix(**postfix)
        loading_bar.update()

        # No error
        if error is None:

            filename = None

            # Building filename
            if filename_pos is not None:
                filename = line[filename_pos] + info['ext']
            else:
                # NOTE: it would be nice to have an id that can be sorted by time
                filename = str(uuid4()) + info['ext']

            # Standardize encoding?
            encoding = info['encoding']

            if namespace.standardize_encoding or namespace.contents_in_report:
                if encoding is None or encoding != 'utf-8' or namespace.contents_in_report:
                    data = data.decode(encoding, errors='replace')
                    encoding = 'utf-8'
                    content_write_flag = 'w'

            # Writing file on disk
            if not namespace.contents_in_report:
                with open(join(namespace.output_dir, filename), content_write_flag) as f:
                    f.write(data)

            # Reporting in output
            if selected_pos:
                line = [line[i] for i in selected_pos]

            line.extend([i, result.status, '', filename, encoding or ''])

            if namespace.contents_in_report:
                line.append(data)

            output_writer.writerow(line)

        # Handling potential errors
        else:
            reporter = ERROR_REPORTERS.get(type(error), repr)

            error_code = reporter(error) if callable(reporter) else reporter

            # Reporting in output
            if selected_pos:
                line = [line[i] for i in selected_pos]

            line.extend([i, '', error_code, '', ''])
            output_writer.writerow(line)

    # Closing files
    if namespace.output is not None:
        output_file.close()
