# =============================================================================
# Minet Hyphe Dump CLI Action
# =============================================================================
#
# Logic of the `hyphe dump` action.
#
import os
import csv
import base64
import zlib
import gzip
from os.path import join, dirname

from minet.utils import md5
from minet.cli.utils import die, LoadingBar
from minet.hyphe import HypheAPIClient
from minet.hyphe.formatters import format_webentity_for_csv, format_page_for_csv
from minet.hyphe.constants import WEBENTITY_CSV_HEADERS, PAGE_CSV_HEADERS
from minet.hyphe.exceptions import HypheCorpusAuthenticationError

ADDITIONAL_PAGE_HEADERS = ["filename"]


def format_page_filename(webentity, page):
    h = md5(page["url"])

    # TODO: could be something other than html?
    return "%s/%s/%s.html.gz" % (webentity["id"], h[:2], h)


def hyphe_dump_action(cli_args):

    # Paths
    output_dir = "hyphe_corpus_%s" % cli_args.corpus

    if cli_args.output_dir is not None:
        output_dir = cli_args.output_dir

    os.makedirs(output_dir, exist_ok=True)

    webentities_output_path = join(output_dir, "webentities.csv")
    pages_output_path = join(output_dir, "pages.csv")

    if cli_args.body:
        body_output_dir = join(output_dir, "content")
        os.makedirs(body_output_dir, exist_ok=True)

    client = HypheAPIClient(cli_args.url)
    corpus = client.corpus(cli_args.corpus, password=cli_args.password)

    try:
        corpus.ensure_is_started()
    except HypheCorpusAuthenticationError:
        die(
            [
                'Wrong password for the "%s" corpus!' % cli_args.corpus,
                "Don't forget to provide a password for this corpus using --password",
            ]
        )

    # Then we gather some handy statistics
    counts = corpus.count(statuses=cli_args.statuses)

    # Then we fetch webentities
    webentities_file = open(webentities_output_path, "w", encoding="utf-8")
    webentities_writer = csv.writer(webentities_file)
    webentities_writer.writerow(WEBENTITY_CSV_HEADERS)

    loading_bar = LoadingBar(
        desc="Paginating web entities",
        unit="webentity",
        unit_plural="webentities",
        total=counts["webentities"],
    )

    webentities = {}

    for webentity in corpus.webentities(statuses=cli_args.statuses):
        loading_bar.update()
        webentities[webentity["id"]] = webentity
        webentities_writer.writerow(format_webentity_for_csv(webentity))

    webentities_file.close()
    loading_bar.close()

    # Finally we paginate pages
    pages_file = open(pages_output_path, "w", encoding="utf-8")
    pages_writer = csv.writer(pages_file)
    pages_writer.writerow(
        PAGE_CSV_HEADERS + (ADDITIONAL_PAGE_HEADERS if cli_args.body else [])
    )

    loading_bar = LoadingBar(desc="Fetching pages", unit="page", total=counts["pages"])

    for webentity in webentities.values():
        for page in corpus.webentity_pages(webentity["id"], include_body=cli_args.body):
            loading_bar.update()

            filename = None

            if cli_args.body and "body" in page:
                filename = format_page_filename(webentity, page)
                filepath = join(body_output_dir, filename)
                os.makedirs(dirname(filepath), exist_ok=True)

                with open(filter, "wb") as f:
                    binary = base64.b64decode(page["body"])
                    binary = zlib.decompress(binary)
                    binary = gzip.compress(binary)  # TODO: use gzip.open rather

                    f.write(binary)

            pages_writer.writerow(
                format_page_for_csv(webentity, page, filename=filename)
            )
