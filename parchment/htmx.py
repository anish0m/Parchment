"""Small helpers for views that serve both full pages and HTMX fragments."""

from urllib.parse import urlsplit

from django.core.paginator import Paginator
from django.http import QueryDict


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def wants_fragment(request, target_id):
    """True when HTMX asks to replace just the element with this id.

    History restores (back button after a cache miss) need the full page,
    so they never get a fragment.
    """
    return (
        is_htmx(request)
        and request.headers.get("HX-Target") == target_id
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


def paginate(queryset, page_number, per_page):
    """Returns the requested page; out-of-range or invalid numbers fall back to a valid page.

    The page also carries `elided_range` (e.g. 1 … 4 5 6 … 20) for the page links,
    since templates can't call get_elided_page_range() with arguments.
    """
    page = Paginator(queryset, per_page).get_page(page_number)
    page.elided_range = list(
        page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
    )
    return page


def current_query(request):
    """Query parameters of the page the user is looking at.

    For HTMX requests this comes from the HX-Current-URL header, so a list can be
    re-rendered after an add or delete with the same filters and page.
    """
    current = request.headers.get("HX-Current-URL")
    if is_htmx(request) and current:
        return QueryDict(urlsplit(current).query)
    return request.GET
