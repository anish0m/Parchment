"""Small helpers for views that serve both full pages and HTMX fragments."""

from django.core.paginator import Paginator


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
