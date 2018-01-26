import scrapy
from urllib.parse import urlparse
import logging

from scrapy.exceptions import CloseSpider
from scrapy.utils.markup import remove_tags
from urllib.parse import urljoin


class BlogSpider(scrapy.Spider):
    name = "blogs"
    POST_PER_RSS = 5
    RSS_PER_POST = 5
    BLOG_LIMIT = 10
    INITIAL_URL_FILE = 'urls.txt'

    def start_requests(self):
        urls = [urljoin(url, '/rss/') for url in open(self.INITIAL_URL_FILE).read().split('\n')]
        print(urls)
        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse_rss)

    def parse_rss(self, response):
        posts_link = response.css('item link::text').extract()[:self.POST_PER_RSS]
        posts_title = response.css('item title::text').extract()[:self.POST_PER_RSS]
        posts_descriptions = response.css('item description::text').extract()[:self.POST_PER_RSS]
        posts_descriptions = [remove_tags(desc) for desc in posts_descriptions]
        meta_data = {
            'blog_name': response.css('channel>title::text').extract()[0],
            'blog_url': response.url,
            'posts_link': posts_link,
            'next_link': posts_link[1:],
            'posts_full_content': [],
            'posts_content': posts_descriptions,
            'posts_title': posts_title
        }
        if posts_link:
            yield scrapy.Request(url=posts_link[0], callback=self.parse, meta=meta_data)
        else:
            result = {
                'type': 'blog',
                'blog_name': meta_data['blog_name'],
                'blog_url': meta_data['blog_url']
            }
            yield result
            self.BLOG_LIMIT -= 1

    @staticmethod
    def is_bayan(url):
        parsed_url = urlparse(url)
        return parsed_url.netloc.endswith('.blog.ir')

    def parse(self, response):
        other_blogs = response.xpath("//a[@name='comments']/..//a/@href").extract()
        bayan_blogs = ['https://' + urlparse(url).netloc for url in other_blogs if self.is_bayan(url)][
                      :self.RSS_PER_POST]
        rss_links = [url + '/rss/' for url in bayan_blogs]
        rss_links = rss_links
        for url in rss_links:
            yield scrapy.Request(url=url, callback=self.parse_rss)

        yield {'type': 'post',
               'blog_url': urlparse(response.url).netloc,
               'post_url': response.url,
               'comment_urls': bayan_blogs}

        # extract post content
        post_content = response.css('.post .cnt').extract()
        post_content += response.css('.post .post-content').extract()
        post_content += response.css('.block-post .block-post-content').extract()
        post_content += response.css('.post-wrp .post-content').extract()
        post_content += response.css('.post .post-matn').extract()
        post_content += response.css('.post .context').extract()
        post_content += response.css('article').extract()
        post_content += response.css('.postbody').extract()
        post_content += response.css('.contentbar .contentbarcontent').extract()
        post_content += response.css('.sub-body .text').extract()
        if not post_content:
            logging.debug("Coudln't find content in %s" % response.url)
        post_content = '\n'.join(post_content)
        post_content = remove_tags(post_content)

        response.meta['posts_full_content'].append(post_content)
        if response.meta['next_link']:
            link = response.meta['next_link'].pop(0)
            yield scrapy.Request(url=link, callback=self.parse, meta=response.meta)
        else:
            result = {
                'type': 'blog',
                'blog_name': response.meta['blog_name'],
                'blog_url': response.meta['blog_url']
            }
            for i in range(len(response.meta['posts_link'])):
                x = i + 1
                result['post_url_%d' % x] = response.meta['posts_link'][i]
                result['post_title_%d' % x] = response.meta['posts_title'][i]
                result['post_full_content_%d' % x] = response.meta['posts_full_content'][i]
                result['post_content_%d' % x] = response.meta['posts_content'][i]
            yield result
            self.BLOG_LIMIT -= 1
            # because of multi-threading, this is an approximate only
            # some better/more complex solution exist by using the item pipelines
            if self.BLOG_LIMIT <= 0:
                raise CloseSpider("Reached blog limit, shutting down spider")
