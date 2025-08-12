import logging
import requests
import google.generativeai as genai
import os
import json
from bs4 import BeautifulSoup
from datetime import datetime
from pydantic import BaseModel, HttpUrl, ValidationError
from typing import List

from django.core.management.base import BaseCommand
from news.models import NewsListPage, NewsArticlePage, ScrapingSource

logger = logging.getLogger(__name__)

class Article(BaseModel):
    title: str
    summary: str
    source_url: HttpUrl

class ArticleList(BaseModel):
    articles: List[Article]

def clean_json_response(text):
    """
    Extracts the first valid JSON object from a string.
    Returns None if not found.
    """
    if not isinstance(text, str):
        return None
    json_start = text.find('{')
    json_end = text.rfind('}')
    if json_start == -1 or json_end == -1:
        return None
    return text[json_start:json_end+1]

class Command(BaseCommand):
    help = 'Scrapes news articles from all active sources defined in Wagtail Snippets.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, help='Scrape only a single source by its name.'
        )

    def handle(self, *args, **options):
        try:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY not found.")
            genai.configure(api_key=api_key)
        except ValueError as e:
            logger.error(f"Config failed: {e}")
            return

        if options['source']:
            sources = ScrapingSource.objects.filter(name__iexact=options['source'], is_active=True)
            if not sources:
                logger.error(f"No active source named '{options['source']}' found.")
                return
        else:
            sources = ScrapingSource.objects.filter(is_active=True)

        news_list_page = NewsListPage.objects.live().first()
        if not news_list_page:
            logger.error("A 'NewsListPage' must be created in Wagtail first.")
            return

        for source in sources:
            logger.info(f"Scraping source: {source.name}")
            self.scrape_source(source, news_list_page)

        logger.info("All scraping tasks complete.")

    def scrape_source(self, source: ScrapingSource, news_list_page: NewsListPage):
        try:
            response = requests.get(source.url_to_scrape)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            main_content = soup.select_one(source.html_selector)
            if not main_content:
                logger.error(f"Could not find selector '{source.html_selector}' on page.")
                return
            html_snippet = main_content.prettify()
        except requests.exceptions.RequestException as e:
            logger.error(f"URL fetch error: {e}")
            return

        prompt = f"""
        Analyze the following HTML content. Extract the 20 most recent articles.
        Your response MUST be a single, valid JSON object.
        The JSON object must have one key: "articles", a list of objects, each with keys: "title", "summary", "source_url".
        The summary should describe the article as briefly as possible while capturing the main idea.
        Resolve all URLs to be absolute, using '{source.base_url}' as the base.
        HTML: {html_snippet}
        """

        try:
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = model.generate_content(prompt)
            if not response.parts:
                logger.error("Gemini returned an empty response.")
                logger.error(f"Reason: {response.prompt_feedback}")
                return
            cleaned_response = clean_json_response(response.text)
            if cleaned_response is None:
                logger.error("Could not find a valid JSON object in Gemini's response.")
                logger.error(f"--- RAW RESPONSE ---\n{response.text}\n---")
                return
            parsed_data = json.loads(cleaned_response)
            validated_articles = ArticleList(**parsed_data)
        except Exception as e:
            logger.error(f"Gemini processing failed: {e}")
            return

        for article_data in validated_articles.articles:
            try:
                existing_page = NewsArticlePage.objects.get(source_url=str(article_data.source_url))
                existing_page.title = article_data.title
                existing_page.summary = article_data.summary
                existing_page.save()
                logger.info(f"Updated: '{existing_page.title}'")
            except NewsArticlePage.DoesNotExist:
                new_page = NewsArticlePage(
                    title=article_data.title,
                    summary=article_data.summary,
                    source_url=str(article_data.source_url),
                    publication_date=datetime.now().date(),
                    slug=f"article-gemini-{hash(article_data.title) % 100000}"
                )
                news_list_page.add_child(instance=new_page)
                logger.info(f"Added: '{new_page.title}'")
