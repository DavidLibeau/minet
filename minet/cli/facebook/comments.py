# =============================================================================
# Minet Facebook Comments CLI Action
# =============================================================================
#
# Logic of the `fb comments` action.
#
import csv
from tqdm import tqdm
from ural.facebook import is_facebook_post_url

from minet.cli.utils import open_output_file, die
from minet.facebook.comments import FacebookCommentScraper
from minet.facebook.constants import FACEBOOK_COMMENT_CSV_HEADERS
from minet.facebook.exceptions import FacebookInvalidCookieError


def facebook_comments_action(namespace):

    # Handling output
    output_file = open_output_file(namespace.output)

    writer = csv.writer(output_file)
    writer.writerow(FACEBOOK_COMMENT_CSV_HEADERS)

    # Loading bar
    loading_bar = tqdm(
        desc='Scraping comments',
        dynamic_ncols=True,
        unit=' comments'
    )

    if not is_facebook_post_url(namespace.url):
        die('Given url is not a Facebook post url: %s' % namespace.url)

    try:
        scraper = FacebookCommentScraper(namespace.cookie)
    except FacebookInvalidCookieError:
        if namespace.cookie in ['firefox', 'chrome']:
            die('Could not extract cookies from %s.' % namespace.cookie)

        die([
            'Relevant cookie not found.',
            'A Facebook authentication cookie is necessary to be able to access Facebook post comments.',
            'Use the --cookie flag to choose a browser from which to extract the cookie or give your cookie directly.'
        ])

    batches = scraper(
        namespace.url,
        per_call=True,
        detailed=True,
        format='csv_row'
    )

    for details, batch in batches:
        for comment in batch:
            writer.writerow(comment)

        loading_bar.update(len(batch))
        loading_bar.set_postfix(
            calls=details['calls'],
            replies=details['replies'],
            q=details['queue_size'],
            posts=1
        )

    loading_bar.close()
