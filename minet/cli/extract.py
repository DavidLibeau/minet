# =============================================================================
# Minet Extract Content CLI Action
# =============================================================================
#
# Logic of the extract action.
#
import casanova
import gzip
import codecs
from multiprocessing import Pool
from trafilatura.core import bare_extraction
from tqdm import tqdm

from minet.encodings import is_supported_encoding
from minet.utils import fix_ensure_ascii_json_string
from minet.cli.utils import (
    open_output_file,
    create_report_iterator
)
from minet.cli.reporters import report_error

from minet.exceptions import UnknownEncodingError

OUTPUT_ADDITIONAL_HEADERS = [
    'extract_error',
    'canonical_url',
    'title',
    'description',
    'raw_content',
    'comments',
    'author',
    'categories',
    'tags',
    'date',
    'sitename'
]

PADDING = [''] * (len(OUTPUT_ADDITIONAL_HEADERS) - 1)


def singular(result, key, fix=False):
    v = result.get(key, '') or ''

    if fix:
        return fix_ensure_ascii_json_string(v)

    return v


def format_trafilatura_result(result):
    return [
        '',
        singular(result, 'url'),
        singular(result, 'title'),
        singular(result, 'description'),
        singular(result, 'text'),
        singular(result, 'comments'),
        singular(result, 'author', fix=True),
        '|'.join(result.get('categories', [])),
        '|'.join(result.get('tags', [])),
        singular(result, 'date'),
        singular(result, 'sitename')
    ]


def worker(payload):
    row, _, path, encoding, content, _ = payload

    if not is_supported_encoding(encoding):
        return UnknownEncodingError('Unknown encoding: "%s"' % encoding), row, None

    # Reading file
    if content is None:
        try:
            if path.endswith('.gz'):
                with open(path, 'rb') as f:
                    raw_html_bytes = gzip.decompress(f.read())

                raw_html = raw_html_bytes.decode(encoding, errors='replace')
            else:
                with codecs.open(path, 'r', encoding=encoding, errors='replace') as f:
                    raw_html = f.read()
        except UnicodeDecodeError as e:
            return e, row, None
    else:
        raw_html = content

    # Attempting extraction
    try:
        # https://trafilatura.readthedocs.io/en/latest/corefunctions.html
        # TODO: discuss deduplication
        # TODO: fallback options
        result = bare_extraction(raw_html)
    except BaseException as e:
        return e, row, None

    return None, row, result


def extract_action(namespace):
    output_file = open_output_file(namespace.output)

    enricher = casanova.enricher(
        namespace.report,
        output_file,
        keep=namespace.select,
        add=OUTPUT_ADDITIONAL_HEADERS
    )

    loading_bar = tqdm(
        desc='Extracting content',
        total=namespace.total,
        dynamic_ncols=True,
        unit=' docs'
    )

    files = create_report_iterator(namespace, enricher, loading_bar=loading_bar)

    with Pool(namespace.processes) as pool:
        for error, row, result in pool.imap_unordered(worker, files):
            loading_bar.update()

            if error is not None:
                enricher.writerow(row, [report_error(error)] + PADDING)
                continue

            if result is None:
                enricher.writerow(row, ['no-content'] + PADDING)
            try:
                enricher.writerow(row, format_trafilatura_result(result))
            except UnicodeError:
                print(result)
                raise

    output_file.close()
