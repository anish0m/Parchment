from rest_framework import pagination


class PageNumberPagination(pagination.PageNumberPagination):
    """?page=N, 30 items a page by default; ?page_size= up to 100."""

    page_size_query_param = "page_size"
    max_page_size = 100
