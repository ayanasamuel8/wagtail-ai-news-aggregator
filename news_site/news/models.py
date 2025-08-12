from django.db import models
from wagtail.models import Page
from wagtail.admin.panels import FieldPanel
from wagtail.snippets.models import register_snippet
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

class NewsArticlePage(Page):
    publication_date = models.DateField("Publication Date")
    summary = models.TextField(blank=True)
    source_url = models.URLField(max_length=255, unique=True)
    source_name = models.CharField(max_length=100, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('publication_date'),
        FieldPanel('summary'),
        FieldPanel('source_url'),
    ]

    parent_page_types = ['news.NewsListPage']
    subpage_types = []

class NewsListPage(Page):
    template = "news/news_list_page.html"
    subpage_types = ['news.NewsArticlePage']

    def get_context(self, request, *args, **kwargs):
        """
        Adds paginated NewsArticlePage objects to the context.
        """
        context = super().get_context(request, *args, **kwargs)
        all_articles = NewsArticlePage.objects.live().public().order_by('-publication_date')
        paginator = Paginator(all_articles, 10)
        page = request.GET.get('page')
        try:
            articles = paginator.page(page)
        except PageNotAnInteger:
            articles = paginator.page(1)
        except EmptyPage:
            articles = paginator.page(paginator.num_pages)
        context['articles'] = articles
        return context

@register_snippet
class ScrapingSource(models.Model):
    """
    Stores configuration for a news scraping source.
    """
    name = models.CharField(
        max_length=255,
        help_text="A descriptive name for the source, e.g., 'BBC Technology'"
    )
    url_to_scrape = models.URLField(
        "URL to Scrape",
        help_text="The URL of the page that lists the articles."
    )
    base_url = models.URLField(
        "Base URL",
        help_text="The base URL used to resolve relative links (e.g., 'https://www.bbc.com')."
    )
    html_selector = models.CharField(
        max_length=255,
        help_text="The CSS selector for the main content area (e.g., 'main#main-content')."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck this to temporarily disable scraping for this source."
    )

    panels = [
        FieldPanel('name'),
        FieldPanel('url_to_scrape'),
        FieldPanel('base_url'),
        FieldPanel('html_selector'),
        FieldPanel('is_active'),
    ]

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Scraping Source"
        verbose_name_plural = "Scraping Sources"
